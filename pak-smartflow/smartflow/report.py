"""Console reporting. Dependency-free, fixed-width, readable on a projector.

Output is built as a list of lines and returned as a string, so the same
renderer can feed the CLI, a test assertion, or a text file for the judge's
packet.
"""

from __future__ import annotations

import textwrap
from datetime import datetime
from typing import Iterable, Sequence

from .config import PolicyConfig
from .db import Store
from .fuzzy import INPUT_LABELS, OUTPUT_TERMS, top_contributors
from .legal import (
    BLOCKED_CAPABILITIES,
    PRIVACY_DEFAULTS,
    SAFE_ALTERNATIVES,
    SIMULATION_BANNER,
)
from .models import (
    AgentMaturity,
    ChallanStatus,
    EscalationStage,
    PipelineResult,
)
from .util import bar, money, money2, truncate

WIDTH = 86


def rule(char: str = "=", width: int = WIDTH) -> str:
    return char * width


def section(title: str) -> list[str]:
    return ["", rule(), f" {title}", rule()]


def kv(label: str, value: object, indent: int = 2, label_width: int = 30) -> str:
    return f"{' ' * indent}{label.ljust(label_width)}{value}"


def wrap(
    text: str,
    indent: int = 2,
    width: int = WIDTH,
    subsequent: int | None = None,
) -> list[str]:
    return textwrap.wrap(
        " ".join(str(text).split()),
        width=width - indent,
        initial_indent=" " * indent,
        subsequent_indent=" " * (indent if subsequent is None else subsequent),
    ) or [" " * indent]


def _maturity_tag(maturity: AgentMaturity) -> str:
    return f"[{maturity.value}]".ljust(12)


def render_agent_trace(result: PipelineResult) -> list[str]:
    lines = section(f"AGENT TRACE  ({len(result.traces)} agents, {result.duration_ms:.1f} ms)")
    for trace in result.traces:
        lines.append(
            f" L{trace.level} {_maturity_tag(trace.maturity)}"
            f"{trace.agent.ljust(28)}{truncate(trace.verdict, 40)}"
        )
    return lines


def render_fuzzy(result: PipelineResult) -> list[str]:
    assessment = result.decision.risk
    lines = section("FUZZY DECISION ENGINE  (why this number)")
    lines.append(kv("Engine", assessment.engine))
    lines.append(kv("Fuzzy score", f"{assessment.score:.2f} / 100   {bar(assessment.score)}"))
    lines.append(
        kv(
            "Defuzzifier",
            "weighted centre-average over fired rules (monotone)",
        )
    )
    if assessment.centroid_cog is not None:
        lines.append(
            kv("Centroid of gravity", f"{assessment.centroid_cog:.2f} (reference only)")
        )
    lines.append(kv("Verdict", assessment.level.value))
    lines.append(kv("Policy-weighted baseline", f"{assessment.weighted_baseline:.2f}"))
    lines.append(kv("Fallback used", assessment.fallback_used))
    lines.append(kv("Review recommended", assessment.review_recommended))
    lines.append("")
    lines.append("  Linguistic inputs (0-100):")
    for name, value in assessment.inputs.items():
        lines.append(
            f"    {INPUT_LABELS.get(name, name).ljust(24)}"
            f"{value:6.1f}  {bar(value, 22)}"
        )
    lines.append("")
    lines.append("  Contribution to firing strength:")
    for name, share in top_contributors(assessment, len(assessment.inputs)):
        lines.append(
            f"    {INPUT_LABELS.get(name, name).ljust(24)}{share:5.1f}%  {bar(share, 22)}"
        )
    lines.append("")
    lines.append(f"  Rules that fired (top {min(5, len(assessment.rule_firings))} of {len(assessment.rule_firings)}):")
    for firing in assessment.rule_firings[:5]:
        conditions = ", ".join(f"{v}={t}" for v, t in firing.conditions.items())
        lines.append(f"    [{firing.strength:.2f}] IF {conditions}")
        lines.append(f"            THEN risk={firing.consequent}   ({firing.label})")
    lines.append("")
    lines.append("  Output term centroids (calibration reference):")
    for name, term in OUTPUT_TERMS.items():
        lines.append(
            f"    {name.ljust(10)}centroid {term.centroid:5.1f}  {bar(term.centroid, 22)}"
        )
    return lines


