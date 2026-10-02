"""The twelve agents, in execution order.

Each agent is a small, independently testable unit with an honest
:class:`~smartflow.models.AgentMaturity` label. Nothing here is a wrapper around
an LLM call that might not return; every agent is deterministic, and the only
optional AI components (YOLO detector, Groq wording) sit behind adapters with
working fallbacks.

Execution order is 1..12 and matches the case narrative:
perception -> intelligence -> action -> emergency -> optimisation -> compliance.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from .compliance import (
    OPEN_STATUSES,
    build_profile,
    notices_for_stage,
    prepare_enforcement_request,
)
from .config import DEFAULT_POLICY, PolicyConfig
from .db import Store
from .decision import decide, explain_decision
from .evidence import (
    cross_frame_agreement,
    hash_plate,
    seal_evidence,
    verify_bundle,
)
from .fuzzy import DEFAULT_ENGINE, FuzzyRiskEngine
from .integrations import (
    MockNADRAVerifier,
    MockPaymentGateway,
    MockVehicleRegistry,
    NotificationGateway,
    get_explanation_writer,
)
from .messages import render_dispute_ack
from .models import (
    AgentMaturity,
    AgentTrace,
    CameraEvent,
    Challan,
    ChallanStatus,
    ComplianceProfile,
    Decision,
    EnforcementRequest,
    EscalationStage,
    EvidenceBundle,
    RequestStatus,
    RiskLevel,
    VehicleIdentity,
    ViolationType,
    utcnow,
)
from .penalty import compute_penalty, payment_plan
from .prediction import (
    estimate_collision_risk,
    optimise_signals,
    plan_ambulance_corridor,
)


# --------------------------------------------------------------------------- #
# Shared context
# --------------------------------------------------------------------------- #
@dataclass
class AgentContext:
    """Mutable state threaded through the pipeline."""

    run_id: str
    scenario: str
    as_of: datetime
    config: PolicyConfig = DEFAULT_POLICY
    store: Store = field(default_factory=Store)
    registry: MockVehicleRegistry = field(default_factory=MockVehicleRegistry)
    nadra: MockNADRAVerifier | None = None
    payments: MockPaymentGateway = field(default_factory=MockPaymentGateway)
    notifications: NotificationGateway = field(default_factory=NotificationGateway)
    writer: Any = None
    engine: FuzzyRiskEngine = DEFAULT_ENGINE
    state: dict[str, Any] = field(default_factory=dict)
    traces: list[AgentTrace] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.nadra is None:
            self.nadra = MockNADRAVerifier(self.registry)
        if self.writer is None:
            self.writer = get_explanation_writer(False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def put(self, key: str, value: Any) -> Any:
        self.state[key] = value
        return value

    def require(self, key: str) -> Any:
        if key not in self.state:
            raise KeyError(
                f"agent pipeline is out of order: {key!r} was requested before it "
                f"was produced. Present keys: {sorted(self.state)}"
            )
        return self.state[key]

    def log(self, kind: str, actor: str, detail: str, **payload: Any) -> None:
        self.store.log_event(
            kind=kind,
            actor=actor,
            challan_id=self.state.get("challan_id"),
            plate=self.state.get("plate"),
            detail=detail,
            payload=payload or None,
            at=self.as_of,
        )


class Agent:
    name = "agent"
    level = 0
    maturity = AgentMaturity.MOCK

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        raise NotImplementedError

    def run(self, ctx: AgentContext) -> str:
        started = time.perf_counter()
        verdict, details = self.execute(ctx)
        ctx.traces.append(
            AgentTrace(
                run_id=ctx.run_id,
                agent=self.name,
                level=self.level,
                maturity=self.maturity,
                verdict=verdict,
                details=dict(details),
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                at=ctx.as_of,
            )
        )
        return verdict


# --------------------------------------------------------------------------- #
# Level 1 -- Perception
# --------------------------------------------------------------------------- #
class DetectionAgent(Agent):
    name = "1. Detection"
    level = 1
    maturity = AgentMaturity.MOCK

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        event: CameraEvent = ctx.require("event")
        violation = event.violations[0] if event.violations else None
        ctx.put("violation", violation)
        labels = ", ".join(v.value for v in event.violations) or "NO_VIOLATION"
        verdict = (
            f"DETECTED {labels} at {event.camera_id} "
            f"({len(event.frames)} frames, density {event.traffic_density:.0f})"
        )
        return verdict, {
            "camera_id": event.camera_id,
            "location": event.location,
            "violations": [v.value for v in event.violations],
            "frame_count": len(event.frames),
            "speed_kmh": event.speed_kmh,
            "speed_limit_kmh": event.speed_limit_kmh,
            "traffic_density": event.traffic_density,
            "context_tags": list(event.context_tags),
            "implementation": "synthetic frames; swap in vision/yolo_adapter.py",
        }


class ANPRAgent(Agent):
    name = "2. ANPR & Registry"
    level = 1
    maturity = AgentMaturity.MOCK

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        plate: str = ctx.require("plate")
        identity: VehicleIdentity = ctx.registry.resolve(plate)
        ctx.put("identity", identity)
        nadra_record = ctx.nadra.verify_owner(identity.plate, requested_by=ctx.run_id)
        ctx.put("nadra_record", nadra_record)
        verdict = (
            f"PLATE {identity.plate} ({identity.anpr_confidence:.1f}% confidence) "
            f"owner {identity.owner_name_masked} / {identity.cnic_masked}"
        )
        return verdict, {
            "plate": identity.plate,
            "city": identity.city,
            "vehicle": identity.vehicle_make,
            "owner_masked": identity.owner_name_masked,
            "cnic_masked": identity.cnic_masked,
            "registered_owner_liable": identity.registered_owner_liable,
            "registry_reference": identity.registry_reference,
            "nadra_simulation": nadra_record["simulation"],
            "nadra_network_calls": nadra_record["network_calls"],
        }


# --------------------------------------------------------------------------- #
# Level 2 -- Intelligence
# --------------------------------------------------------------------------- #
class EvidenceVerificationAgent(Agent):
    name = "3. Evidence Verification"
    level = 2
    maturity = AgentMaturity.DEEP

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        event: CameraEvent = ctx.require("event")
        violation = ctx.require("violation")
        if violation is None:
            verdict = "NO_VIOLATION_TO_SEAL"
            return verdict, {"reason": "detector reported no violation"}
        confidence = cross_frame_agreement(event.frames, violation.value)
        bundle = seal_evidence(event.event_id, event.frames, sealed_at=ctx.as_of)
        verified = verify_bundle(bundle)
        ctx.put("evidence", bundle)
        ctx.put("evidence_confidence", confidence)
        ctx.log(
            "EVIDENCE_SEALED",
            self.name,
            f"root={bundle.root_hash[:16]} frames={bundle.frame_count}",
            confidence=confidence,
        )
        verdict = (
            f"SEALED root {bundle.root_hash[:16]}… frames {bundle.frame_count} "
            f"confidence {confidence:.1f}% re-verified={verified}"
        )
        return verdict, {
            "root_hash": bundle.root_hash,
            "frame_count": bundle.frame_count,
            "frame_digests": list(bundle.frame_digests),
            "confidence": confidence,
            "verification": verified,
        }


class RiskContextAgent(Agent):
    name = "4. Risk & Context"
    level = 2
    maturity = AgentMaturity.HEURISTIC

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        event: CameraEvent = ctx.require("event")
        violation = ctx.require("violation")
        config = ctx.config
        severity = config.severity_for_event(event.violations)
        context_factor = config.context_factor(event.context_tags)
        ctx.put("severity", severity)
        ctx.put("context", context_factor)
        ctx.put("density", event.traffic_density)
        per_violation = {
            v.value: config.severity_for(v) for v in event.violations
        }
        verdict = (
            f"SEVERITY {severity:.0f} | CONTEXT {context_factor:.0f} "
            f"[{', '.join(event.context_tags) or 'none'}] | DENSITY "
            f"{event.traffic_density:.0f}"
        )
        return verdict, {
            "severity": severity,
            "severity_by_violation": per_violation,
            "compounding_bonus": round(
                severity - max(per_violation.values(), default=0.0), 1
            ),
            "context_factor": context_factor,
            "traffic_density": event.traffic_density,
            "context_tags": list(event.context_tags),
            "policy_source": "PolicyConfig.severity_scores / context_scores",
        }


class PredictiveSafetyAgent(Agent):
    name = "5. Predictive Safety"
    level = 2
    maturity = AgentMaturity.HEURISTIC

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        event: CameraEvent = ctx.require("event")
        estimate = estimate_collision_risk(
            speed_kmh=event.speed_kmh,
            speed_limit_kmh=event.speed_limit_kmh,
            traffic_density=ctx.require("density"),
            context_factor=ctx.require("context"),
        )
        ctx.put("collision", estimate.score)
        ctx.put("collision_estimate", estimate)
        verdict = (
            f"COLLISION RISK {estimate.score:.0f}/100 "
            f"(TTC {estimate.time_to_collision_s:.1f}s, "
            f"excess {estimate.speed_excess_pct:.0f}%)"
        )
        return verdict, {
            "collision_risk": estimate.score,
            "time_to_collision_s": estimate.time_to_collision_s,
            "speed_excess_pct": estimate.speed_excess_pct,
            "components": dict(estimate.components),
            "note": estimate.note,
        }


class FuzzyDecisionAgent(Agent):
    name = "6. Fuzzy Decision"
    level = 2
    maturity = AgentMaturity.DEEP

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        inputs = {
            "evidence": ctx.require("evidence_confidence"),
            "severity": ctx.require("severity"),
            "collision": ctx.require("collision"),
            "density": ctx.require("density"),
            "context": ctx.require("context"),
        }
        assessment = ctx.engine.evaluate(inputs)
        decision: Decision = decide(assessment, ctx.config)
        ctx.put("inputs", inputs)
        ctx.put("assessment", assessment)
        ctx.put("decision", decision)
        ctx.log(
            "DECISION",
            self.name,
            f"score={assessment.score:.1f} level={decision.risk.level.value} "
            f"challan={decision.issue_challan}",
            inputs=inputs,
            actions=list(decision.actions),
        )
        verdict = (
            f"RISK {decision.risk.score:.1f}/100 -> {decision.risk.level.value} | "
            f"challan={decision.issue_challan} | actions="
            f"{','.join(a.lower() for a in decision.actions)}"
        )
        return verdict, {
            "inputs": inputs,
            "score": decision.risk.score,
            "level": decision.risk.level.value,
            "actions": list(decision.actions),
            "issue_challan": decision.issue_challan,
            "needs_human_review": decision.needs_human_review,
            "top_rules": [f.label for f in assessment.rule_firings[:3]],
            "contributions": dict(assessment.contributions),
            "overlay_or_gate": decision.rationale,
        }


# --------------------------------------------------------------------------- #
# Level 3 -- Action
# --------------------------------------------------------------------------- #
class ActionNotificationAgent(Agent):
    name = "7. Action & Notification"
    level = 3
    maturity = AgentMaturity.HEURISTIC

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        decision: Decision = ctx.require("decision")
        identity: VehicleIdentity = ctx.require("identity")
        violation: ViolationType = ctx.require("violation")
        bundle: EvidenceBundle = ctx.require("evidence")
        event: CameraEvent = ctx.require("event")
        config = ctx.config

        if not decision.issue_challan:
            ctx.put("challan", None)
            ctx.log(
                "NO_CHALLAN",
                self.name,
                decision.rationale[:180],
                score=decision.risk.score,
            )
            return (
                f"NO_CHALLAN ({decision.risk.level.value}, score "
                f"{decision.risk.score:.1f}) - logged for review",
                {"issue_challan": False, "rationale": decision.rationale},
            )

        base_fine = config.fine_for(violation)
        challan = Challan(
            challan_id=f"CH-{event.captured_at:%y%m%d}-{identity.plate.replace('-', '')}",
            event_id=event.event_id,
            plate=identity.plate,
            violation_type=violation,
            base_fine=base_fine,
            issued_at=ctx.as_of,
            due_at=ctx.as_of + timedelta(days=config.penalty.due_days),
            risk_score=decision.risk.score,
            risk_level=decision.risk.level,
            evidence_root_hash=bundle.root_hash,
            evidence_frame_count=bundle.frame_count,
            status=ChallanStatus.ISSUED,
            explanation=ctx.writer.decision_explanation(
                plate=identity.plate,
                violation=violation.value.replace("_", " ").title(),
                risk_score=decision.risk.score,
                risk_level=decision.risk.level.value,
                top_factors=list(
                    sorted(
                        decision.risk.contributions.items(),
                        key=lambda kv: kv[1],
                        reverse=True,
                    )[:3]
                ),
                actions=decision.actions,
            ),
            policy_version=config.version,
            plate_hash=hash_plate(identity.plate, config.plate_salt),
        )
        ctx.put("challan", challan)
        ctx.put("challan_id", challan.challan_id)
        ctx.require("bundles")[challan.challan_id] = bundle
        ctx.require("challan_index")[challan.challan_id] = challan
        ctx.store.save_challan(challan)
        ctx.log(
            "CHALLAN_ISSUED",
            self.name,
            f"fine {base_fine:,.0f} due {challan.due_at.date().isoformat()}",
            evidence_root=challan.evidence_root_hash,
        )
        notice = ctx.notifications.send(
            EscalationStage.ISSUED, challan, config=config, sent_at=ctx.as_of
        )
        ctx.put("issued_notice", notice)
        verdict = (
            f"CHALLAN {challan.challan_id} issued fine PKR {base_fine:,.0f} "
            f"due {challan.due_at.date().isoformat()} + notice sent"
        )
        return verdict, {
            "challan_id": challan.challan_id,
            "base_fine": base_fine,
            "due_at": challan.due_at.isoformat(),
            "explanation": challan.explanation,
            "notice_channels": notice.channel,
        }


class ExplainabilityDisputeAgent(Agent):
    name = "8. Explainability & Dispute"
    level = 3
    maturity = AgentMaturity.DEEP

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        decision: Decision = ctx.require("decision")
        bundles: dict[str, EvidenceBundle] = ctx.require("bundles")
        challans: dict[str, Challan] = ctx.require("challan_index")

        lines = explain_decision(decision, top=3)
        ctx.put("explanation_lines", lines)

        failures = [
            challan_id
            for challan_id, bundle in bundles.items()
            if not verify_bundle(bundle)
        ]
        cancelled: list[str] = []
        for challan_id in failures:
            challan = challans.get(challan_id)
            if challan is None:
                continue
            cancelled.append(challan_id)
            ctx.store.update_challan_status(challan_id, ChallanStatus.CANCELLED.value)
            ctx.store.log_event(
                kind="APPEAL_UPHELD",
                actor=self.name,
                challan_id=challan_id,
                plate=challan.plate,
                detail=(
                    "Evidence bundle failed re-verification: the stored root hash "
                    "does not match the stored frames. Penalty cancelled."
                ),
                at=ctx.as_of,
            )
            ack = render_dispute_ack(challan_id, accepted=True)
            ctx.put("appeal_outcome", ack)

        if cancelled:
            verdict = (
                f"INTEGRITY_FAIL {len(cancelled)} bundle(s) -> CANCELLED "
                f"({', '.join(cancelled)}); citizen appeal upheld automatically"
            )
        elif failures:
            verdict = f"INTEGRITY_FAIL {len(failures)} bundle(s) with no matching challan"
        else:
            verdict = (
                f"EXPLAINED {len(bundles)} bundle(s) intact; "
                f"reason codes: {', '.join(decision.actions)}"
            )

        return verdict, {
            "explanation": lines,
            "bundles_checked": len(bundles),
            "failures": failures,
            "cancelled_challans": cancelled,
            "citizen_rights": "view evidence, dispute, request payment plan",
        }


# --------------------------------------------------------------------------- #
# Level 4 -- Emergency
# --------------------------------------------------------------------------- #
class AmbulancePriorityAgent(Agent):
    name = "9. Ambulance Priority"
    level = 4
    maturity = AgentMaturity.HEURISTIC

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        if not ctx.get("ambulance", False):
            return "NO_EMERGENCY_ACTIVE (corridor monitoring normal)", {
                "emergency": False
            }
        plan = plan_ambulance_corridor(
            ambulance_plate=ctx.get("ambulance_plate", "AMB-0000"),
            route=ctx.get("ambulance_route", "Route B"),
            traffic_density=ctx.require("density"),
        )
        ctx.put("ambulance_plan", plan)
        ctx.log(
            "EMERGENCY_CORRIDOR",
            self.name,
            f"{plan['ambulance_plate']} on {plan['recommended_route']} "
            f"clearance {plan['estimated_corridor_clearance_s']:.0f}s",
        )
        verdict = (
            f"CORRIDOR PLAN {plan['ambulance_plate']} via "
            f"{plan['recommended_route']} - clearance ~"
            f"{plan['estimated_corridor_clearance_s']:.0f}s across "
            f"{len(plan['signal_preemptions'])} junctions"
        )
        return verdict, dict(plan)


# --------------------------------------------------------------------------- #
# Level 5 -- Optimisation
# --------------------------------------------------------------------------- #
class TrafficOptimizationAgent(Agent):
    name = "10. Traffic Optimisation"
    level = 5
    maturity = AgentMaturity.HEURISTIC

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        density = ctx.require("density")
        serious = 1 if ctx.require("decision").risk.level in (
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        ) else 0
        serious += int(ctx.get("history_serious_count", 0))
        plan = optimise_signals(
            traffic_density=density,
            serious_violations=serious,
            emergency_active=bool(ctx.get("ambulance", False)),
            corridor=ctx.get("corridor", "Main corridor"),
        )
        ctx.put("optimisation_notes", plan["rationale"])
        ctx.put("signal_plan", plan)
        verdict = (
            f"SIGNAL PLAN green {plan['proposed_green_seconds']}s in a "
            f"{plan['cycle_seconds']}s cycle | safety hold="
            f"{plan['safety_hold']}"
        )
        return verdict, dict(plan)


# --------------------------------------------------------------------------- #
# Level 6 -- Compliance & recovery
# --------------------------------------------------------------------------- #
class SmartComplianceAgent(Agent):
    name = "11. Smart Compliance"
    level = 6
    maturity = AgentMaturity.DEEP

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        challan: Challan | None = ctx.get("challan")
        history: Sequence[Challan] = ctx.get("history", ())
        all_challans = [c for c in [*history, challan] if c is not None]
        plate = ctx.require("plate")
        prior_notices = int(ctx.get("notices_sent_prior", 0))
        payments_attempted = int(ctx.get("payment_attempts", 0))
        disputes = int(ctx.get("disputes_open", 0))

        profile = build_profile(
            plate=plate,
            challans=all_challans,
            notices_sent=prior_notices,
            payment_attempts=payments_attempted,
            disputes_open=disputes,
            as_of=ctx.as_of,
            config=ctx.config,
        )

        # Back-fill the notification ladder at historically correct timestamps,
        # so the audit trail shows a realistic 100+ day history rather than
        # every notice arriving in the same second. The ladder belongs to the
        # vehicle's OLDEST unpaid case -- that is the case being escalated.
        sent_now = 0
        open_history = [c for c in all_challans if c.status in OPEN_STATUSES]
        anchor = min((c.issued_at for c in open_history), default=ctx.as_of)
        ladder_target = open_history[0] if open_history else challan
        for stage in notices_for_stage(profile, ctx.config.escalation):
            stage_policy = ctx.config.escalation.stage_policy(stage)
            if ladder_target is None:
                continue
            sent_at = anchor + timedelta(days=stage_policy.after_days)
            if sent_at > ctx.as_of:
                sent_at = ctx.as_of
            ctx.notifications.send(
                stage, ladder_target, config=ctx.config, sent_at=sent_at
            )
            sent_now += 1

        final_profile = build_profile(
            plate=plate,
            challans=all_challans,
            notices_sent=prior_notices + sent_now,
            payment_attempts=payments_attempted,
            disputes_open=disputes,
            as_of=ctx.as_of,
            config=ctx.config,
        )
        ctx.put("compliance", final_profile)
        ctx.store.save_compliance_snapshot(plate, final_profile, at=ctx.as_of)
        ctx.log(
            "COMPLIANCE_SCORED",
            self.name,
            f"{final_profile.score:.1f}/100 {final_profile.tier.value} "
            f"stage={final_profile.recommended_stage.value}",
            reasons=list(final_profile.reasons),
        )

        request: EnforcementRequest | None = None
        if final_profile.recommended_stage is EscalationStage.ENFORCEMENT_REQUEST:
            request = prepare_enforcement_request(
                final_profile, all_challans, created_at=ctx.as_of, config=ctx.config
            )
            ctx.store.save_enforcement_request(request)
            ctx.log(
                "ENFORCEMENT_REQUEST_PREPARED",
                self.name,
                f"{request.request_id} status={request.status.value} "
                f"(simulation={request.simulation})",
                required_approvals=list(request.required_approvals),
            )
            target = ladder_target
            if target is not None:
                ctx.notifications.send(
                    EscalationStage.ENFORCEMENT_REQUEST,
                    target,
                    config=ctx.config,
                    sent_at=ctx.as_of,
                    requires_human_approval=True,
                )
        ctx.put("enforcement_request", request)

        verdict = (
            f"COMPLIANCE {final_profile.score:.1f}/100 "
            f"({final_profile.tier.value}) | stage "
            f"{final_profile.recommended_stage.value} | notices +{sent_now} | "
            f"enforcement request={'YES' if request else 'NO'}"
        )
        return verdict, {
            "score": final_profile.score,
            "tier": final_profile.tier.value,
            "unpaid_count": final_profile.unpaid_count,
            "outstanding": final_profile.outstanding_amount,
            "oldest_days": final_profile.oldest_unpaid_days,
            "stage": final_profile.recommended_stage.value,
            "notices_sent_now": sent_now,
            "reasons": list(final_profile.reasons),
            "enforcement_request_id": request.request_id if request else None,
        }


class PaymentRecoveryAgent(Agent):
    name = "12. Payment Recovery"
    level = 6
    maturity = AgentMaturity.MOCK

    def execute(self, ctx: AgentContext) -> tuple[str, Mapping[str, Any]]:
        challan: Challan | None = ctx.get("challan")
        history: Sequence[Challan] = ctx.get("history", ())
        open_challans = [
            c
            for c in [*history, challan]
            if c is not None and c.status in OPEN_STATUSES
        ]
        gateway = ctx.payments
        quotes = [gateway.quote(c, ctx.config, as_of=ctx.as_of) for c in open_challans]
        total_due = round(sum(q["total_payable"] for q in quotes), 2)
        instalments = payment_plan(total_due, ctx.config.penalty) if total_due else ()

        paid_ids: list[str] = []
        paid_total = 0.0
        settled: dict[str, Challan] = {}
        if ctx.get("pay_all", False):
            for item in open_challans:
                record, updated = gateway.pay(
                    item, paid_at=ctx.as_of, config=ctx.config, as_of=ctx.as_of
                )
                settled[item.challan_id] = updated
                ctx.store.save_payment(record)
                ctx.store.update_challan_status(
                    updated.challan_id, updated.status.value
                )
                ctx.log(
                    "PAYMENT_RECEIVED",
                    self.name,
                    f"{record.amount:,.0f} via {record.method} ref {record.transaction_ref}",
                )
                paid_ids.append(record.payment_id)
                paid_total += record.amount

            request: EnforcementRequest | None = ctx.get("enforcement_request")
            if request is not None:
                withdrawn = replace(
                    request, status=RequestStatus.WITHDRAWN_ON_PAYMENT
                )
                ctx.store.save_enforcement_request(withdrawn)
                ctx.store.log_event(
                    kind="ENFORCEMENT_REQUEST_WITHDRAWN",
                    actor=self.name,
                    plate=request.plate,
                    detail=(
                        f"{request.request_id} withdrawn automatically on payment; "
                        "no authority action was ever taken."
                    ),
                    at=ctx.as_of,
                )
                ctx.put("enforcement_request", withdrawn)
                target = challan or (open_challans[-1] if open_challans else None)
                if target is not None:
                    ctx.notifications.send(
                        EscalationStage.RESOLVED,
                        target,
                        config=ctx.config,
                        sent_at=ctx.as_of,
                    )

            # Re-score after settlement. The same case that was SEVERE an instant
            # ago is now COMPLIANT; the report prints both numbers, because the
            # movement of that number *is* the product.
            post_challans = [
                settled.get(c.challan_id, c)
                for c in [*history, challan]
                if c is not None
            ]
            post_profile = build_profile(
                plate=ctx.require("plate"),
                challans=post_challans,
                notices_sent=len(ctx.notifications.outbox),
                payment_attempts=len(paid_ids),
                disputes_open=0,
                as_of=ctx.as_of,
                config=ctx.config,
            )
            ctx.put("compliance_after_payment", post_profile)
            ctx.store.save_compliance_snapshot(
                ctx.require("plate"), post_profile, at=ctx.as_of
            )
            ctx.log(
                "CASE_RESOLVED",
                self.name,
                f"compliance {post_profile.score:.1f}/100 "
                f"({post_profile.tier.value}); enforcement request withdrawn",
            )

        after = ctx.get("compliance_after_payment")
        verdict = (
            f"QUOTED {len(quotes)} open challan(s) totalling PKR {total_due:,.0f}"
            + (f" | plan {len(instalments)}x" if instalments else "")
            + (
                f" | PAID {len(paid_ids)} txn(s) PKR {paid_total:,.0f} | "
                f"compliance now {after.score:.1f}/100 ({after.tier.value}) | "
                "enforcement request withdrawn | case RESOLVED"
                if paid_ids and after is not None
                else " | awaiting citizen action"
            )
        )
        return verdict, {
            "open_challans": len(open_challans),
            "total_due": total_due,
            "instalment_plan": list(instalments),
            "payments_made": paid_ids,
            "paid_total": paid_total,
            "settled": bool(paid_ids),
            "compliance_after_payment": (
                f"{after.score:.1f} ({after.tier.value})" if after else None
            ),
            "gateway": "MockPaymentGateway (no real money moved)",
        }


# --------------------------------------------------------------------------- #
AGENTS: tuple[Agent, ...] = (
    DetectionAgent(),
    ANPRAgent(),
    EvidenceVerificationAgent(),
    RiskContextAgent(),
    PredictiveSafetyAgent(),
    FuzzyDecisionAgent(),
    ActionNotificationAgent(),
    ExplainabilityDisputeAgent(),
    AmbulancePriorityAgent(),
    TrafficOptimizationAgent(),
    SmartComplianceAgent(),
    PaymentRecoveryAgent(),
)

AGENT_COUNT = len(AGENTS)
