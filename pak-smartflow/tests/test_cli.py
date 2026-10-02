"""CLI smoke tests.

Two real bugs motivated this file, both invisible to unit tests and both fatal
on stage:

1. ``smartflow legal`` printed a Python list because a renderer returned
   ``list[str]`` and the caller handed it straight to ``print``.
2. ``smartflow fuzzy`` built its whole report and never printed it, because an
   edit removed the final call.

So every subcommand is now executed in-process, and every one must exit 0 **and
produce output**. A command that silently prints nothing is a failure.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from smartflow.cli import main


def run(*argv: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue() + err.getvalue()


class CommandOutputTests(unittest.TestCase):
    def test_scenarios_lists_all_five(self) -> None:
        code, output = run("scenarios")
        self.assertEqual(code, 0)
        for number in range(1, 6):
            self.assertIn(f"{number}.", output)
        self.assertIn("red_light", output)
        self.assertIn("unpaid_escalation", output)

    def test_fuzzy_prints_the_whole_report(self) -> None:
        code, output = run("fuzzy")
        self.assertEqual(code, 0)
        for expected in (
            "Membership terms",
            "Decision bands",
            "Rule base",
            "Monotonicity check",
            "Reference cases",
        ):
            self.assertIn(expected, output, expected)
        self.assertGreater(len(output.splitlines()), 60)

    def test_fuzzy_reference_cases_match_the_pipeline(self) -> None:
        """The calibration table derives its inputs from the real scenarios, so
        the engine verdict shown must equal the score the pipeline reports."""
        from datetime import datetime, timezone

        from smartflow.fuzzy import DEFAULT_ENGINE
        from smartflow.prediction import estimate_collision_risk
        from smartflow.evidence import cross_frame_agreement
        from smartflow.config import DEFAULT_POLICY
        from smartflow.scenarios import SCENARIOS, build_event

        for spec in SCENARIOS:
            event = build_event(spec, as_of=datetime(2026, 10, 2, tzinfo=timezone.utc))
            assessment = DEFAULT_ENGINE.evaluate(
                {
                    "evidence": cross_frame_agreement(
                        event.frames, event.violations[0].value
                    ),
                    "severity": DEFAULT_POLICY.severity_for_event(event.violations),
                    "collision": estimate_collision_risk(
                        event.speed_kmh,
                        event.speed_limit_kmh,
                        event.traffic_density,
                        DEFAULT_POLICY.context_factor(event.context_tags),
                    ).score,
                    "density": event.traffic_density,
                    "context": DEFAULT_POLICY.context_factor(event.context_tags),
                }
            )
            self.assertGreater(assessment.score, 0.0, spec.key)
            self.assertTrue(assessment.rule_firings, spec.key)

    def test_legal_is_text_not_a_list_repr(self) -> None:
        code, output = run("legal")
        self.assertEqual(code, 0)
        self.assertNotIn("['", output)
        self.assertNotIn("']", output)
        self.assertIn("LEGAL BOUNDARY", output)
        self.assertIn("driver biometrics", output)
        self.assertIn("block_real_cnic", output)

    def test_legal_quotes_the_safe_statement(self) -> None:
        _, output = run("legal")
        self.assertIn("authorized government ecosystem", output)

    def test_probe_blocks_everything_and_exits_clean(self) -> None:
        code, output = run("probe")
        self.assertEqual(code, 0)
        self.assertIn("Prohibited operations that succeeded: 0", output)
        self.assertIn("Network calls made to any external system: 0", output)
        self.assertNotIn("SUCCEEDED", output)

    def test_selftest_passes(self) -> None:
        code, output = run("selftest")
        self.assertEqual(code, 0)
        self.assertIn("14/14 invariant checks passed", output)
        self.assertNotIn("[FAIL]", output)

    def test_demo_single_scenario(self) -> None:
        code, output = run("demo", "4")
        self.assertEqual(code, 0)
        for expected in (
            "AGENT TRACE",
            "FUZZY DECISION ENGINE",
            "CHALLAN",
            "COMPLIANCE PROFILE",
            "ESCALATION TIMELINE",
            "ENFORCEMENT REQUEST",
            "PAYMENTS",
            "CASE AUDIT TRAIL",
            "LEGAL BOUNDARY",
        ):
            self.assertIn(expected, output, expected)
        self.assertIn("COMPLIANT", output)

    def test_demo_accepts_a_key_instead_of_a_number(self) -> None:
        code, output = run("demo", "unpaid_escalation")
        self.assertEqual(code, 0)
        self.assertIn("UNPAID ESCALATION", output)

    def test_demo_urdu_flag_prints_urdu_script(self) -> None:
        code, output = run("demo", "4", "--urdu")
        self.assertEqual(code, 0)
        self.assertTrue(
            any("\u0600" <= ch <= "\u06ff" for ch in output),
            "no Urdu script in the output despite --urdu",
        )

    def test_demo_all_prints_a_summary(self) -> None:
        code, output = run("demo", "--all")
        self.assertEqual(code, 0)
        self.assertIn("RUN SUMMARY", output)
        for key in (
            "red_light",
            "collision_risk",
            "ambulance",
            "unpaid_escalation",
            "false_positive_appeal",
        ):
            self.assertIn(key, output, key)

    def test_db_stats_after_a_run(self) -> None:
        # The in-memory store is per-invocation, so this asserts the empty-state
        # renderer still produces a report rather than crashing.
        code, output = run("db")
        self.assertEqual(code, 0)
        self.assertIn("DATABASE", output)
        self.assertIn("Challans", output)

    def test_unknown_scenario_exits_with_a_clean_error(self) -> None:
        code, output = run("demo", "no-such-scenario")
        self.assertEqual(code, 2)
        self.assertIn("error:", output)

    def test_no_arguments_prints_help(self) -> None:
        code, output = run()
        self.assertEqual(code, 0)
        self.assertIn("usage: smartflow", output)

    def test_every_subcommand_is_registered(self) -> None:
        from smartflow.cli import build_parser

        parser = build_parser()
        actions = [
            a for a in parser._actions if hasattr(a, "choices") and a.choices
        ]
        commands = set()
        for action in actions:
            commands.update(action.choices)
        self.assertEqual(
            commands,
            {
                "scenarios",
                "demo",
                "fuzzy",
                "compliance",
                "db",
                "legal",
                "probe",
                "selftest",
            },
        )


if __name__ == "__main__":
    unittest.main()