def render_decision(result: PipelineResult) -> list[str]:
    decision = result.decision
    lines = section("DECISION")
    lines.append(kv("Issue challan", "YES" if decision.issue_challan else "NO"))
    lines.append(kv("Needs human review", decision.needs_human_review))
    lines.append(kv("Actions", ", ".join(a.lower() for a in decision.actions)))
    lines.append(kv("Policy version", decision.policy_version))
    lines.append("")
    lines.append("  Rationale:")
    lines.extend(wrap(decision.rationale, indent=4))
    return lines


def render_evidence(result: PipelineResult) -> list[str]:
    bundle = result.evidence
    lines = section("EVIDENCE  (chain of custody)")
    lines.append(kv("Frame count", bundle.frame_count))
    lines.append(kv("Root hash", bundle.root_hash))
    lines.append(kv("Sealed at", bundle.sealed_at.isoformat()))
    lines.append(kv("Re-verification", "PASSED" if bundle.verified else "FAILED"))
    lines.append("  Per-frame digests:")
    for digest in bundle.frame_digests:
        lines.append(f"    {digest}")
    lines.append("")
    lines.extend(
        wrap(
            "Any single byte changed in any frame breaks the root hash, so a "
            "citizen dispute can be answered with arithmetic instead of opinion.",
            indent=2,
        )
    )
    return lines


def render_challan(result: PipelineResult) -> list[str]:
    lines = section("CHALLAN")
    if result.challan is None:
        lines.append(kv("Issued", "NONE - evidence did not support a penalty"))
        for row in result.history:
            lines.append(
                kv(
                    "Existing case",
                    f"{row.challan_id}  {row.violation_type.value}  "
                    f"{money(row.base_fine)}  {row.status.value}",
                )
            )
        return lines
    challan = result.challan
    lines.append(kv("Challan ID", challan.challan_id))
    lines.append(kv("Plate", f"{challan.plate}  (hash {challan.plate_hash})"))
    lines.append(kv("Owner (masked)", f"{result.identity.owner_name_masked} / {result.identity.cnic_masked}"))
    lines.append(kv("Vehicle", f"{result.identity.vehicle_make} ({result.identity.city})"))
    lines.append(kv("Violation", challan.violation_type.value))
    lines.append(kv("Base fine", money(challan.base_fine)))
    lines.append(kv("Issued", challan.issued_at.date().isoformat()))
    lines.append(kv("Due", challan.due_at.date().isoformat()))
    lines.append(kv("Status", challan.status.value))
    lines.append(kv("Evidence frames", challan.evidence_frame_count))
    lines.append(kv("Evidence root", challan.evidence_root_hash[:32] + "..."))
    lines.append("")
    lines.append("  Explanation served to the citizen:")
    lines.extend(wrap(challan.explanation, indent=4))
    return lines


def render_compliance(result: PipelineResult) -> list[str]:
    lines = section("COMPLIANCE PROFILE")
    profile = result.compliance
    if profile is None:
        lines.append(kv("Profile", "not computed"))
        return lines
    lines.append(rule("-"))
    lines.append(kv("Plate", profile.plate))
    lines.append(kv("Unpaid challans", profile.unpaid_count))
    lines.append(kv("Outstanding (base fines)", money(profile.outstanding_amount)))
    lines.append(kv("Oldest unpaid case", f"{profile.oldest_unpaid_days} days"))
    lines.append(kv("Notices sent", profile.notices_sent))
    lines.append(kv("Payment attempts", profile.payment_attempts))
    lines.append(kv("Open disputes", profile.disputes_open))
    lines.append("")
    lines.append(
        kv("Compliance score", f"{profile.score:.1f} / 100  {bar(profile.score)}")
    )
    lines.append(kv("Tier", profile.tier.value))
    lines.append(kv("Recommended stage", profile.recommended_stage.value))
    lines.append("")
    lines.append("  Score derivation:")
    for reason in profile.reasons:
        lines.append(f"    {reason}")
    before = result.compliance_at_escalation
    if before is not None and abs(before.score - profile.score) > 0.05:
        lines.append("")
        lines.append("  Score movement during this run:")
        lines.append(
            f"    {'at escalation'.ljust(20)}{before.score:6.1f} / 100  "
            f"({before.tier.value})  {bar(before.score)}"
        )
        lines.append(
            f"    {'after settlement'.ljust(20)}{profile.score:6.1f} / 100  "
            f"({profile.tier.value})  {bar(profile.score)}"
        )
        lines.extend(
            wrap(
                "This movement is the product. The system does not just issue a "
                "challan; it drives the case to a closed, paid, compliant state.",
                indent=4,
            )
        )
    lines.append(rule("-"))
    return lines


