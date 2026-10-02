"""Compliance scoring and the escalation ladder.

The two behaviours that matter most for the project's credibility are tested
here directly: proportionality (no single factor can dominate) and the two-key
rule (time AND severity, never one alone).
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from smartflow.compliance import (
    build_profile,
    notices_for_stage,
    prepare_enforcement_request,
    recommended_stage,
    score_case,
)
from smartflow.config import DEFAULT_POLICY
from smartflow.models import (
    Challan,
    ChallanStatus,
    ComplianceTier,
    EscalationStage,
    RequestStatus,
    RiskLevel,
    ViolationType,
)

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)
POLICY = DEFAULT_POLICY
ESCALATION = POLICY.escalation


def make_challan(
    index: int = 1,
    age_days: int = 10,
    fine: float = 1000.0,
    status: ChallanStatus = ChallanStatus.ISSUED,
    plate: str = "LEB-1234",
) -> Challan:
    issued = NOW - timedelta(days=age_days)
    return Challan(
        challan_id=f"CH-TEST-{index:03d}",
        event_id=f"EVT-{index}",
        plate=plate,
        violation_type=ViolationType.RED_LIGHT,
        base_fine=fine,
        issued_at=issued,
        due_at=issued + timedelta(days=POLICY.penalty.due_days),
        risk_score=88.0,
        risk_level=RiskLevel.HIGH,
        evidence_root_hash=f"root-{index}",
        evidence_frame_count=4,
        status=status,
        explanation="test fixture",
        policy_version=POLICY.version,
        plate_hash=f"hash-{index}",
    )


class ComplianceScoreTests(unittest.TestCase):
    def test_clean_record_scores_full_marks(self) -> None:
        score, reasons = score_case([], as_of=NOW, config=POLICY)
        self.assertEqual(score, 100.0)
        self.assertEqual(reasons, ("No adverse history on record",))

    def test_score_decreases_with_unpaid_cases(self) -> None:
        few = score_case([make_challan(1)], as_of=NOW, config=POLICY)[0]
        many = score_case([make_challan(i) for i in range(1, 6)], as_of=NOW, config=POLICY)[0]
        self.assertGreater(few, many)

    def test_paid_challans_do_not_count_against_the_citizen(self) -> None:
        paid = [make_challan(i, status=ChallanStatus.PAID) for i in range(1, 6)]
        self.assertEqual(score_case(paid, as_of=NOW, config=POLICY)[0], 100.0)

    def test_proportionality_caps_the_unpaid_component(self) -> None:
        """Fifty unpaid challans must not score fifty times worse than ten."""
        ten = score_case([make_challan(i) for i in range(10)], as_of=NOW, config=POLICY)[0]
        fifty = score_case([make_challan(i) for i in range(50)], as_of=NOW, config=POLICY)[0]
        self.assertGreaterEqual(fifty, 0.0)
        self.assertLessEqual(ten - fifty, POLICY.compliance.max_unpaid_component)

    def test_score_is_bounded(self) -> None:
        worst = score_case(
            [make_challan(i, age_days=400, fine=50_000.0) for i in range(60)],
            notices_sent=50,
            disputes_open=10,
            as_of=NOW,
            config=POLICY,
        )[0]
        self.assertGreaterEqual(worst, 0.0)
        self.assertLessEqual(worst, 100.0)

    def test_payment_attempts_earn_credit(self) -> None:
        without = score_case([make_challan(1, age_days=100)], as_of=NOW, config=POLICY)[0]
        with_attempts = score_case(
            [make_challan(1, age_days=100)],
            payment_attempts=2,
            as_of=NOW,
            config=POLICY,
        )[0]
        self.assertGreater(with_attempts, without)

    def test_notices_stop_counting_once_everything_is_settled(self) -> None:
        """A citizen who has paid is not still 'ignoring notices'."""
        open_case = [make_challan(1, age_days=100)]
        settled = [make_challan(1, age_days=100, status=ChallanStatus.PAID)]
        open_score = score_case(open_case, notices_sent=5, as_of=NOW, config=POLICY)[0]
        settled_score = score_case(settled, notices_sent=5, as_of=NOW, config=POLICY)[0]
        self.assertEqual(settled_score, 100.0)
        self.assertLess(open_score, settled_score)

    def test_reasons_are_reported_for_every_deduction(self) -> None:
        _, reasons = score_case(
            [make_challan(1, age_days=120)],
            notices_sent=3,
            disputes_open=1,
            as_of=NOW,
            config=POLICY,
        )
        self.assertTrue(any("Unpaid challans" in r for r in reasons))
        self.assertTrue(any("Outstanding amount" in r for r in reasons))
        self.assertTrue(any("Oldest unpaid case" in r for r in reasons))
        self.assertTrue(any("Notices ignored" in r for r in reasons))
        self.assertTrue(any("Open disputes" in r for r in reasons))


class TwoKeyRuleTests(unittest.TestCase):
    def test_time_alone_is_not_enough(self) -> None:
        """A 100-day-old single challan is old but the citizen is otherwise fine."""
        stage = recommended_stage(100, 80.7, ESCALATION)
        self.assertIsNot(stage, EscalationStage.ENFORCEMENT_REQUEST)
        self.assertIs(stage, EscalationStage.FINAL_NOTICE)

    def test_bad_score_alone_is_not_enough(self) -> None:
        stage = recommended_stage(10, 5.0, ESCALATION)
        self.assertIsNot(stage, EscalationStage.ENFORCEMENT_REQUEST)
        self.assertIs(stage, EscalationStage.REMINDER_1)

    def test_both_conditions_together_unlock_enforcement(self) -> None:
        stage = recommended_stage(100, 12.0, ESCALATION)
        self.assertIs(stage, EscalationStage.ENFORCEMENT_REQUEST)

    def test_ladder_climbs_with_time(self) -> None:
        expected = {
            0: EscalationStage.ISSUED,
            8: EscalationStage.REMINDER_1,
            16: EscalationStage.REMINDER_2,
            26: EscalationStage.FINAL_NOTICE,
        }
        for days, stage in expected.items():
            self.assertIs(recommended_stage(days, 90.0, ESCALATION), stage, days)

    def test_manual_stages_are_never_selected_automatically(self) -> None:
        stage = recommended_stage(3650, 0.0, ESCALATION)
        self.assertNotIn(
            stage, (EscalationStage.AUTHORITY_REVIEW, EscalationStage.RESOLVED)
        )


class EnforcementRequestTests(unittest.TestCase):
    def _severe_profile(self):
        challans = [make_challan(i, age_days=127 - i * 8) for i in range(1, 9)]
        return build_profile("LEW-1234", challans, as_of=NOW, config=POLICY), challans

    def test_severe_profile_is_classified_severe(self) -> None:
        profile, _ = self._severe_profile()
        self.assertIs(profile.tier, ComplianceTier.SEVERE)
        self.assertIs(profile.recommended_stage, EscalationStage.ENFORCEMENT_REQUEST)

    def test_request_is_inert(self) -> None:
        profile, challans = self._severe_profile()
        request = prepare_enforcement_request(profile, challans, created_at=NOW)
        self.assertTrue(request.simulation)
        self.assertIs(request.status, RequestStatus.PENDING_AUTHORITY_APPROVAL)
        self.assertIn("no legal force", request.legal_disclaimer)
        request.assert_not_executable()

    def test_request_demands_human_approvals(self) -> None:
        profile, challans = self._severe_profile()
        request = prepare_enforcement_request(profile, challans, created_at=NOW)
        self.assertGreaterEqual(len(request.required_approvals), 3)
        self.assertTrue(all(isinstance(a, str) and a for a in request.required_approvals))

    def test_request_cannot_be_built_for_an_ineligible_profile(self) -> None:
        profile = build_profile(
            "LEB-1234", [make_challan(1, age_days=5)], as_of=NOW, config=POLICY
        )
        with self.assertRaises(ValueError):
            prepare_enforcement_request(profile, [make_challan(1, age_days=5)])

    def test_an_approved_request_is_rejected_by_the_guard(self) -> None:
        profile, challans = self._severe_profile()
        request = prepare_enforcement_request(profile, challans, created_at=NOW)
        executable = replace(request, status=RequestStatus.APPROVED_BY_AUTHORITY)
        with self.assertRaises(AssertionError):
            executable.assert_not_executable()

    def test_request_lists_evidence_roots(self) -> None:
        profile, challans = self._severe_profile()
        request = prepare_enforcement_request(profile, challans, created_at=NOW)
        self.assertEqual(len(request.evidence_roots), profile.unpaid_count)


class NoticeLadderTests(unittest.TestCase):
    def test_no_reminders_for_a_fresh_case(self) -> None:
        profile = build_profile("LEB-1234", [make_challan(1, 1)], as_of=NOW, config=POLICY)
        self.assertEqual(notices_for_stage(profile, ESCALATION), ())

    def test_reminders_appear_over_time(self) -> None:
        profile = build_profile(
            "LEB-1234", [make_challan(1, age_days=8)], as_of=NOW, config=POLICY
        )
        self.assertEqual(notices_for_stage(profile, ESCALATION), (EscalationStage.REMINDER_1,))

    def test_issuance_is_not_replayed_as_a_reminder(self) -> None:
        profile = build_profile(
            "LEB-1234", [make_challan(1, age_days=400)], as_of=NOW, config=POLICY
        )
        self.assertNotIn(EscalationStage.ISSUED, notices_for_stage(profile, ESCALATION))

    def test_enforcement_is_not_dispatched_as_a_plain_reminder(self) -> None:
        profile = build_profile(
            "LEB-1234",
            [make_challan(i, age_days=200) for i in range(1, 4)],
            as_of=NOW,
            config=POLICY,
        )
        self.assertNotIn(
            EscalationStage.ENFORCEMENT_REQUEST, notices_for_stage(profile, ESCALATION)
        )


class ProfileTests(unittest.TestCase):
    def test_profile_reports_history_facts(self) -> None:
        challans = [make_challan(i, age_days=50 + i) for i in range(1, 4)]
        profile = build_profile(
            "LEB-1234", challans, notices_sent=3, payment_attempts=1, as_of=NOW, config=POLICY
        )
        self.assertEqual(profile.unpaid_count, 3)
        self.assertEqual(profile.oldest_unpaid_days, 53)
        self.assertEqual(profile.notices_sent, 3)
        self.assertEqual(profile.plate, "LEB-1234")
        self.assertEqual(len(profile.challan_ids), 3)

    def test_profile_is_empty_for_an_unknown_plate(self) -> None:
        profile = build_profile("XXX-0000", [], as_of=NOW, config=POLICY)
        self.assertEqual(profile.unpaid_count, 0)
        self.assertEqual(profile.outstanding_amount, 0.0)
        self.assertIs(profile.tier, ComplianceTier.COMPLIANT)


if __name__ == "__main__":
    unittest.main()
