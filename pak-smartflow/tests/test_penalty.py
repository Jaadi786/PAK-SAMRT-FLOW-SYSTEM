"""Progressive penalty engine tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from smartflow.config import DEFAULT_POLICY, PenaltyPolicy
from smartflow.penalty import (
    applicable_tranches,
    compute_penalty,
    days_overdue,
    explain_penalty,
    payment_plan,
)

ISSUED = datetime(2026, 1, 1, tzinfo=timezone.utc)
POLICY = DEFAULT_POLICY.penalty


def at(days_after_issue: int) -> datetime:
    return ISSUED + timedelta(days=days_after_issue)


class OverdueWindowTests(unittest.TestCase):
    def test_inside_the_window_is_not_overdue(self) -> None:
        self.assertEqual(days_overdue(ISSUED, at(0), POLICY), 0)
        self.assertEqual(days_overdue(ISSUED, at(29), POLICY), 0)

    def test_due_date_itself_is_not_overdue(self) -> None:
        self.assertEqual(days_overdue(ISSUED, at(POLICY.due_days), POLICY), 0)

    def test_one_day_late_is_one_day_overdue(self) -> None:
        self.assertEqual(days_overdue(ISSUED, at(POLICY.due_days + 1), POLICY), 1)

    def test_paying_before_issuance_cannot_be_negative(self) -> None:
        self.assertEqual(days_overdue(ISSUED, at(-5), POLICY), 0)


class TrancheTests(unittest.TestCase):
    def test_no_tranche_inside_the_window(self) -> None:
        self.assertEqual(applicable_tranches(0, POLICY), ())

    def test_tranches_are_cumulative_not_compounding(self) -> None:
        self.assertEqual(applicable_tranches(30, POLICY), ((30, 0.10),))
        self.assertEqual(applicable_tranches(60, POLICY), ((30, 0.10), (60, 0.25)))
        self.assertEqual(
            applicable_tranches(90, POLICY),
            ((30, 0.10), (60, 0.25), (90, 0.50)),
        )

    def test_total_late_fraction_after_ninety_days(self) -> None:
        breakdown = compute_penalty(1000.0, ISSUED, at(POLICY.due_days + 95), POLICY)
        self.assertAlmostEqual(breakdown.late_fee, 850.0)


class BreakdownTests(unittest.TestCase):
    def test_no_late_fee_on_time(self) -> None:
        breakdown = compute_penalty(1000.0, ISSUED, at(10), POLICY)
        self.assertEqual(breakdown.late_fee, 0.0)
        self.assertEqual(breakdown.total_payable, 1000.0)
        self.assertFalse(breakdown.cap_applied)

    def test_late_fee_applies_after_thirty_days_overdue(self) -> None:
        breakdown = compute_penalty(1000.0, ISSUED, at(POLICY.due_days + 31), POLICY)
        self.assertAlmostEqual(breakdown.late_fee, 100.0)
        self.assertAlmostEqual(breakdown.total_payable, 1100.0)

    def test_cap_actually_binds_at_the_final_tranche(self) -> None:
        """Regression: with a 2.0x ceiling and tranches summing to 0.85, the cap
        could never be reached and the 'capped' line on the citizen receipt was
        dead code. The policy ceiling must be below 1 + sum(tranches)."""
        self.assertLess(
            POLICY.cap_multiplier, 1.0 + sum(f for _, f in POLICY.tranches)
        )
        breakdown = compute_penalty(1000.0, ISSUED, at(1000), POLICY)
        self.assertTrue(breakdown.cap_applied)
        self.assertAlmostEqual(breakdown.total_payable, 1750.0)
        self.assertLess(breakdown.total_payable, breakdown.subtotal)

    def test_uncapped_cases_report_no_cap(self) -> None:
        breakdown = compute_penalty(1000.0, ISSUED, at(POLICY.due_days + 31), POLICY)
        self.assertFalse(breakdown.cap_applied)

    def test_penalty_is_monotone_in_time(self) -> None:
        totals = [
            compute_penalty(1000.0, ISSUED, at(days), POLICY).total_payable
            for days in range(0, 400, 5)
        ]
        self.assertEqual(totals, sorted(totals))

    def test_early_payment_discount_only_inside_the_window(self) -> None:
        early = compute_penalty(1000.0, ISSUED, at(3), POLICY)
        late = compute_penalty(1000.0, ISSUED, at(10), POLICY)
        self.assertAlmostEqual(early.early_payment_discount, 100.0)
        self.assertAlmostEqual(late.early_payment_discount, 0.0)
        self.assertLess(early.total_if_paid_today_early, early.total_payable)

    def test_breakdown_totals_are_consistent(self) -> None:
        breakdown = compute_penalty(1200.0, ISSUED, at(120), POLICY)
        self.assertAlmostEqual(
            breakdown.subtotal, breakdown.base_fine + breakdown.late_fee, places=2
        )

    def test_negative_fine_rejected(self) -> None:
        with self.assertRaises(ValueError):
            compute_penalty(-1.0, ISSUED, at(10), POLICY)

    def test_custom_policy_changes_the_outcome(self) -> None:
        aggressive = PenaltyPolicy(
            due_days=7, tranches=((7, 1.0),), cap_multiplier=5.0
        )
        breakdown = compute_penalty(1000.0, ISSUED, at(20), aggressive)
        self.assertAlmostEqual(breakdown.total_payable, 2000.0)

    def test_explanation_lines_are_generated(self) -> None:
        lines = explain_penalty(compute_penalty(1000.0, ISSUED, at(120), POLICY))
        joined = "\n".join(lines)
        self.assertIn("Base fine", joined)
        self.assertIn("late fee", joined)
        self.assertIn("capped", joined)


class PaymentPlanTests(unittest.TestCase):
    def test_plan_sums_to_the_total(self) -> None:
        total = 1000.0
        plan = payment_plan(total, POLICY)
        self.assertEqual(len(plan), POLICY.payment_plan_instalments)
        self.assertAlmostEqual(sum(plan), total, places=2)

    def test_plan_absorbs_rounding_in_the_last_instalment(self) -> None:
        plan = payment_plan(100.0, POLICY)
        self.assertAlmostEqual(sum(plan), 100.0, places=2)

    def test_zero_total_is_handled(self) -> None:
        self.assertAlmostEqual(sum(payment_plan(0.0, POLICY)), 0.0)


if __name__ == "__main__":
    unittest.main()
