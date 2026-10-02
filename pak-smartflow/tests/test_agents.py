"""Agent pipeline structure and behaviour."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from smartflow.agents import AGENTS, AGENT_COUNT
from smartflow.config import DEFAULT_POLICY
from smartflow.db import Store
from smartflow.models import AgentMaturity, ViolationType
from smartflow.pipeline import run_scenario
from smartflow.scenarios import get_scenario

AS_OF = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


class AgentStructureTests(unittest.TestCase):
    def test_twelve_agents(self) -> None:
        self.assertEqual(AGENT_COUNT, 12)
        self.assertEqual(len(AGENTS), 12)

    def test_agent_names_are_unique(self) -> None:
        names = [agent.name for agent in AGENTS]
        self.assertEqual(len(names), len(set(names)))

    def test_levels_run_from_perception_to_compliance(self) -> None:
        levels = [agent.level for agent in AGENTS]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual(levels[0], 1)
        self.assertEqual(levels[-1], 6)

    def test_each_level_has_at_least_one_agent(self) -> None:
        self.assertEqual({agent.level for agent in AGENTS}, {1, 2, 3, 4, 5, 6})

    def test_maturity_labels_are_honest_and_mixed(self) -> None:
        labels = {agent.maturity for agent in AGENTS}
        self.assertEqual(labels, set(AgentMaturity))
        deep = [a for a in AGENTS if a.maturity is AgentMaturity.DEEP]
        self.assertGreaterEqual(len(deep), 4)

    def test_detector_and_anpr_are_labelled_as_mocks(self) -> None:
        by_name = {agent.name: agent for agent in AGENTS}
        self.assertIs(by_name["1. Detection"].maturity, AgentMaturity.MOCK)
        self.assertIs(by_name["2. ANPR & Registry"].maturity, AgentMaturity.MOCK)


class PolicySeverityTests(unittest.TestCase):
    """Concurrent violations must compound, but not without limit."""

    def test_single_violation_uses_its_own_score(self) -> None:
        policy = DEFAULT_POLICY
        self.assertEqual(
            policy.severity_for_event((ViolationType.RED_LIGHT,)),
            policy.severity_for(ViolationType.RED_LIGHT),
        )

    def test_concurrent_violations_score_higher_than_either_alone(self) -> None:
        policy = DEFAULT_POLICY
        pair = (ViolationType.WRONG_WAY, ViolationType.OVERSPEEDING)
        compounded = policy.severity_for_event(pair)
        self.assertGreater(compounded, policy.severity_for(ViolationType.WRONG_WAY))
        self.assertGreater(compounded, policy.severity_for(ViolationType.OVERSPEEDING))

    def test_compounding_cannot_exceed_one_hundred(self) -> None:
        policy = DEFAULT_POLICY
        many = tuple(ViolationType) * 5
        self.assertEqual(policy.severity_for_event(many), 100.0)

    def test_stacking_trivial_violations_stays_modest(self) -> None:
        policy = DEFAULT_POLICY
        trivial = (ViolationType.ILLEGAL_PARKING,) * 3
        self.assertLess(policy.severity_for_event(trivial), 45.0)

    def test_empty_event_has_no_severity(self) -> None:
        self.assertEqual(DEFAULT_POLICY.severity_for_event(()), 0.0)


class PipelineExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")
        self.result = run_scenario(get_scenario("red_light"), self.store, as_of=AS_OF)

    def tearDown(self) -> None:
        self.store.close()

    def test_every_agent_produces_exactly_one_trace(self) -> None:
        self.assertEqual(len(self.result.traces), AGENT_COUNT)

    def test_traces_are_in_execution_order(self) -> None:
        self.assertEqual(
            [trace.agent for trace in self.result.traces],
            [agent.name for agent in AGENTS],
        )

    def test_run_id_is_shared_by_all_traces(self) -> None:
        self.assertEqual({trace.run_id for trace in self.result.traces}, {self.result.run_id})

    def test_every_trace_has_a_verdict_and_details(self) -> None:
        for trace in self.result.traces:
            self.assertTrue(trace.verdict.strip(), trace.agent)
            self.assertIsInstance(dict(trace.details), dict)

    def test_durations_are_recorded(self) -> None:
        self.assertTrue(all(trace.duration_ms >= 0 for trace in self.result.traces))

    def test_traces_are_persisted(self) -> None:
        stored = self.store.traces_for(self.result.run_id)
        self.assertEqual(len(stored), AGENT_COUNT)

    def test_out_of_order_state_access_fails_loudly(self) -> None:
        from smartflow.agents import AgentContext

        context = AgentContext(
            run_id="RUN-TEST", scenario="unit", as_of=AS_OF, store=Store(":memory:")
        )
        with self.assertRaises(KeyError):
            context.require("decision")

    def test_runs_are_independent(self) -> None:
        second = run_scenario(get_scenario("red_light"), self.store, as_of=AS_OF)
        self.assertNotEqual(self.result.run_id, second.run_id)
        self.assertAlmostEqual(
            self.result.decision.risk.score, second.decision.risk.score, places=6
        )


if __name__ == "__main__":
    unittest.main()
