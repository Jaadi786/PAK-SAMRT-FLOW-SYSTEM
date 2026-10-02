"""Decision policy: turns a fuzzy risk score into an action, with guardrails.

Three things happen here, in order, and all three are printed in the demo:

1. **Safety Overlay** -- extreme collision + severity + density promotes HIGH
   to CRITICAL (a hard rule on top of the soft score).
2. **Evidence Gate** -- weak evidence blocks a challan outright, and a serious
   allegation on weak evidence is routed to a human reviewer.
3. **Action Matrix** -- the surviving verdict maps to concrete actions.

Keeping these separate from the fuzzy engine matters: the fuzzy engine answers
*"how risky does this look?"* and this module answers *"what are we entitled to
do about it?"*. That distinction is the whole legal argument of the project.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .config import ACTION_MATRIX, DEFAULT_POLICY, PolicyConfig
from .models import Decision, RiskAssessment, RiskLevel

NO_PENALTY_ACTIONS: tuple[str, ...] = ("LOG_ONLY", "NO_CHALLAN", "EVIDENCE_REVIEW")


def apply_safety_overlay(
    assessment: RiskAssessment, config: PolicyConfig
) -> tuple[RiskAssessment, str | None]:
    overlay = config.overlay
    if assessment.level is RiskLevel.HIGH and overlay.applies(assessment.inputs):
        promoted = replace(assessment, level=RiskLevel.CRITICAL)
        return promoted, overlay.reason(assessment.inputs)
    return assessment, None


def apply_evidence_gate(
    assessment: RiskAssessment, config: PolicyConfig
) -> tuple[bool, bool, str | None]:
    """Return ``(blocked, needs_human_review, reason)``."""
    gate = config.evidence_gate
    confidence = assessment.inputs.get("evidence", 0.0)
    severity = assessment.inputs.get("severity", 0.0)

    if confidence < gate.min_confidence_for_challan:
        return (
            True,
            True,
            f"Evidence Gate: confidence {confidence:.1f} is below the "
            f"{gate.min_confidence_for_challan:.0f} threshold required to penalise "
            "anyone. Logged for review; no challan issued.",
        )
    if (
        severity >= gate.serious_severity_threshold
        and confidence < gate.serious_min_confidence
    ):
        return (
            True,
            True,
            f"Evidence Gate: severity {severity:.0f} is serious but confidence "
            f"{confidence:.1f} is only {confidence:.1f}. Routed to a human reviewer "
            "instead of issuing a challan.",
        )
    return False, False, None


def decide(assessment: RiskAssessment, config: PolicyConfig | None = None) -> Decision:
    """Produce the final, explainable decision for one violation."""
    policy = config or DEFAULT_POLICY
    reasons: list[str] = []

    published, overlay_reason = apply_safety_overlay(assessment, policy)
    if overlay_reason:
        reasons.append(overlay_reason)

    blocked, gate_review, gate_reason = apply_evidence_gate(published, policy)
    if gate_reason:
        reasons.append(gate_reason)

    plan = ACTION_MATRIX[published.level]
    if blocked:
        actions = NO_PENALTY_ACTIONS
        issue_challan = False
    else:
        actions = plan.actions
        issue_challan = plan.issue_challan

    needs_human_review = plan.needs_human_review or gate_review
    if issue_challan and published.review_recommended:
        needs_human_review = True
        reasons.append(
            "Score and policy-weighted baseline diverge by more than 25 points; "
            "flagged for human review."
        )

    reasons.append(
        f"Fuzzy risk score {published.score:.1f}/100 -> {published.level.value}. "
        f"{plan.summary}"
    )
    if not issue_challan:
        reasons.append(
            "No penalty issued. Logging a violation the evidence does not support "
            "would be a false positive, which costs more trust than it recovers revenue."
        )

    return Decision(
        actions=actions,
        issue_challan=issue_challan,
        needs_human_review=needs_human_review,
        rationale=" ".join(reasons),
        risk=published,
        policy_version=policy.version,
    )


def explain_decision(decision: Decision, top: int = 3) -> list[str]:
    """Ranked 'why' lines for the officer view and the citizen notice."""
    from .fuzzy import INPUT_LABELS, describe_firings, top_contributors

    lines = [
        f"Risk score: {decision.risk.score:.1f}/100 ({decision.risk.level.value})",
        f"Engine: {decision.risk.engine}",
        "Top contributing factors:",
    ]
    for name, share in top_contributors(decision.risk, top):
        value = decision.risk.inputs.get(name, 0.0)
        label = INPUT_LABELS.get(name, name)
        lines.append(f"  - {label}: {share:.0f}% of firing strength (input {value:.0f}/100)")
    lines.append("Rules that fired:")
    lines.extend(f"  {line}" for line in describe_firings(decision.risk, top))
    return lines
