"""Policy configuration -- every number a human authority would set.

Nothing here is baked into logic. Fines, penalty tranches, escalation
timelines and score weights all live in one versioned, frozen object so that a
provincial transport authority could swap policy without touching code. The
demo prints ``policy_version`` on every challan and notice for exactly that
reason.

All monetary values are illustrative demo values in PKR, not a statement of
current law.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .models import EscalationStage, RiskLevel, ViolationType


# --------------------------------------------------------------------------- #
# Risk -> action policy
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ActionPlan:
    issue_challan: bool
    actions: tuple[str, ...]
    needs_human_review: bool
    summary: str


ACTION_MATRIX: Mapping[RiskLevel, ActionPlan] = {
    RiskLevel.LOW: ActionPlan(
        issue_challan=False,
        actions=("LOG_ONLY", "NO_CHALLAN"),
        needs_human_review=False,
        summary="Evidence does not justify a penalty. Logged for analytics only.",
    ),
    RiskLevel.MEDIUM: ActionPlan(
        issue_challan=True,
        actions=("CHALLAN", "SAFETY_ADVISORY", "MONITOR"),
        needs_human_review=False,
        summary="Challan with a safety advisory; no enforcement flag.",
    ),
    RiskLevel.HIGH: ActionPlan(
        issue_challan=True,
        actions=("CHALLAN", "SAFETY_ALERT", "MONITOR", "PATROL_HINT"),
        needs_human_review=False,
        summary="Challan, safety alert and a patrol hint for this corridor.",
    ),
    RiskLevel.CRITICAL: ActionPlan(
        issue_challan=True,
        actions=(
            "CHALLAN",
            "IMMEDIATE_SAFETY_ALERT",
            "PATROL_HINT",
            "SIGNAL_REVIEW",
            "HUMAN_REVIEW",
        ),
        needs_human_review=True,
        summary="Challan plus immediate safety alert; routed to a human reviewer.",
    ),
}


@dataclass(frozen=True)
class SafetyOverlay:
    """Hard safety constraints layered on top of the soft fuzzy score.

    A fuzzy score alone cannot reach CRITICAL reliably (see the note in
    ``fuzzy.py``). Rather than fudge membership functions, extreme real-world
    combinations promote a HIGH verdict explicitly. The promotion is printed
    with the decision, so it is explainable rather than magic.
    """

    min_collision: float = 85.0
    min_severity: float = 85.0
    min_density: float = 80.0

    def applies(self, inputs: Mapping[str, float]) -> bool:
        return (
            inputs.get("collision", 0.0) >= self.min_collision
            and inputs.get("severity", 0.0) >= self.min_severity
            and inputs.get("density", 0.0) >= self.min_density
        )

    def reason(self, inputs: Mapping[str, float]) -> str:
        return (
            "Safety Overlay applied: collision exposure "
            f"{inputs.get('collision', 0):.0f}, violation severity "
            f"{inputs.get('severity', 0):.0f} and traffic density "
            f"{inputs.get('density', 0):.0f} are all in the extreme band, so the "
            "verdict is promoted from HIGH to CRITICAL."
        )


@dataclass(frozen=True)
class EvidenceGate:
    """Evidence quality gates enforcement.

    Two independent guards:

    * nothing is penalised below ``min_confidence_for_challan``, no matter how
      severe the alleged violation; and
    * a *serious* allegation backed by weak evidence is routed to a human
      reviewer instead of producing a challan. Over-enforcement is treated as a
      failure mode, not a bonus.
    """

    min_confidence_for_challan: float = 55.0
    serious_severity_threshold: float = 70.0
    serious_min_confidence: float = 45.0


# --------------------------------------------------------------------------- #
# Progressive penalty policy
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PenaltyPolicy:
    """Late-fee ladder. Tranches are (days_past_due, fraction_of_base_fine)."""

    policy_version: str = "PK-SF-PENALTY-v0.3-DEMO"
    due_days: int = 30
    tranches: tuple[tuple[int, float], ...] = ((30, 0.10), (60, 0.25), (90, 0.50))
    #: 1.75x, not 2.0x. The tranche fractions sum to 0.85, so a 2.0x ceiling
    #: would never bind -- the cap would be decorative. At 1.75x the final
    #: tranche is partially absorbed by the ceiling, which is exactly what a
    #: statutory cap is for, and the citizen-facing receipt says so.
    cap_multiplier: float = 1.75
    early_payment_discount_pct: float = 0.10
    early_payment_window_days: int = 7
    payment_plan_available_after_days: int = 45
    payment_plan_instalments: int = 3
    note: str = (
        "Illustrative demo values. A real deployment must take these from the "
        "authority's notified schedule; the prototype never invents law."
    )


# --------------------------------------------------------------------------- #
# Escalation policy
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EscalationStagePolicy:
    stage: EscalationStage
    after_days: int
    channel: str
    requires_human_approval: bool
    auto: bool
    description: str


@dataclass(frozen=True)
class EscalationPolicy:
    """Compliance escalation ladder.

    The move to an enforcement request requires a *two-key* rule: enough elapsed
    time **and** a low enough compliance score. Either alone is not sufficient.
    """

    policy_version: str = "PK-SF-ESCALATION-v0.3-DEMO"
    stages: tuple[EscalationStagePolicy, ...] = (
        EscalationStagePolicy(
            EscalationStage.ISSUED, 0, "citizen portal", False, True,
            "Challan issued with evidence bundle and explanation.",
        ),
        EscalationStagePolicy(
            EscalationStage.REMINDER_1, 7, "SMS + WhatsApp", False, True,
            "Friendly first reminder with a working payment link.",
        ),
        EscalationStagePolicy(
            EscalationStage.REMINDER_2, 15, "SMS + WhatsApp + Urdu voice note", False, True,
            "Second reminder, adds voice and offers a payment plan.",
        ),
        EscalationStagePolicy(
            EscalationStage.FINAL_NOTICE, 25, "SMS + Urdu voice note + notice PDF", False, True,
            "Final notice before the due date, states the late-fee ladder.",
        ),
        EscalationStagePolicy(
            EscalationStage.ENFORCEMENT_REQUEST, 60, "authority portal (simulated)", True, True,
            "Prepare an Enforcement Request packet for an authorised officer.",
        ),
        EscalationStagePolicy(
            EscalationStage.AUTHORITY_REVIEW, 60, "human officer queue", True, False,
            "A named human officer decides. The prototype takes no action here.",
        ),
        EscalationStagePolicy(
            EscalationStage.RESOLVED, 0, "citizen portal", False, False,
            "Paid, cancelled, or otherwise closed. Case file sealed.",
        ),
    )
    max_compliance_score_for_enforcement: float = 40.0
    cooling_off_days: int = 7
    note: str = (
        "Escalation is a notification workflow, never an enforcement action. "
        "The final step produces a draft packet for human authority review."
    )

    def stage_policy(self, stage: EscalationStage) -> EscalationStagePolicy:
        for item in self.stages:
            if item.stage is stage:
                return item
        raise KeyError(stage)


# --------------------------------------------------------------------------- #
# Compliance scoring
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ComplianceWeights:
    """Weights that turn raw history into a 0-100 compliance score.

    The score starts at 100 and deductions are applied, each capped so no single
    factor can dominate. Voluntary engagement (payment attempts) earns credit
    back -- the model rewards participation, not just payment.
    """

    per_unpaid_challan: float = 5.0
    max_unpaid_component: float = 40.0
    outstanding_per_1000_pkr: float = 2.5
    max_outstanding_component: float = 25.0
    age_scale_days: float = 127.0
    max_age_component: float = 15.0
    per_notice: float = 3.0
    max_notice_component: float = 10.0
    per_open_dispute: float = 6.0
    max_dispute_component: float = 12.0
    per_payment_attempt_credit: float = 4.0
    max_payment_credit: float = 12.0

    tiers: tuple[tuple[float, str], ...] = (
        (80.0, "COMPLIANT"),
        (60.0, "WATCH"),
        (35.0, "HIGH"),
        (0.0, "SEVERE"),
    )


# --------------------------------------------------------------------------- #
# Top-level policy bundle
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PolicyConfig:
    version: str = "PK-SF-POLICY-v0.3-DEMO"
    currency: str = "PKR"
    penalty: PenaltyPolicy = field(default_factory=PenaltyPolicy)
    escalation: EscalationPolicy = field(default_factory=EscalationPolicy)
    compliance: ComplianceWeights = field(default_factory=ComplianceWeights)
    overlay: SafetyOverlay = field(default_factory=SafetyOverlay)
    evidence_gate: EvidenceGate = field(default_factory=EvidenceGate)
    fuzzy_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "evidence": 0.25,
            "severity": 0.25,
            "collision": 0.20,
            "density": 0.15,
            "context": 0.15,
        }
    )
    base_fines: Mapping[ViolationType, float] = field(
        default_factory=lambda: {
            ViolationType.RED_LIGHT: 1000.0,
            ViolationType.OVERSPEEDING: 1500.0,
            ViolationType.WRONG_WAY: 1200.0,
            ViolationType.MOBILE_USE: 800.0,
            ViolationType.NO_HELMET: 500.0,
            ViolationType.NO_SEATBELT: 500.0,
            ViolationType.LANE_VIOLATION: 400.0,
            ViolationType.ILLEGAL_PARKING: 300.0,
        }
    )
    severity_scores: Mapping[ViolationType, float] = field(
        default_factory=lambda: {
            ViolationType.RED_LIGHT: 88.0,
            ViolationType.WRONG_WAY: 82.0,
            ViolationType.OVERSPEEDING: 76.0,
            ViolationType.MOBILE_USE: 68.0,
            ViolationType.NO_HELMET: 58.0,
            ViolationType.NO_SEATBELT: 52.0,
            ViolationType.LANE_VIOLATION: 34.0,
            ViolationType.ILLEGAL_PARKING: 22.0,
        }
    )
    context_scores: Mapping[str, float] = field(
        default_factory=lambda: {
            "SCHOOL_ZONE": 90.0,
            "HOSPITAL_ZONE": 85.0,
            "RUSH_HOUR": 78.0,
            "NIGHT": 62.0,
            "RAIN": 70.0,
            "CONSTRUCTION": 66.0,
            "INTERSECTION": 58.0,
            "OPEN_ROAD": 25.0,
        }
    )
    plate_salt: str = "pak-smartflow-demo-salt"
    simulation: bool = True
    #: Concurrent violations compound. A driver going the wrong way *while*
    #: speeding is not merely as dangerous as the worse of the two offences.
    #: The bonus is small and capped so that stacking trivia cannot manufacture
    #: a CRITICAL verdict on its own.
    compounding_bonus_per_extra: float = 5.0

    def fine_for(self, violation: ViolationType) -> float:
        return float(self.base_fines[violation])

    def severity_for(self, violation: ViolationType) -> float:
        return float(self.severity_scores[violation])

    def severity_for_event(self, violations: Sequence[ViolationType]) -> float:
        """Severity for an event that may carry more than one violation."""
        if not violations:
            return 0.0
        base = max(self.severity_for(v) for v in violations)
        bonus = self.compounding_bonus_per_extra * (len(violations) - 1)
        return round(min(100.0, base + bonus), 1)

    def context_factor(self, tags: tuple[str, ...]) -> float:
        """Highest single context factor, damped when several apply together.

        Using the max rather than the sum keeps one bad location from
        manufacturing a CRITICAL verdict on its own.
        """
        if not tags:
            return 40.0
        scores = sorted(
            (self.context_scores.get(t, 40.0) for t in tags), reverse=True
        )
        primary = scores[0]
        secondary_bonus = min(12.0, 4.0 * (len(scores) - 1))
        return min(100.0, primary + secondary_bonus)


DEFAULT_POLICY = PolicyConfig()
