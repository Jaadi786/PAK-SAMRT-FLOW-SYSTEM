"""Compliance scoring and the escalation ladder.

This is the module that makes Pak-SmartFlow different from a challan printer.
It answers the question every existing system ignores: *challan banane ke baad
kya hota hai?*

Two guarantees are enforced here:

1. **Proportionality.** Score deductions are capped per factor, so no single
   history item can push a citizen into the enforcement tier alone.
2. **Two-key escalation.** Time elapsed *and* a low compliance score are both
   required before an Enforcement Request may be prepared. Either one alone
   produces only a reminder.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Sequence

from .config import DEFAULT_POLICY, EscalationPolicy, PolicyConfig
from .legal import enforcement_request_disclaimer
from .models import (
    Challan,
    ChallanStatus,
    ComplianceProfile,
    ComplianceTier,
    EnforcementRequest,
    EscalationStage,
    RequestStatus,
    utcnow,
)

#: Statuses that still count against a citizen.
OPEN_STATUSES = (
    ChallanStatus.ISSUED,
    ChallanStatus.OVERDUE,
    ChallanStatus.ESCALATED,
    ChallanStatus.PARTIALLY_PAID,
)


def _tier_for(score: float, config: PolicyConfig) -> ComplianceTier:
    for threshold, name in config.compliance.tiers:
        if score >= threshold:
            return ComplianceTier(name)
    return ComplianceTier.SEVERE


def score_case(
    challans: Sequence[Challan],
    notices_sent: int = 0,
    payment_attempts: int = 0,
    disputes_open: int = 0,
    as_of: datetime | None = None,
    config: PolicyConfig | None = None,
) -> tuple[float, tuple[str, ...]]:
    """Return ``(compliance_score, reasons)`` where 100 is fully compliant."""
    policy = config or DEFAULT_POLICY
    weights = policy.compliance
    now = as_of or utcnow()

    open_challans = [c for c in challans if c.status in OPEN_STATUSES]
    unpaid_count = len(open_challans)
    outstanding = sum(c.base_fine for c in open_challans)
    oldest_days = 0
    if open_challans:
        oldest = min(c.issued_at for c in open_challans)
        oldest_days = max(0, (now - oldest).days)

    reasons: list[str] = []
    unpaid_component = min(
        weights.max_unpaid_component, unpaid_count * weights.per_unpaid_challan
    )
    outstanding_component = min(
        weights.max_outstanding_component,
        (outstanding / 1000.0) * weights.outstanding_per_1000_pkr,
    )
    age_component = min(
        weights.max_age_component,
        (oldest_days / weights.age_scale_days) * weights.max_age_component,
    )
    # Notices and disputes describe a *pattern of ignoring an open case*. Once
    # every case is settled there is nothing left to ignore, so neither should
    # keep dragging the score down after payment.
    has_open_case = unpaid_count > 0
    notice_component = (
        min(weights.max_notice_component, notices_sent * weights.per_notice)
        if has_open_case
        else 0.0
    )
    dispute_component = (
        min(weights.max_dispute_component, disputes_open * weights.per_open_dispute)
        if has_open_case
        else 0.0
    )
    payment_credit = min(
        weights.max_payment_credit, payment_attempts * weights.per_payment_attempt_credit
    )

    deductions = (
        ("Unpaid challans", unpaid_count, unpaid_component, weights.max_unpaid_component),
        (
            "Outstanding amount",
            f"{outstanding:,.0f} PKR",
            outstanding_component,
            weights.max_outstanding_component,
        ),
        ("Oldest unpaid case", f"{oldest_days} days", age_component, weights.max_age_component),
        ("Notices ignored", notices_sent, notice_component, weights.max_notice_component),
        ("Open disputes", disputes_open, dispute_component, weights.max_dispute_component),
    )
    for name, value, applied, cap in deductions:
        if applied > 0:
            reasons.append(f"-{applied:.1f} {name} ({value}, cap {cap:.0f})")
    if payment_credit > 0:
        reasons.append(f"+{payment_credit:.1f} credit for {payment_attempts} payment attempt(s)")

    raw = 100.0 - sum(item[2] for item in deductions) + payment_credit
    score = round(max(0.0, min(100.0, raw)), 1)
    if not reasons:
        reasons.append("No adverse history on record")
    return score, tuple(reasons)


def build_profile(
    plate: str,
    challans: Sequence[Challan],
    notices_sent: int = 0,
    payment_attempts: int = 0,
    disputes_open: int = 0,
    as_of: datetime | None = None,
    config: PolicyConfig | None = None,
) -> ComplianceProfile:
    policy = config or DEFAULT_POLICY
    now = as_of or utcnow()
    open_challans = [c for c in challans if c.status in OPEN_STATUSES]
    outstanding = sum(c.base_fine for c in open_challans)
    oldest_days = 0
    if open_challans:
        oldest_days = max(0, (now - min(c.issued_at for c in open_challans)).days)

    score, reasons = score_case(
        challans,
        notices_sent=notices_sent,
        payment_attempts=payment_attempts,
        disputes_open=disputes_open,
        as_of=now,
        config=policy,
    )
    tier = _tier_for(score, policy)
    stage = recommended_stage(oldest_days, score, policy.escalation)
    return ComplianceProfile(
        plate=plate,
        unpaid_count=len(open_challans),
        outstanding_amount=round(outstanding, 2),
        oldest_unpaid_days=oldest_days,
        notices_sent=notices_sent,
        payment_attempts=payment_attempts,
        disputes_open=disputes_open,
        challan_ids=tuple(c.challan_id for c in open_challans),
        score=score,
        tier=tier,
        reasons=reasons,
        recommended_stage=stage,
        policy_version=policy.escalation.policy_version,
    )


def recommended_stage(
    oldest_days: int,
    compliance_score: float,
    policy: EscalationPolicy,
) -> EscalationStage:
    """Highest ladder rung currently justified.

    Enforcement rungs need both elapsed time and a genuinely poor score;
    otherwise the ladder stops at the last notification rung.
    """
    eligible = EscalationStage.ISSUED
    for item in policy.stages:
        if not item.auto or item.after_days <= 0:
            continue
        if oldest_days < item.after_days:
            continue
        if item.stage is EscalationStage.ENFORCEMENT_REQUEST:
            if compliance_score > policy.max_compliance_score_for_enforcement:
                continue
        eligible = item.stage
    return eligible


def prepare_enforcement_request(
    profile: ComplianceProfile,
    challans: Sequence[Challan],
    created_at: datetime | None = None,
    config: PolicyConfig | None = None,
) -> EnforcementRequest:
    """Assemble a *draft* packet. This function cannot execute anything.

    The returned object is deliberately inert: status is
    ``PENDING_AUTHORITY_APPROVAL``, ``simulation`` is True, and the dataclass
    exposes ``assert_not_executable`` so the property is testable.
    """
    policy = config or DEFAULT_POLICY
    escalation = policy.escalation
    if profile.recommended_stage is not EscalationStage.ENFORCEMENT_REQUEST:
        raise ValueError(
            "Compliance profile does not meet the two-key threshold "
            f"(stage={profile.recommended_stage.value}, score={profile.score}, "
            f"oldest={profile.oldest_unpaid_days}d). Send a reminder instead."
        )

    open_challans = [c for c in challans if c.status in OPEN_STATUSES]
    measures = (
        "Review the attached evidence bundles and compliance history",
        "Confirm the applicable penalty schedule against current law",
        "Give the citizen one final opportunity to pay or dispute",
        "Decide: withdraw, extend, or refer under the authority's own procedure",
    )
    request = EnforcementRequest(
        request_id=f"ER-{profile.plate.replace('-', '')[:6]}-{created_at or utcnow():%Y%m%d}",
        plate=profile.plate,
        challan_ids=tuple(c.challan_id for c in open_challans),
        total_outstanding=profile.outstanding_amount,
        compliance_score=profile.score,
        compliance_tier=profile.tier,
        created_at=created_at or utcnow(),
        status=RequestStatus.PENDING_AUTHORITY_APPROVAL,
        evidence_roots=tuple(c.evidence_root_hash for c in open_challans),
        requested_measures=measures,
        required_approvals=(
            f"Traffic Enforcement Officer (named) -- review window "
            f"{escalation.cooling_off_days} days",
            "Sector Commander -- assess proportionality",
            "Legal/Compliance desk -- confirm statute and schedule",
        ),
        legal_disclaimer=enforcement_request_disclaimer(),
        simulation=True,
    )
    request.assert_not_executable()
    return request


def notices_for_stage(
    profile: ComplianceProfile, policy: EscalationPolicy
) -> tuple[EscalationStage, ...]:
    """Which *reminder* rungs a citizen should have received by now.

    ISSUED is excluded: issuance is an event, not a reminder, and the case file
    already records it. Re-sending it would fabricate a second issuance.
    """
    stages = []
    for item in policy.stages:
        if not item.auto or item.stage in (
            EscalationStage.ISSUED,
            EscalationStage.ENFORCEMENT_REQUEST,
            EscalationStage.AUTHORITY_REVIEW,
            EscalationStage.RESOLVED,
        ):
            continue
        if item.after_days <= profile.oldest_unpaid_days:
            stages.append(item.stage)
    return tuple(stages)
