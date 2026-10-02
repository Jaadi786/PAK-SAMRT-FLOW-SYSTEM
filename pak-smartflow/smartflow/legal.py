"""Legal guardrails for Pak-SmartFlow.

This module is the single source of truth for what this prototype will and will
not do. Every legal claim the demo makes is enforced *in code*, not just in a
slide -- so if a judge asks "could this system take a real action against a
citizen?", the answer is a type error, not a promise.

Design rule
-----------
Pak-SmartFlow is a *decision-support and workflow-coordination* prototype.
It prepares, explains and queues recommendations. It never executes an
enforcement action. Execution belongs to an authorised authority, acting under
applicable law, policy and human approval.
"""

from __future__ import annotations


class ProhibitedOperationError(RuntimeError):
    """Raised when code attempts an action this prototype must never perform."""


#: Shown on every simulated external interaction (console + UI + API payloads).
SIMULATION_BANNER = "*** SIMULATED -- NO REAL GOVERNMENT SYSTEM IS CONTACTED ***"

#: The exact sentence to say, verbatim, whenever a judge asks about scope.
SAFE_STATEMENT = (
    "Our prototype demonstrates how an authorized government ecosystem could "
    "technically coordinate these workflows, subject to applicable law, policy, "
    "security, and human/authority approval."
)

#: Capabilities we deliberately do NOT implement. Kept as a data structure so
#: the test suite and the UI can assert that they stay absent.
BLOCKED_CAPABILITIES: tuple[str, ...] = (
    "block_real_cnic",
    "block_real_passport",
    "freeze_bank_account",
    "block_sim",
    "auto_deduct_funds",
    "biometric_driver_identification",
    "real_nadra_lookup",
    "real_vehicle_registration_lookup",
    "publish_citizen_data",
)

#: What we do instead of each blocked capability. Used to build the UI/PPT
#: mapping table automatically so documentation cannot drift from code.
SAFE_ALTERNATIVES: dict[str, str] = {
    "block_real_cnic": "Prepare an Enforcement Request for authority review",
    "block_real_passport": "Prepare an Enforcement Request for authority review",
    "freeze_bank_account": "Offer a payment plan in the mock payment gateway",
    "block_sim": "Send a compliance reminder over a stub notification channel",
    "auto_deduct_funds": "Mock transaction only; citizen initiates payment",
    "biometric_driver_identification": (
        "Registered-owner liability only; driver biometrics deliberately excluded"
    ),
    "real_nadra_lookup": "Mock NADRA verifier returning already-masked identifiers",
    "real_vehicle_registration_lookup": "Seeded in-memory local registry, no external lookup",
    "publish_citizen_data": "Masked identifiers and access-scoped audit trail",
}

#: Data-protection defaults, surfaced in the UI so the story is consistent.
PRIVACY_DEFAULTS: dict[str, object] = {
    "evidence_retention_days": 30,
    "raw_image_retention_days": 7,
    "plate_storage": "hashed_for_analytics, plaintext_only_for_active_case",
    "driver_biometrics": "not_collected",
    "citizen_access": "right to view own evidence bundle and appeal",
    "audit_trail": "append-only, every state change attributed to an actor",
}


def assert_operation_allowed(operation: str) -> None:
    """Fail loudly if *operation* is on the prohibited list.

    Call this at the top of any adapter that could plausibly be pointed at a
    real system. It converts an accidental integration into an immediate,
    obvious crash during development rather than a silent liability.
    """
    if operation in BLOCKED_CAPABILITIES:
        raise ProhibitedOperationError(
            f"'{operation}' is permanently disabled in this prototype. "
            f"Safe alternative: {SAFE_ALTERNATIVES.get(operation, 'none defined')}."
        )


def enforcement_request_disclaimer() -> str:
    """Standard footer for any generated enforcement paperwork."""
    return (
        "DRAFT FOR AUTHORITY REVIEW ONLY. This document carries no legal force. "
        "No citizen right, entitlement or service has been, or will be, "
        "suspended by this prototype. " + SIMULATION_BANNER
    )
