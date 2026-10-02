"""Progressive penalty engine.

Old challan, bigger number -- but *explainably* bigger, capped, and with an
early-payment incentive rather than punishment alone. A citizen who pays on
day 3 pays less than the face value; a citizen who ignores the case for 90 days
hits the statutory cap and nothing beyond it. Both facts are printed on the
challan, which is what makes the escalation ladder feel fair instead of
predatory.
"""

from __future__ import annotations

from datetime import datetime

from .config import DEFAULT_POLICY, PenaltyPolicy, PolicyConfig
from .models import PenaltyBreakdown


def days_overdue(issued_at: datetime, as_of: datetime, policy: PenaltyPolicy) -> int:
    """Days past the due date (0 while still inside the payment window)."""
    elapsed = max(0, (as_of - issued_at).days)
    return max(0, elapsed - policy.due_days)


def applicable_tranches(
    overdue_days: int, policy: PenaltyPolicy
) -> tuple[tuple[int, float], ...]:
    """All tranches whose threshold has been crossed.

    Tranches are cumulative, not compounding: each threshold contributes its own
    fraction of the base fine, so the total is predictable from a single table.
    """
    return tuple(t for t in policy.tranches if overdue_days >= t[0])


def compute_penalty(
    base_fine: float,
    issued_at: datetime,
    as_of: datetime,
    policy: PenaltyPolicy | None = None,
    policy_config: PolicyConfig | None = None,
) -> PenaltyBreakdown:
    """Full penalty breakdown for a challan as of ``as_of``."""
    penalty_policy = policy or (policy_config or DEFAULT_POLICY).penalty
    if base_fine < 0:
        raise ValueError("base_fine must be non-negative")

    overdue = days_overdue(issued_at, as_of, penalty_policy)
    tranches = applicable_tranches(overdue, penalty_policy)
    late_fee = round(sum(fraction for _, fraction in tranches) * base_fine, 2)
    subtotal = base_fine + late_fee

    cap = base_fine * penalty_policy.cap_multiplier
    capped = subtotal > cap
    total = round(min(subtotal, cap), 2) if capped else round(subtotal, 2)

    elapsed = max(0, (as_of - issued_at).days)
    discount = 0.0
    if elapsed <= penalty_policy.early_payment_window_days:
        discount = round(base_fine * penalty_policy.early_payment_discount_pct, 2)

    return PenaltyBreakdown(
        base_fine=round(base_fine, 2),
        days_overdue=overdue,
        applied_tranches=tranches,
        late_fee=late_fee,
        subtotal=round(subtotal, 2),
        cap_applied=capped,
        total_payable=total,
        early_payment_discount=discount,
        total_if_paid_today_early=round(total - discount, 2),
        policy_version=penalty_policy.policy_version,
    )


def payment_plan(
    total_payable: float, policy: PenaltyPolicy | None = None
) -> tuple[float, ...]:
    """Split a total into equal instalments (last one absorbs rounding)."""
    plan_policy = policy or DEFAULT_POLICY.penalty
    count = max(1, plan_policy.payment_plan_instalments)
    each = round(total_payable / count, 2)
    instalments = [each] * (count - 1)
    instalments.append(round(total_payable - sum(instalments), 2))
    return tuple(instalments)


def explain_penalty(breakdown: PenaltyBreakdown, currency: str = "PKR") -> list[str]:
    """Line-by-line 'why this number' for the citizen-facing receipt."""
    lines = [
        f"Base fine: {currency} {breakdown.base_fine:,.0f}",
        f"Days past due: {breakdown.days_overdue}",
    ]
    if breakdown.applied_tranches:
        for threshold, fraction in breakdown.applied_tranches:
            lines.append(
                f"  + late fee after day {threshold}: "
                f"{fraction * 100:.0f}% of base = {currency} "
                f"{fraction * breakdown.base_fine:,.0f}"
            )
    else:
        lines.append("  + no late fee: still inside the payment window")
    if breakdown.cap_applied:
        lines.append(
            f"  = capped at {currency} {breakdown.total_payable:,.0f} "
            f"(the statutory ceiling; nothing accrues beyond this)"
        )
    else:
        lines.append(f"Total payable: {currency} {breakdown.total_payable:,.0f}")
    if breakdown.early_payment_discount:
        lines.append(
            f"Early-payment discount available: {currency} "
            f"{breakdown.early_payment_discount:,.0f} -> pay "
            f"{currency} {breakdown.total_if_paid_today_early:,.0f} today"
        )
    return lines
