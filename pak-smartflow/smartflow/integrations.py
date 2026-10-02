"""Mock integrations: registry, NADRA, payments, notifications, LLM.

Every external system here is a sealed simulation. The pattern is the same for
each one:

* it performs **zero** network I/O (a counter proves it, and a test asserts it),
* it returns **masked** identifiers,
* and it exposes the prohibited real-world action as a method that always
  raises :class:`~smartflow.legal.ProhibitedOperationError`.

That last point matters. Instead of claiming "we would never block a CNIC",
the codebase ships ``request_service_block`` which cannot succeed. A reviewer
can run it and watch it fail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Mapping, Sequence

from .config import DEFAULT_POLICY, PolicyConfig
from .legal import SIMULATION_BANNER, ProhibitedOperationError, assert_operation_allowed
from .messages import render_notice
from .models import (
    Challan,
    ChallanStatus,
    EscalationStage,
    PaymentRecord,
    VehicleIdentity,
    utcnow,
)


# --------------------------------------------------------------------------- #
# Masking
# --------------------------------------------------------------------------- #
def mask_cnic(raw: str) -> str:
    """Mask all but the first five and last digit of a 13-digit CNIC."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 13:
        raise ValueError("CNIC must contain exactly 13 digits")
    return f"{digits[:5]}-XXXXXXX-{digits[-1]}"


def mask_name(full_name: str) -> str:
    parts = [p for p in full_name.split() if p]
    if not parts:
        return "X"
    initialled = [p if len(p) <= 2 else f"{p[0]}." for p in parts]
    return " ".join(initialled)


# --------------------------------------------------------------------------- #
# Seeded local vehicle registry (replaces a real registration lookup)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SeededVehicle:
    plate: str
    city: str
    make: str
    owner_full_name: str
    cnic: str


SEED_VEHICLES: tuple[SeededVehicle, ...] = (
    SeededVehicle("LEB-1234", "Lahore", "Suzuki Alto 2021", "Ahmed Rahim", "3520212345671"),
    SeededVehicle("LEB-7788", "Lahore", "Honda CD-70 2019", "Bilal Nasir", "3520198765432"),
    SeededVehicle("KHI-4471", "Karachi", "Toyota Corolla 2018", "Sana Fatima", "4210187654321"),
    SeededVehicle("ISB-2210", "Islamabad", "Honda Civic 2022", "Usman Tariq", "6110154321098"),
    SeededVehicle("RWP-9087", "Rawalpindi", "Suzuki Bolan 2016", "Hina Kausar", "3740523456789"),
    SeededVehicle("MUX-3312", "Multan", "United Bravo 2020", "Imran Shah", "3630298765431"),
    SeededVehicle("PSH-6650", "Peshawar", "Toyota Hilux 2015", "Zafar Ali", "1730111222333"),
    SeededVehicle("FSD-1198", "Faisalabad", "Suzuki Every 2017", "Nadia Aslam", "3310144556677"),
)

AMBULANCE_PLATE = "AMB-0007"


class MockVehicleRegistry:
    """Local, seeded, offline stand-in for the vehicle registration authority."""

    def __init__(self, vehicles: Sequence[SeededVehicle] = SEED_VEHICLES) -> None:
        self._by_plate = {v.plate.upper(): v for v in vehicles}
        self.lookups = 0

    def plates(self) -> tuple[str, ...]:
        return tuple(self._by_plate)

    def resolve(self, plate: str) -> VehicleIdentity:
        self.lookups += 1
        key = plate.upper().strip()
        vehicle = self._by_plate.get(key)
        if vehicle is None:
            # Unknown plate: still return a masked, explicitly-unverified record
            # rather than inventing an identity.
            return VehicleIdentity(
                plate=key,
                city="UNKNOWN",
                vehicle_make="UNRESOLVED",
                owner_name_masked="not on file",
                cnic_masked="XXXXX-XXXXXXX-X",
                registered_owner_liable=False,
                anpr_confidence=55.0,
                registry_reference="LOCAL-SEED:MISS",
                note="Plate not present in the seeded registry; no owner asserted.",
            )
        return VehicleIdentity(
            plate=vehicle.plate,
            city=vehicle.city,
            vehicle_make=vehicle.make,
            owner_name_masked=mask_name(vehicle.owner_full_name),
            cnic_masked=mask_cnic(vehicle.cnic),
            registered_owner_liable=True,
            anpr_confidence=96.5,
            registry_reference=f"LOCAL-SEED:{vehicle.plate}",
        )


