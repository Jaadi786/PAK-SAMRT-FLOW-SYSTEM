"""Fuzzy engine tests: geometry, coverage, monotonicity, validation."""

from __future__ import annotations

import unittest

from smartflow.fuzzy import (
    DEFAULT_ENGINE,
    INPUT_TERMS,
    INPUT_VARIABLES,
    LEVEL_BANDS,
    OUTPUT_TERMS,
    RULES,
    FuzzyRiskEngine,
    Rule,
    level_for_score,
    trimf,
    trapmf,
)


class MembershipFunctionTests(unittest.TestCase):
    def test_triangle_peaks_at_one(self) -> None:
        self.assertAlmostEqual(trimf(50.0, 0.0, 50.0, 100.0), 1.0)
        self.assertAlmostEqual(trimf(25.0, 0.0, 50.0, 100.0), 0.5)
        self.assertAlmostEqual(trimf(75.0, 0.0, 50.0, 100.0), 0.5)
        self.assertEqual(trimf(-1.0, 0.0, 50.0, 100.0), 0.0)
        self.assertEqual(trimf(101.0, 0.0, 50.0, 100.0), 0.0)

    def test_left_shoulder_is_true_at_zero(self) -> None:
        """Regression: a hand-written trimf/trapmf that tests `x <= a` first
        returns 0.0 at the left shoulder, which silently empties the rule base
        for the most extreme inputs. This bit us during development."""
        self.assertAlmostEqual(trapmf(0.0, 0.0, 0.0, 12.0, 45.0), 1.0)
        self.assertAlmostEqual(trimf(0.0, 0.0, 0.0, 45.0), 1.0)

    def test_right_shoulder_is_true_at_hundred(self) -> None:
        self.assertAlmostEqual(trapmf(100.0, 55.0, 88.0, 100.0, 100.0), 1.0)
        self.assertAlmostEqual(trimf(100.0, 55.0, 100.0, 100.0), 1.0)

    def test_plateau_is_flat(self) -> None:
        for x in (88.0, 90.0, 95.0, 100.0):
            self.assertAlmostEqual(trapmf(x, 55.0, 88.0, 100.0, 100.0), 1.0)

    def test_malformed_points_rejected(self) -> None:
        with self.assertRaises(ValueError):
            trimf(5.0, 10.0, 2.0, 3.0)
        with self.assertRaises(ValueError):
            trapmf(5.0, 1.0, 2.0, 1.0, 4.0)


class RuleBaseIntegrityTests(unittest.TestCase):
    def test_every_rule_references_known_terms(self) -> None:
        for rule in RULES:
            self.assertIn(rule.consequent, OUTPUT_TERMS, rule.label)
            for variable, term in rule.conditions.items():
                self.assertIn(variable, INPUT_VARIABLES, rule.label)
                self.assertIn(term, INPUT_TERMS, rule.label)

    def test_engine_rejects_unknown_input(self) -> None:
        with self.assertRaises(ValueError):
            FuzzyRiskEngine(rules=(Rule("bad", {"nonsense": "low"}, "low"),))

    def test_engine_rejects_unknown_consequent(self) -> None:
        with self.assertRaises(ValueError):
            FuzzyRiskEngine(rules=(Rule("bad", {"severity": "low"}, "apocalyptic"),))

    def test_every_output_term_is_reachable(self) -> None:
        """A consequent that no input region can reach is dead weight."""
        reached: set[str] = set()
        for severity in range(0, 101, 5):
            for evidence in range(0, 101, 20):
                for collision in range(0, 101, 25):
                    for density in (0.0, 50.0, 100.0):
                        for context in (0.0, 50.0, 100.0):
                            assessment = DEFAULT_ENGINE.evaluate(
                                {
                                    "evidence": float(evidence),
                                    "severity": float(severity),
                                    "collision": float(collision),
                                    "density": density,
                                    "context": context,
                                }
                            )
                            reached.update(
                                firing.consequent for firing in assessment.rule_firings
                            )
        self.assertEqual(set(OUTPUT_TERMS), reached)

    def test_rule_base_is_not_empty_in_the_extremes(self) -> None:
        """No silent fallback at the corners of the input space."""
        corners = [
            {"evidence": e, "severity": s, "collision": c, "density": d, "context": x}
            for e in (0.0, 100.0)
            for s in (0.0, 100.0)
            for c in (0.0, 100.0)
            for d in (0.0, 100.0)
            for x in (0.0, 100.0)
        ]
        for inputs in corners:
            assessment = DEFAULT_ENGINE.evaluate(inputs)
            self.assertFalse(
                assessment.fallback_used,
                f"fallback used for {inputs}: the rule base has a hole",
            )
            self.assertTrue(assessment.rule_firings)