def render_escalation(result: PipelineResult) -> list[str]:
    lines = section("ESCALATION TIMELINE  (notifications, never enforcement)")
    if not result.notices:
        lines.append(kv("Notices", "none dispatched in this run"))
        return lines
    for notice in sorted(result.notices, key=lambda n: n.sent_at):
        approval = "  [needs human approval]" if notice.requires_human_approval else ""
        lines.append(
            f"  {notice.sent_at.date().isoformat()}  "
            f"{notice.stage.value.ljust(20)}{notice.channel}{approval}"
        )
        lines.append(f"      {truncate(notice.subject, 74)}")
    return lines


def render_enforcement(result: PipelineResult) -> list[str]:
    lines = section("ENFORCEMENT REQUEST  (DRAFT - SIMULATED - NOT EXECUTED)")
    request = result.enforcement_request
    if request is None:
        lines.append(kv("Prepared", "NO - two-key threshold not met"))
        lines.extend(
            wrap(
                "An Enforcement Request needs BOTH enough elapsed time AND a low "
                "compliance score. A reminder is sent instead.",
                indent=2,
            )
        )
        return lines
    lines.append(kv("Request ID", request.request_id))
    lines.append(kv("Status", request.status.value + "  <- inert by construction"))
    lines.append(kv("Challans bundled", len(request.challan_ids)))
    lines.append(kv("Total outstanding", money(request.total_outstanding)))
    lines.append(kv("Compliance score", f"{request.compliance_score:.1f} ({request.compliance_tier.value})"))
    lines.append(kv("Simulation", request.simulation))
    lines.append("")
    lines.append("  Measures requested (for a human officer to decide):")
    for measure in request.requested_measures:
        lines.extend(wrap(f"- {measure}", indent=4))
    lines.append("")
    lines.append("  Required approvals before anything could happen:")
    for approval in request.required_approvals:
        lines.extend(wrap(f"- {approval}", indent=4))
    lines.append("")
    lines.extend(wrap(request.legal_disclaimer, indent=2))
    return lines


def render_payments(result: PipelineResult) -> list[str]:
    lines = section("PAYMENTS")
    if not result.payments:
        lines.append(kv("Transactions", "none in this run"))
        return lines
    total = 0.0
    for payment in result.payments:
        total += payment.amount
        lines.append(
            f"  {payment.paid_at.date().isoformat()}  "
            f"{payment.challan_id.ljust(26)}{money2(payment.amount).rjust(16)}  "
            f"{payment.method}"
        )
    lines.append("")
    lines.append(kv("Total collected (mock)", money2(total)))
    lines.append(kv("Gateway", "MockPaymentGateway - no real money moved"))
    return lines


