"""Scenario orchestration: spec in, complete case file out.

The pipeline does no domain reasoning of its own. It loads prior case history,
threads shared state through the twelve agents in order, persists everything,
and returns one immutable :class:`~smartflow.models.PipelineResult`.

Because history is *reconstructed* rather than faked, scenario 4 produces a
genuine 127-day audit trail: the reminder timestamps are computed from the
original issue date, so the case file reads like a real one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .agents import AGENTS, AgentContext
from .config import DEFAULT_POLICY, PolicyConfig
from .db import Store
from .evidence import hash_plate, seal_evidence, tamper_demo
from .fuzzy import level_for_score
from .integrations import (
    MockNADRAVerifier,
    MockPaymentGateway,
    MockVehicleRegistry,
    NotificationGateway,
    get_explanation_writer,
)
from .models import (
    Challan,
    ChallanStatus,
    EvidenceBundle,
    PipelineResult,
    RiskAssessment,
    utcnow,
)
from .scenarios import ScenarioSpec, build_event, synthesise_frames


@dataclass(frozen=True)
class HistoryEntry:
    challan: Challan
    bundle: EvidenceBundle


def build_history(
    spec: ScenarioSpec, as_of: datetime, policy: PolicyConfig
) -> tuple[HistoryEntry, ...]:
    """Reconstruct the vehicle's prior challans and their evidence bundles."""
    entries: list[HistoryEntry] = []
    plate_compact = spec.plate.replace("-", "")
    for index, item in enumerate(spec.history):
        issued_at = as_of - timedelta(days=item.age_days)
        case_id = f"CASE-{plate_compact}-H{index + 1}"
        frames = synthesise_frames(
            item.frames,
            item.witnesses,
            item.violation,
            spec.camera_id,
            issued_at,
        )
        bundle = seal_evidence(case_id, frames, sealed_at=issued_at)
        if item.tamper:
            bundle = tamper_demo(bundle)
        score = policy.severity_for(item.violation)
        entries.append(
            HistoryEntry(
                challan=Challan(
                    challan_id=f"CH-{issued_at:%y%m%d}-{plate_compact}-H{index + 1}",
                    event_id=case_id,
                    plate=spec.plate,
                    violation_type=item.violation,
                    base_fine=policy.fine_for(item.violation),
                    issued_at=issued_at,
                    due_at=issued_at + timedelta(days=policy.penalty.due_days),
                    risk_score=score,
                    risk_level=level_for_score(score),
                    evidence_root_hash=bundle.root_hash,
                    evidence_frame_count=bundle.frame_count,
                    status=ChallanStatus.ISSUED,
                    explanation=(
                        "Historical challan imported for compliance scoring. "
                        + (item.note or "Risk score reconstructed from policy severity.")
                    ),
                    policy_version=policy.version,
                    plate_hash=hash_plate(spec.plate, policy.plate_salt),
                ),
                bundle=bundle,
            )
        )
    return tuple(entries)


def run_scenario(
    spec: ScenarioSpec,
    store: Store | None = None,
    as_of: datetime | None = None,
    use_llm: bool = False,
    policy: PolicyConfig | None = None,
) -> PipelineResult:
    """Execute one scenario end to end and return the finished case file."""
    config = policy or DEFAULT_POLICY
    now = as_of or utcnow()
    own_store = store or Store(":memory:")
    run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
    started_at = now

    registry = MockVehicleRegistry()
    context = AgentContext(
        run_id=run_id,
        scenario=spec.key,
        as_of=now,
        config=config,
        store=own_store,
        registry=registry,
        nadra=MockNADRAVerifier(registry),
        payments=MockPaymentGateway(),
        notifications=NotificationGateway(),
        writer=get_explanation_writer(use_llm),
    )

    event = build_event(spec, now)
    history = build_history(spec, now, config)
    serious_history = sum(
        1 for entry in history if entry.challan.risk_score >= 70.0
    )

    context.state.update(
        {
            "event": event,
            "plate": spec.plate,
            "spec": spec,
            "history": tuple(entry.challan for entry in history),
            "history_serious_count": serious_history,
            "bundles": {entry.challan.challan_id: entry.bundle for entry in history},
            "challan_index": {entry.challan.challan_id: entry.challan for entry in history},
            "notices_sent_prior": spec.notices_sent_prior,
            "payment_attempts": spec.payment_attempts,
            "disputes_open": spec.disputes_open,
            "pay_all": spec.pay_all,
            "ambulance": spec.ambulance,
            "ambulance_plate": spec.ambulance_plate,
            "ambulance_route": spec.ambulance_route,
            "corridor": spec.corridor,
        }
    )

    own_store.start_run(run_id, spec.key, started_at)
    for entry in history:
        own_store.save_challan(entry.challan)
        own_store.log_event(
            kind="LEGACY_CHALLAN_IMPORTED",
            actor="case-migration",
            challan_id=entry.challan.challan_id,
            plate=entry.challan.plate,
            detail=(
                f"{entry.challan.violation_type.value} issued "
                f"{entry.challan.issued_at.date().isoformat()} "
                f"({(now - entry.challan.issued_at).days} days ago)"
            ),
            at=entry.challan.issued_at,
        )

    for agent in AGENTS:
        agent.run(context)

    result = PipelineResult(
        run_id=run_id,
        scenario=spec.key,
        started_at=started_at,
        finished_at=utcnow(),
        decision=context.require("decision"),
        identity=context.require("identity"),
        evidence=context.require("evidence"),
        challan=context.get("challan"),
        notices=tuple(context.notifications.outbox),
        payments=tuple(context.payments.ledger),
        compliance=context.get("compliance_after_payment") or context.get("compliance"),
        enforcement_request=context.get("enforcement_request"),
        optimisation_notes=tuple(
            filter(None, [context.get("optimisation_notes")])
        ),
        traces=tuple(context.traces),
        history=tuple(entry.challan for entry in history),
        compliance_at_escalation=context.get("compliance"),
    )

    own_store.finish_run(
        run_id,
        result.finished_at,
        {
            "scenario": spec.key,
            "score": result.decision.risk.score,
            "level": result.decision.risk.level.value,
            "challan_issued": result.challan.challan_id if result.challan else None,
            "compliance_score": result.compliance.score if result.compliance else None,
            "enforcement_request": (
                result.enforcement_request.request_id
                if result.enforcement_request
                else None
            ),
        },
    )
    own_store.save_traces(result.traces)
    return result


def run_all(
    store: Store | None = None,
    as_of: datetime | None = None,
    use_llm: bool = False,
) -> Sequence[PipelineResult]:
    from .scenarios import all_scenarios

    shared = store or Store(":memory:")
    return [run_scenario(spec, shared, as_of, use_llm) for spec in all_scenarios()]