# --------------------------------------------------------------------------- #
# Mock NADRA verifier
# --------------------------------------------------------------------------- #
class MockNADRAVerifier:
    """Simulated identity verification. Never touches a real NADRA service."""

    SIMULATION = True

    def __init__(self, registry: MockVehicleRegistry | None = None) -> None:
        self.registry = registry or MockVehicleRegistry()
        self.network_calls = 0
        self.audit: list[dict[str, Any]] = []

    def verify_owner(self, plate: str, requested_by: str = "system") -> Mapping[str, Any]:
        """Return an already-masked owner record from local seeded data."""
        identity = self.registry.resolve(plate)
        record = {
            "simulation": True,
            "banner": SIMULATION_BANNER,
            "plate": identity.plate,
            "cnic_masked": identity.cnic_masked,
            "owner_name_masked": identity.owner_name_masked,
            "registry_reference": identity.registry_reference,
            "verification_method": "LOCAL_SEEDED_REGISTRY",
            "network_calls": self.network_calls,
            "requested_by": requested_by,
            "note": (
                "Simulated verification for demonstration. Driver biometrics are "
                "not collected; liability follows the registered owner."
            ),
        }
        self.audit.append({"plate": identity.plate, "at": utcnow().isoformat()})
        return record

    # Prohibited operations, shipped as always-failing seams ----------------- #
    def request_service_block(self, cnic: str, reason: str) -> None:
        """Deliberately impossible. Kept as a named seam so the boundary is visible."""
        assert_operation_allowed("block_real_cnic")
        raise ProhibitedOperationError("unreachable")  # pragma: no cover

    def freeze_bank_account(self, cnic: str) -> None:
        assert_operation_allowed("freeze_bank_account")
        raise ProhibitedOperationError("unreachable")  # pragma: no cover

    def block_sim(self, cnic: str) -> None:
        assert_operation_allowed("block_sim")
        raise ProhibitedOperationError("unreachable")  # pragma: no cover

    def identify_driver_biometrically(self, face_image: bytes) -> None:
        assert_operation_allowed("biometric_driver_identification")
        raise ProhibitedOperationError("unreachable")  # pragma: no cover


# --------------------------------------------------------------------------- #
# Mock payment gateway
# --------------------------------------------------------------------------- #
class MockPaymentGateway:
    """In-process ledger. Records transactions; moves no real money."""

    METHODS = ("JazzCash (mock)", "Easypaisa (mock)", "Bank transfer (mock)", "Card (mock)")

    def __init__(self) -> None:
        self.ledger: list[PaymentRecord] = []
        self.network_calls = 0

    def quote(
        self,
        challan: Challan,
        config: PolicyConfig | None = None,
        as_of: datetime | None = None,
    ) -> Mapping[str, Any]:
        from .penalty import compute_penalty, payment_plan

        policy = config or DEFAULT_POLICY
        at = as_of or utcnow()
        breakdown = compute_penalty(
            challan.base_fine, challan.issued_at, at, policy_config=policy
        )
        return {
            "challan_id": challan.challan_id,
            "base_fine": breakdown.base_fine,
            "total_payable": breakdown.total_payable,
            "late_fee": breakdown.late_fee,
            "days_overdue": breakdown.days_overdue,
            "early_payment_discount": breakdown.early_payment_discount,
            "total_if_paid_today_early": breakdown.total_if_paid_today_early,
            "instalments": payment_plan(breakdown.total_payable, policy.penalty),
            "simulation": True,
        }

    def pay(
        self,
        challan: Challan,
        amount: float | None = None,
        method: str | None = None,
        paid_at: datetime | None = None,
        config: PolicyConfig | None = None,
        as_of: datetime | None = None,
    ) -> tuple[PaymentRecord, Challan]:
        """Settle a challan (fully or partially) against the mock ledger."""
        policy = config or DEFAULT_POLICY
        quote = self.quote(challan, policy, as_of=as_of or paid_at)
        due = float(quote["total_payable"])
        if amount is None:
            amount = float(quote["total_if_paid_today_early"] or due)
        if amount <= 0:
            raise ValueError("payment amount must be positive")
        if amount > due + 0.01:
            raise ValueError(f"payment {amount} exceeds outstanding {due}")

        # An early-payment discount is a policy write-off, not a partial payment:
        # settling the discounted total closes the case instead of leaving a
        # residue that would keep the citizen in the escalation ladder.
        settle_threshold = min(
            due, float(quote["total_if_paid_today_early"] or due)
        )

        at = paid_at or utcnow()
        reference = f"MOCK-{at:%Y%m%d%H%M%S}-{challan.challan_id[-4:]}"
        record = PaymentRecord(
            payment_id=f"PAY-{reference}",
            challan_id=challan.challan_id,
            amount=round(amount, 2),
            paid_at=at,
            method=method or self.METHODS[0],
            transaction_ref=reference,
        )
        self.ledger.append(record)

        if amount >= settle_threshold - 0.01:
            status = ChallanStatus.PAID
        elif amount > 0:
            status = ChallanStatus.PARTIALLY_PAID
        else:  # pragma: no cover - guarded above
            status = challan.status
        return record, replace(challan, status=status)