def render_audit(result: PipelineResult, store: Store) -> list[str]:
    lines = section("CASE AUDIT TRAIL  (append-only)")
    rows: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    challan_ids = [c.challan_id for c in result.history]
    if result.challan is not None:
        challan_ids.append(result.challan.challan_id)
    for challan_id in challan_ids:
        for event in store.audit_trail(challan_id):
            key = (challan_id, event["at"], event["kind"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                f"  {event['at'][:19]}  {event['kind'].ljust(30)}"
                f"{event['actor'].ljust(24)}{truncate(event['detail'] or '', 24)}"
            )
    rows.sort()
    lines.extend(rows if rows else [kv("Events", "none")])
    return lines


def render_history(result: PipelineResult) -> list[str]:
    if not result.history:
        return []
    lines = section(f"PRIOR CASE HISTORY ({len(result.history)} challans)")
    for challan in result.history:
        lines.append(
            f"  {challan.issued_at.date().isoformat()}  "
            f"{challan.challan_id.ljust(26)}{challan.violation_type.value.ljust(16)}"
            f"{money(challan.base_fine).rjust(11)}  {challan.status.value}"
        )
    return lines


def render_legal() -> list[str]:
    lines = section("LEGAL BOUNDARY  (enforced in code, not just on a slide)")
    lines.append("  What this prototype will NOT do -> what it does instead:")
    for capability in BLOCKED_CAPABILITIES:
        lines.append(f"    x {capability}")
        lines.append(f"      -> {SAFE_ALTERNATIVES[capability]}")
    lines.append("")
    lines.append("  Data-protection defaults:")
    for key, value in PRIVACY_DEFAULTS.items():
        lines.append(f"    {key.replace('_', ' ').ljust(28)}{value}")
    lines.append("")
    lines.append(f"  {SIMULATION_BANNER}")
    return lines


def render_scenario_header(result: PipelineResult, subtitle: str, teaching: str, narrative: Sequence[str]) -> list[str]:
    lines = [
        rule(),
        f" PAK-SMARTFLOW  |  SCENARIO: {result.scenario.replace('_', ' ').upper()}",
        rule(),
    ]
    lines.extend(wrap(subtitle, indent=1))
    if narrative:
        lines.append("")
        lines.append(" What this run demonstrates:")
        for point in narrative:
            lines.extend(wrap(f"- {point}", indent=3, subsequent=5))
    if teaching:
        lines.append("")
        lines.extend(wrap(f"Teaching point: {teaching}", indent=2))
    return lines


def render_result(
    result: PipelineResult,
    store: Store,
    policy: PolicyConfig,
    spec: object | None = None,
    show_urdu: bool = False,
) -> str:
    subtitle = getattr(spec, "subtitle", "")
    teaching = getattr(spec, "teaching_point", "")
    narrative = getattr(spec, "narrative", ())

    lines = render_scenario_header(result, subtitle, teaching, narrative)
    lines += render_history(result)
    lines += render_agent_trace(result)
    lines += render_fuzzy(result)
    lines += render_decision(result)
    lines += render_evidence(result)
    lines += render_challan(result)
    lines += render_compliance(result)
    lines += render_escalation(result)
    lines += render_enforcement(result)
    lines += render_payments(result)
    lines += render_audit(result, store)

    if show_urdu and result.notices:
        lines += section("CITIZEN NOTICE  (Urdu script)")
        for notice in result.notices[-1:]:
            lines.append(f"  {notice.subject}")
            lines.append("")
            lines.extend(f"  {line}" for line in notice.body_urdu.splitlines())
        lines += section("CITIZEN NOTICE  (Roman Urdu)")
        for notice in result.notices[-1:]:
            lines.extend(wrap(notice.body_roman_urdu, indent=2))

    lines += render_legal()
    lines += ["", rule(), ""]
    return "\n".join(lines)


def render_summary(results: Iterable[PipelineResult]) -> str:
    lines = section("RUN SUMMARY")
    lines.append(
        f"  {'SCENARIO'.ljust(24)}{'SCORE'.rjust(7)}{'LEVEL'.rjust(11)}"
        f"{'CHALLAN'.rjust(10)}{'COMPLIANCE'.rjust(12)}{'STAGE'.rjust(22)}"
    )
    lines.append("  " + rule("-", WIDTH - 2))
    for result in results:
        compliance = result.compliance
        lines.append(
            f"  {result.scenario.ljust(24)}"
            f"{result.decision.risk.score:7.1f}"
            f"{result.decision.risk.level.value.rjust(11)}"
            f"{('yes' if result.challan else 'no').rjust(10)}"
            f"{(f'{compliance.score:.0f}' if compliance else '-').rjust(12)}"
            f"{(compliance.recommended_stage.value if compliance else '-').rjust(22)}"
        )
    return "\n".join(lines)


def render_db_stats(store: Store) -> str:
    stats = store.stats()
    lines = section("DATABASE")
    for key in (
        "challans",
        "events",
        "payments",
        "enforcement_requests",
        "agent_traces",
    ):
        lines.append(kv(key.replace("_", " ").title(), stats[key]))
    lines.append(kv("Outstanding (base)", money(stats["outstanding_amount"])))
    lines.append("")
    lines.append("  Challans by status:")
    for status, count in sorted(stats["by_status"].items()):
        lines.append(f"    {status.ljust(16)}{count}")
    return "\n".join(lines)
