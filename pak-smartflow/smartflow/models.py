"""Domain model for Pak-SmartFlow.

Everything is a frozen dataclass so state transitions produce new objects and
the audit trail stays trustworthy. All timestamps are timezone-aware UTC.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping, Sequence


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class ViolationType(str, Enum):
    RED_LIGHT = "RED_LIGHT"
    OVERSPEEDING = "OVERSPEEDING"
    WRONG_WAY = "WRONG_WAY"
    NO_HELMET = "NO_HELMET"
    NO_SEATBELT = "NO_SEATBELT"
    MOBILE_USE = "MOBILE_USE"
    LANE_VIOLATION = "LANE_VIOLATION"
    ILLEGAL_PARKING = "ILLEGAL_PARKING"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ChallanStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class EscalationStage(str, Enum):
    ISSUED = "ISSUED"
    REMINDER_1 = "REMINDER_1"
    REMINDER_2 = "REMINDER_2"
    FINAL_NOTICE = "FINAL_NOTICE"
    ENFORCEMENT_REQUEST = "ENFORCEMENT_REQUEST"
    AUTHORITY_REVIEW = "AUTHORITY_REVIEW"
    RESOLVED = "RESOLVED"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_AUTHORITY_APPROVAL = "PENDING_AUTHORITY_APPROVAL"
    APPROVED_BY_AUTHORITY = "APPROVED_BY_AUTHORITY"
    REJECTED_BY_AUTHORITY = "REJECTED_BY_AUTHORITY"
    WITHDRAWN_ON_PAYMENT = "WITHDRAWN_ON_PAYMENT"


class ComplianceTier(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class AgentMaturity(str, Enum):
    """How much real machinery sits behind an agent. Honesty by design."""

    DEEP = "deep"           # real algorithm, unit-tested
    HEURISTIC = "heuristic"  # deterministic rules over real inputs
    MOCK = "mock"           # synthetic data, integration seam only


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Perception layer
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FrameCapture:
    """One camera frame. Payload is raw bytes; only its digest is retained."""

    index: int
    captured_at: datetime
    payload: bytes
    camera_id: str = "CAM-UNKNOWN"

    @property
    def size_bytes(self) -> int:
        return len(self.payload)


@dataclass(frozen=True)
class CameraEvent:
    """What a single camera observed. Produced by the Detection agent."""

    camera_id: str
    location: str
    captured_at: datetime
    violations: tuple[ViolationType, ...]
    frames: tuple[FrameCapture, ...]
    speed_kmh: float | None = None
    speed_limit_kmh: float | None = None
    traffic_density: float = 40.0
    context_tags: tuple[str, ...] = ()
    event_id: str = field(default_factory=lambda: _uid("EVT"))

    @property
    def primary_violation(self) -> ViolationType:
        if not self.violations:
            raise ValueError("CameraEvent carries no violation")
        return self.violations[0]


@dataclass(frozen=True)
class VehicleIdentity:
    """Result of ANPR + registry resolution. Identifiers are pre-masked."""

    plate: str
    city: str
    vehicle_make: str
    owner_name_masked: str
    cnic_masked: str
    registered_owner_liable: bool = True
    anpr_confidence: float = 0.0
    registry_reference: str = "LOCAL-SEED"
    note: str = "Registered-owner liability. Driver biometrics not collected."

    @property
    def is_masked(self) -> bool:
        return "X" in self.cnic_masked


@dataclass(frozen=True)
class EvidenceBundle:
    """Tamper-evident evidence package (chain of custody)."""

    violation_id: str
    frames: tuple[FrameCapture, ...]
    frame_digests: tuple[str, ...]
    root_hash: str
    sealed_at: datetime
    hash_algorithm: str = "sha256"
    verified: bool = True
    note: str = "Frames hashed at capture; any edit breaks the root hash."

    @property
    def frame_count(self) -> int:
        return len(self.frames)


# --------------------------------------------------------------------------- #
# Decision layer
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RuleFiring:
    label: str
    strength: float
    consequent: str
    conditions: Mapping[str, str]


@dataclass(frozen=True)
class RiskAssessment:
    score: float
    level: RiskLevel
    inputs: Mapping[str, float]
    rule_firings: tuple[RuleFiring, ...]
    contributions: Mapping[str, float]
    weighted_baseline: float
    review_recommended: bool
    fallback_used: bool
    engine: str = "mamdani-trimf-pure-python"
    centroid_cog: float | None = None


@dataclass(frozen=True)
class Decision:
    """Output of the Fuzzy Decision agent: what to do, and why."""

    actions: tuple[str, ...]
    issue_challan: bool
    needs_human_review: bool
    rationale: str
    risk: RiskAssessment
    policy_version: str


# --------------------------------------------------------------------------- #
# Action layer
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Challan:
    challan_id: str
    event_id: str
    plate: str
    violation_type: ViolationType
    base_fine: float
    issued_at: datetime
    due_at: datetime
    risk_score: float
    risk_level: RiskLevel
    evidence_root_hash: str
    evidence_frame_count: int
    status: ChallanStatus
    explanation: str
    policy_version: str
    plate_hash: str = ""
    simulation: bool = True

    @property
    def is_overdue(self) -> bool:
        return utcnow() > self.due_at and self.status not in (
            ChallanStatus.PAID,
            ChallanStatus.CANCELLED,
            ChallanStatus.DISPUTED,
        )


@dataclass(frozen=True)
class Notice:
    stage: EscalationStage
    channel: str
    sent_at: datetime
    subject: str
    body_english: str
    body_roman_urdu: str
    body_urdu: str
    requires_human_approval: bool = False
    simulation: bool = True


@dataclass(frozen=True)
class PaymentRecord:
    payment_id: str
    challan_id: str
    amount: float
    paid_at: datetime
    method: str
    transaction_ref: str
    simulation: bool = True
    note: str = "Mock gateway. No real money moved."


@dataclass(frozen=True)
class PenaltyBreakdown:
    base_fine: float
    days_overdue: int
    applied_tranches: tuple[tuple[int, float], ...]
    late_fee: float
    subtotal: float
    cap_applied: bool
    total_payable: float
    early_payment_discount: float
    total_if_paid_today_early: float
    policy_version: str


# --------------------------------------------------------------------------- #
# Compliance layer
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ComplianceProfile:
    plate: str
    unpaid_count: int
    outstanding_amount: float
    oldest_unpaid_days: int
    notices_sent: int
    payment_attempts: int
    disputes_open: int
    challan_ids: tuple[str, ...]
    score: float
    tier: ComplianceTier
    reasons: tuple[str, ...]
    recommended_stage: EscalationStage
    policy_version: str


@dataclass(frozen=True)
class EnforcementRequest:
    """A *prepared* request. Never an executed action."""

    request_id: str
    plate: str
    challan_ids: tuple[str, ...]
    total_outstanding: float
    compliance_score: float
    compliance_tier: ComplianceTier
    created_at: datetime
    status: RequestStatus
    evidence_roots: tuple[str, ...]
    requested_measures: tuple[str, ...]
    required_approvals: tuple[str, ...]
    legal_disclaimer: str
    simulation: bool = True

    def assert_not_executable(self) -> None:
        if not self.simulation or self.status is RequestStatus.APPROVED_BY_AUTHORITY:
            raise AssertionError(
                "Prototype must never hold an executable enforcement request."
            )


# --------------------------------------------------------------------------- #
# Observability
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AgentTrace:
    run_id: str
    agent: str
    level: int
    maturity: AgentMaturity
    verdict: str
    details: Mapping[str, Any]
    duration_ms: float
    at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    scenario: str
    started_at: datetime
    finished_at: datetime
    decision: Decision
    identity: VehicleIdentity
    evidence: EvidenceBundle
    challan: Challan | None
    notices: tuple[Notice, ...]
    payments: tuple[PaymentRecord, ...]
    compliance: ComplianceProfile | None
    enforcement_request: EnforcementRequest | None
    optimisation_notes: tuple[str, ...]
    traces: tuple[AgentTrace, ...]
    history: tuple[Challan, ...] = ()
    compliance_at_escalation: ComplianceProfile | None = None

    @property
    def duration_ms(self) -> float:
        return (self.finished_at - self.started_at).total_seconds() * 1000.0


def days_between(later: datetime, earlier: datetime) -> int:
    """Whole days between two instants, never negative."""
    return max(0, (later - earlier).days)


def shift(base: datetime, **kwargs: float) -> datetime:
    return base + timedelta(**kwargs)