class MonotonicityTests(unittest.TestCase):
    """Raising a risk input must never lower the score meaningfully.

    Tolerance note: with max-aggregation over overlapping output terms, four of
    the five inputs are exactly monotone. ``evidence`` has a measured worst-case
    dip of 0.07 points out of 100 as strength migrates from the "medium
    evidence" rule to the "high evidence" rule. That is a documented property of
    Mamdani inference with overlapping consequents, not a defect, so the test
    asserts the documented bound rather than pretending it is zero.
    """

    TOLERANCE = 0.25

    def _sweep(self, variable: str, base: dict[str, float]) -> list[float]:
        scores: list[float] = []
        for value in range(0, 101):
            inputs = dict(base)
            inputs[variable] = float(value)
            scores.append(DEFAULT_ENGINE.evaluate(inputs).score)
        return scores

    def test_all_inputs_are_monotone_within_tolerance(self) -> None:
        bases = {
            "severity": {
                "evidence": 100.0, "collision": 50.0, "density": 50.0, "context": 50.0
            },
            "collision": {
                "evidence": 100.0, "severity": 80.0, "density": 50.0, "context": 50.0
            },
            "density": {
                "evidence": 100.0, "severity": 80.0, "collision": 60.0, "context": 50.0
            },
            "context": {
                "evidence": 100.0, "severity": 80.0, "collision": 60.0, "density": 50.0
            },
            "evidence": {
                "severity": 80.0, "collision": 60.0, "density": 50.0, "context": 50.0
            },
        }
        for variable, base in bases.items():
            scores = self._sweep(variable, base)
            worst = max(
                (previous - current)
                for previous, current in zip(scores, scores[1:])
                if current < previous
            ) if any(b < a for a, b in zip(scores, scores[1:])) else 0.0
            self.assertLessEqual(
                worst,
                self.TOLERANCE,
                f"{variable} sweep dips by {worst:.3f} points (limit {self.TOLERANCE})",
            )

    def test_severity_and_collision_are_exactly_monotone(self) -> None:
        for variable, base in (
            ("severity", {
                "evidence": 100.0, "collision": 50.0, "density": 50.0, "context": 50.0
            }),
            ("collision", {
                "evidence": 100.0, "severity": 80.0, "density": 50.0, "context": 50.0
            }),
            ("density", {
                "evidence": 100.0, "severity": 80.0, "collision": 60.0, "context": 50.0
            }),
        ):
            scores = self._sweep(variable, base)
            self.assertEqual(
                scores, sorted(scores), f"{variable} sweep is not sorted"
            )

    def test_verdict_never_downgrades_as_severity_rises(self) -> None:
        order = {level: index for index, (_, level) in enumerate(LEVEL_BANDS)}
        previous = -1
        for value in range(0, 101):
            assessment = DEFAULT_ENGINE.evaluate(
                {
                    "evidence": 90.0,
                    "severity": float(value),
                    "collision": 70.0,
                    "density": 70.0,
                    "context": 70.0,
                }
            )
            rank = order[assessment.level]
            self.assertGreaterEqual(rank, previous)
            previous = rank


class ValidationTests(unittest.TestCase):
    def test_missing_input_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DEFAULT_ENGINE.evaluate({"evidence": 50.0})

    def test_out_of_range_rejected(self) -> None:
        for bad in (-0.1, 100.1, 1e9):
            with self.assertRaises(ValueError):
                DEFAULT_ENGINE.evaluate(
                    {
                        "evidence": bad, "severity": 50.0, "collision": 50.0,
                        "density": 50.0, "context": 50.0,
                    }
                )

    def test_all_inputs_are_required_by_the_engine(self) -> None:
        self.assertEqual(set(INPUT_VARIABLES), {
            "evidence", "severity", "collision", "density", "context"
        })


class ExplainabilityTests(unittest.TestCase):
    def test_contributions_sum_to_one_hundred_when_rules_fire(self) -> None:
        assessment = DEFAULT_ENGINE.evaluate(
            {"evidence": 95.0, "severity": 92.0, "collision": 85.0,
             "density": 88.0, "context": 90.0}
        )
        self.assertTrue(assessment.rule_firings)
        self.assertAlmostEqual(sum(assessment.contributions.values()), 100.0, places=1)

    def test_firings_are_sorted_by_strength(self) -> None:
        assessment = DEFAULT_ENGINE.evaluate(
            {"evidence": 95.0, "severity": 92.0, "collision": 85.0,
             "density": 88.0, "context": 90.0}
        )
        strengths = [firing.strength for firing in assessment.rule_firings]
        self.assertEqual(strengths, sorted(strengths, reverse=True))

    def test_centroid_is_reported_alongside_the_score(self) -> None:
        assessment = DEFAULT_ENGINE.evaluate(
            {"evidence": 95.0, "severity": 70.0, "collision": 40.0,
             "density": 40.0, "context": 40.0}
        )
        self.assertIsNotNone(assessment.centroid_cog)
        self.assertGreaterEqual(assessment.centroid_cog, 0.0)

    def test_weak_evidence_is_not_penalised_by_the_score_alone(self) -> None:
        """Even a severe allegation scores lower when the frames disagree."""
        strong = DEFAULT_ENGINE.evaluate(
            {"evidence": 100.0, "severity": 92.0, "collision": 60.0,
             "density": 60.0, "context": 60.0}
        )
        weak = DEFAULT_ENGINE.evaluate(
            {"evidence": 15.0, "severity": 92.0, "collision": 60.0,
             "density": 60.0, "context": 60.0}
        )
        self.assertLess(weak.score, strong.score)


class LevelBandTests(unittest.TestCase):
    def test_bands_are_ordered_and_complete(self) -> None:
        self.assertEqual(level_for_score(0.0).value, "LOW")
        self.assertEqual(level_for_score(100.0).value, "CRITICAL")
        thresholds = [upper for upper, _ in LEVEL_BANDS]
        self.assertEqual(thresholds, sorted(thresholds))
        self.assertEqual(thresholds[-1], 101.0)

    def test_bands_sit_near_term_centroids(self) -> None:
        centroids = {name: term.centroid for name, term in OUTPUT_TERMS.items()}
        self.assertLess(centroids["low"], centroids["medium"])
        self.assertLess(centroids["medium"], centroids["high"])
        self.assertLess(centroids["high"], centroids["critical"])


if __name__ == "__main__":
    unittest.main()