# --------------------------------------------------------------------------- #
# Notification gateway
# --------------------------------------------------------------------------- #
class NotificationGateway:
    """Renders and 'sends' citizen notices. Writes to an outbox, not a network."""

    def __init__(self) -> None:
        self.outbox: list[Any] = []
        self.network_calls = 0
        self.by_stage: dict[str, int] = {}

    def send(
        self,
        stage: EscalationStage,
        challan: Challan,
        context: Mapping[str, Any] | None = None,
        channel: str | None = None,
        sent_at: datetime | None = None,
        requires_human_approval: bool = False,
        config: PolicyConfig | None = None,
    ) -> Any:
        policy = config or DEFAULT_POLICY
        stage_policy = policy.escalation.stage_policy(stage)
        values = {
            "challan_id": challan.challan_id,
            "plate": challan.plate,
            "violation": challan.violation_type.value.replace("_", " ").title(),
            "amount": f"{challan.base_fine:,.0f}",
            "due_at": challan.due_at.date().isoformat(),
            "due_date": challan.due_at.date().isoformat(),
            "instalments": str(policy.penalty.payment_plan_instalments),
            "evidence_root": challan.evidence_root_hash[:16],
            "policy_version": challan.policy_version,
            "simulation": True,
            **(context or {}),
        }
        notice = render_notice(
            stage=stage,
            context=values,
            channel=channel or stage_policy.channel,
            sent_at=sent_at or utcnow(),
            requires_human_approval=requires_human_approval or stage_policy.requires_human_approval,
        )
        self.outbox.append(notice)
        self.by_stage[stage.value] = self.by_stage.get(stage.value, 0) + 1
        return notice

    @property
    def sent_count(self) -> int:
        return len(self.outbox)


# --------------------------------------------------------------------------- #
# Explanation writer (templates first, LLM optional)
# --------------------------------------------------------------------------- #
class TemplateExplanationWriter:
    """Deterministic, offline explanation text. Always available."""

    name = "template"

    def decision_explanation(
        self,
        plate: str,
        violation: str,
        risk_score: float,
        risk_level: str,
        top_factors: Sequence[tuple[str, float]],
        actions: Sequence[str],
        labels: Mapping[str, str] | None = None,
    ) -> str:
        labels = labels or {}
        factor_text = "; ".join(
            f"{labels.get(name, name)} {share:.0f}%" for name, share in top_factors
        )
        action_text = ", ".join(a.replace("_", " ").lower() for a in actions)
        return (
            f"Vehicle {plate} was flagged for {violation}. The fuzzy risk engine scored "
            f"{risk_score:.1f}/100 ({risk_level}). The decision was driven mainly by "
            f"{factor_text}. Actions taken: {action_text}. "
            f"This is a recommendation produced by an automated system; a human officer "
            f"can override it, and the citizen can dispute it."
        )

    def notice_summary(self, stage: str, plate: str, amount: float) -> str:
        return (
            f"Stage {stage} for {plate}; outstanding {amount:,.0f} PKR. "
            f"Delivered in English, Roman Urdu and Urdu script."
        )


class GroqExplanationWriter:
    """Optional LLM polish. Falls back to templates if unavailable.

    Network access is never required: :meth:`available` probes for the package
    and an API key, and the caller must handle a ``None`` return.
    """

    name = "groq"
    model = "llama-3.1-8b-instant"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        import os

        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.model = model or self.model
        self._client = None

    def available(self) -> bool:
        if not self.api_key:
            return False
        try:  # pragma: no cover - depends on optional install
            import groq  # noqa: F401
        except ImportError:
            return False
        return True

    def complete(self, prompt: str) -> str | None:  # pragma: no cover - network path
        if not self.available():
            return None
        try:
            from groq import Groq

            if self._client is None:
                self._client = Groq(api_key=self.api_key)
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=400,
            )
            return response.choices[0].message.content
        except Exception:
            return None


def get_explanation_writer(prefer_llm: bool = False) -> Any:
    """Return an LLM writer when explicitly requested and available, else templates."""
    if prefer_llm:
        llm = GroqExplanationWriter()
        if llm.available():
            return llm
    return TemplateExplanationWriter()
