"""End-to-end scenario tests: the demo must tell the story it claims to tell."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from smartflow.db import Store
from smartflow.models import (
    ChallanStatus,
    ComplianceTier,
    EscalationStage,
    RequestStatus,
    RiskLevel,
)
from smartflow.pipeline import run_all, run_scenario
from smartflow.scenarios import SCENARIOS, get_scenario

AS_OF = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


class ScenarioCatalogueTests(unittest.TestCase):
    def test_five_scenarios(self) -> None:
        self.assertEqual(len(SCENARIOS), 5)

    def test_keys_and_numbers_are_unique(self) -> None:
        self.assertEqual(len({s.key for s in SCENARIOS}), 5)
        self.assertEqual(len({s.number for s in SCENARIOS}), 5)

    def test_selector_accepts_number_key_and_fragment(self) -> None:
        self.assertEqual(get_scenario("4").key, "unpaid_escalation")
        self.assertEqual(get_scenario("unpaid_escalation").number, 4)
        self.assertEqual(get_scenario("ambulance").number, 3)

    def test_unknown_selector_raises(self) -> None:
        with self.assertRaises(KeyError):
            get_scenario("does-not-exist")

    def test_every_scenario_documents_itself(self) -> None:
        for spec in SCENARIOS:
            self.assertTrue(spec.subtitle, spec.key)
            self.assertTrue(spec.narrative, spec.key)
            self.assertTrue(spec.teaching_point, spec.key)


class PerScenarioOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = Store(":memory:")
        cls.results = {r.scenario: r for r in run_all(cls.store, as_of=AS_OF)}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.store.close()

    def test_all_five_ran(self) -> None:
        self.assertEqual(len(self.results), 5)

    def test_scenario_1_ordinary_violation(self) -> None:
        result = self.results["red_light"]
        self.assertIs(result.decision.risk.level, RiskLevel.HIGH)
        self.assertTrue(result.decision.issue_challan)
        self.assertIsNotNone(result.challan)
        self.assertIn("CHALLAN", result.decision.actions)

    def test_scenario_2_safety_overlay_promotes_to_critical(self) -> None:
        result = self.results["collision_risk"]
        self.assertIs(result.decision.risk.level, RiskLevel.CRITICAL)
        self.assertIn("Safety Overlay", result.decision.rationale)
        self.assertIn("IMMEDIATE_SAFETY_ALERT", result.decision.actions)
        self.assertTrue(result.decision.needs_human_review)

    def test_scenario_2_is_more_severe_than_scenario_1(self) -> None:
        self.assertGreater(
            self.results["collision_risk"].decision.risk.score,
            self.results["red_light"].decision.risk.score,
        )

    def test_scenario_3_emergency_corridor(self) -> None:
        result = self.results["ambulance"]
        self.assertIs(result.decision.risk.level, RiskLevel.MEDIUM)
        self.assertTrue(result.challan)
        ambulance_trace = next(
            t for t in result.traces if "Ambulance" in t.agent
        )
        self.assertIn("CORRIDOR PLAN", ambulance_trace.verdict)
        self.assertIn("ambulance_plate", ambulance_trace.details)

    def test_scenario_3_issues_a_proportionate_not_maximum_response(self) -> None:
        """Blocking a hospital corridor is serious, but the engine does not
        pretend it is a near-fatal offence. Proportionality is the point."""
        self.assertIsNot(self.results["ambulance"].decision.risk.level, RiskLevel.CRITICAL)

    def test_scenario_4_full_recovery_arc(self) -> None:
        result = self.results["unpaid_escalation"]

        # Reached the enforcement rung...
        self.assertIsNotNone(result.enforcement_request)
        request = result.enforcement_request
        assert request is not None
        self.assertIs(request.status, RequestStatus.WITHDRAWN_ON_PAYMENT)
        self.assertTrue(request.simulation)

        # ...because the profile really was severe at that point.
        assert result.compliance_at_escalation is not None
        self.assertIs(result.compliance_at_escalation.tier, ComplianceTier.SEVERE)
        self.assertLess(result.compliance_at_escalation.score, 40.0)

        # ...and then the citizen paid and the case closed clean.
        assert result.compliance is not None
        self.assertIs(result.compliance.tier, ComplianceTier.COMPLIANT)
        self.assertEqual(result.compliance.unpaid_count, 0)
        self.assertEqual(result.compliance.score, 100.0)
        self.assertEqual(len(result.payments), 9)

    def test_scenario_4_prepared_an_enforcement_request_but_never_executed_it(self) -> None:
        result = self.results["unpaid_escalation"]
        assert result.enforcement_request is not None
        result.enforcement_request.assert_not_executable()
        self.assertNotIn(
            "AUTHORITY_REVIEW", [n.stage.value for n in result.notices]
        )

    def test_scenario_4_backfills_the_escalation_ladder(self) -> None:
        result = self.results["unpaid_escalation"]
        stages = {notice.stage for notice in result.notices}
        self.assertIn(EscalationStage.REMINDER_1, stages)
        self.assertIn(EscalationStage.REMINDER_2, stages)
        self.assertIn(EscalationStage.FINAL_NOTICE, stages)
        self.assertIn(EscalationStage.ENFORCEMENT_REQUEST, stages)
        self.assertIn(EscalationStage.RESOLVED, stages)

    def test_scenario_4_reminders_arrive_in_chronological_order(self) -> None:
        result = self.results["unpaid_escalation"]
        ladder = [
            n for n in result.notices
            if n.stage in (
                EscalationStage.REMINDER_1,
                EscalationStage.REMINDER_2,
                EscalationStage.FINAL_NOTICE,
            )
        ]
        ladder.sort(key=lambda n: n.sent_at)
        self.assertEqual(
            [n.stage for n in ladder],
            [
                EscalationStage.REMINDER_1,
                EscalationStage.REMINDER_2,
                EscalationStage.FINAL_NOTICE,
            ],
        )

    def test_scenario_4_reminders_reference_the_oldest_case(self) -> None:
        result = self.results["unpaid_escalation"]
        oldest = min(result.history, key=lambda c: c.issued_at)
        reminder = next(
            n for n in result.notices if n.stage is EscalationStage.REMINDER_1
        )
        self.assertIn(oldest.challan_id, reminder.subject)

    def test_scenario_5_evidence_gate_blocks_the_challan(self) -> None:
        result = self.results["false_positive_appeal"]
        self.assertIsNone(result.challan)
        self.assertFalse(result.decision.issue_challan)
        self.assertIn("EVIDENCE_REVIEW", result.decision.actions)
        self.assertIn("Evidence Gate", result.decision.rationale)
        self.assertTrue(result.decision.needs_human_review)

    def test_scenario_5_upholds_the_appeal_and_cancels_the_challan(self) -> None:
        result = self.results["false_positive_appeal"]
        cancelled = [
            row for row in self.store.list_challans(plate="LEB-1234")
            if row["status"] == ChallanStatus.CANCELLED.value
        ]
        self.assertTrue(cancelled)
        dispute_trace = next(t for t in result.traces if "Dispute" in t.agent)
        self.assertIn("INTEGRITY_FAIL", dispute_trace.verdict)
        self.assertTrue(dispute_trace.details["cancelled_challans"])

    def test_scenario_5_keeps_the_intact_bundle_verified(self) -> None:
        result = self.results["false_positive_appeal"]
        self.assertTrue(result.evidence.verified)

    def test_detection_never_issues_a_challan_without_evidence(self) -> None:
        """No scenario may produce a challan whose evidence confidence is under
        the gate. This is the anti-false-positive invariant."""
        from smartflow.config import DEFAULT_POLICY

        for key, result in self.results.items():
            if result.challan is None:
                continue
            confidence = result.decision.risk.inputs["evidence"]
            self.assertGreaterEqual(
                confidence,
                DEFAULT_POLICY.evidence_gate.min_confidence_for_challan,
                f"{key} issued a challan on weak evidence ({confidence})",
            )


class PersistenceTests(unittest.TestCase):
    def test_all_scenarios_persist_challans_and_events(self) -> None:
        store = Store(":memory:")
        try:
            results = run_all(store, as_of=AS_OF)
            stats = store.stats()
            issued = sum(1 for r in results if r.challan is not None)
            self.assertGreaterEqual(stats["challans"], issued + len(results[3].history))
            self.assertGreater(stats["events"], 0)
            self.assertGreater(stats["agent_traces"], 0)
        finally:
            store.close()

    def test_audit_trail_records_the_decision_chain(self) -> None:
        store = Store(":memory:")
        try:
            result = run_scenario(get_scenario("unpaid_escalation"), store, as_of=AS_OF)
            assert result.challan is not None
            trail = store.audit_trail(result.challan.challan_id)
            kinds = {entry["kind"] for entry in trail}
            self.assertIn("CHALLAN_ISSUED", kinds)
            self.assertTrue(all(entry["actor"] for entry in trail))
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
