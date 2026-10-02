"""Legal-boundary tests.

These are the most important tests in the repository. They assert that the
prototype *cannot* take an action against a citizen, rather than that it merely
chooses not to.
"""

from __future__ import annotations

import unittest

from smartflow.integrations import (
    MockNADRAVerifier,
    MockPaymentGateway,
    MockVehicleRegistry,
    NotificationGateway,
    mask_cnic,
    mask_name,
)
from smartflow.legal import (
    BLOCKED_CAPABILITIES,
    PRIVACY_DEFAULTS,
    SAFE_ALTERNATIVES,
    SAFE_STATEMENT,
    ProhibitedOperationError,
    assert_operation_allowed,
    enforcement_request_disclaimer,
)
from smartflow.messages import TEMPLATES
from smartflow.models import EscalationStage


class BlockedCapabilityTests(unittest.TestCase):
    def test_every_blocked_capability_raises(self) -> None:
        for capability in BLOCKED_CAPABILITIES:
            with self.assertRaises(ProhibitedOperationError, msg=capability):
                assert_operation_allowed(capability)

    def test_every_blocked_capability_has_a_safe_alternative(self) -> None:
        for capability in BLOCKED_CAPABILITIES:
            self.assertIn(capability, SAFE_ALTERNATIVES)
            self.assertTrue(SAFE_ALTERNATIVES[capability])

    def test_allowed_operations_pass_through(self) -> None:
        assert_operation_allowed("prepare_enforcement_request")
        assert_operation_allowed("send_reminder")

    def test_error_message_names_the_alternative(self) -> None:
        with self.assertRaises(ProhibitedOperationError) as ctx:
            assert_operation_allowed("block_real_cnic")
        self.assertIn("Safe alternative", str(ctx.exception))

    def test_driver_biometrics_are_blocked(self) -> None:
        self.assertIn("biometric_driver_identification", BLOCKED_CAPABILITIES)

    def test_privacy_defaults_exclude_biometrics(self) -> None:
        self.assertEqual(PRIVACY_DEFAULTS["driver_biometrics"], "not_collected")
        self.assertIsInstance(PRIVACY_DEFAULTS["evidence_retention_days"], int)


class SafeStatementTests(unittest.TestCase):
    def test_safe_statement_covers_the_key_conditions(self) -> None:
        for phrase in ("authorized government ecosystem", "applicable law", "approval"):
            self.assertIn(phrase, SAFE_STATEMENT)

    def test_disclaimer_says_it_has_no_legal_force(self) -> None:
        disclaimer = enforcement_request_disclaimer()
        self.assertIn("AUTHORITY REVIEW ONLY", disclaimer)
        self.assertIn("no legal force", disclaimer)
        self.assertIn("SIMULATED", disclaimer)


class MockNADRAGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nadra = MockNADRAVerifier()

    def test_service_block_always_fails(self) -> None:
        with self.assertRaises(ProhibitedOperationError):
            self.nadra.request_service_block("3520212345671", "unpaid challans")

    def test_bank_freeze_always_fails(self) -> None:
        with self.assertRaises(ProhibitedOperationError):
            self.nadra.freeze_bank_account("3520212345671")

    def test_sim_block_always_fails(self) -> None:
        with self.assertRaises(ProhibitedOperationError):
            self.nadra.block_sim("3520212345671")

    def test_biometric_driver_identification_always_fails(self) -> None:
        with self.assertRaises(ProhibitedOperationError):
            self.nadra.identify_driver_biometrically(b"\x00\x01")

    def test_verification_performs_no_network_calls(self) -> None:
        record = self.nadra.verify_owner("LEB-1234")
        self.assertEqual(self.nadra.network_calls, 0)
        self.assertEqual(record["network_calls"], 0)
        self.assertTrue(record["simulation"])
        self.assertEqual(record["verification_method"], "LOCAL_SEEDED_REGISTRY")

    def test_verification_returns_masked_identity_only(self) -> None:
        record = self.nadra.verify_owner("LEB-1234")
        self.assertIn("XXXXXXX", record["cnic_masked"])
        self.assertNotIn("3520212345671", str(record))

    def test_audit_entries_are_recorded(self) -> None:
        self.nadra.verify_owner("LEB-1234")
        self.assertEqual(len(self.nadra.audit), 1)


class MaskingTests(unittest.TestCase):
    def test_cnic_masks_the_middle(self) -> None:
        masked = mask_cnic("3520212345671")
        self.assertEqual(masked, "35202-XXXXXXX-1")
        self.assertNotIn("2123456", masked)

    def test_cnic_rejects_wrong_length(self) -> None:
        with self.assertRaises(ValueError):
            mask_cnic("12345")

    def test_name_is_initialled(self) -> None:
        self.assertEqual(mask_name("Ahmed Rahim"), "A. R.")
        self.assertEqual(mask_name("Ahmed"), "A.")

    def test_empty_name_is_handled(self) -> None:
        self.assertEqual(mask_name("   "), "X")

    def test_registry_never_returns_a_full_cnic(self) -> None:
        registry = MockVehicleRegistry()
        for plate in registry.plates():
            self.assertTrue(registry.resolve(plate).is_masked)


class GatewayGuardTests(unittest.TestCase):
    def test_payment_gateway_is_marked_simulation(self) -> None:
        gateway = MockPaymentGateway()
        self.assertEqual(gateway.network_calls, 0)
        self.assertEqual(gateway.ledger, [])

    def test_notification_gateway_is_marked_simulation(self) -> None:
        gateway = NotificationGateway()
        self.assertEqual(gateway.network_calls, 0)
        self.assertEqual(gateway.sent_count, 0)


class CitizenMessageTests(unittest.TestCase):
    def test_every_stage_has_three_languages(self) -> None:
        for stage, template in TEMPLATES.items():
            for language in ("en", "rm", "ur"):
                self.assertIn(language, template, stage)
                self.assertTrue(template[language].strip(), stage)

    def test_enforcement_notice_states_no_restriction_was_applied(self) -> None:
        template = TEMPLATES[EscalationStage.ENFORCEMENT_REQUEST]
        self.assertIn("no", template["en"].lower())
        self.assertIn("suspended", template["en"].lower())
        self.assertIn("پابندی", template["ur"])

    def test_urdu_script_is_actually_urdu(self) -> None:
        for stage, template in TEMPLATES.items():
            self.assertTrue(
                any("\u0600" <= char <= "\u06ff" for char in template["ur"]),
                f"{stage} Urdu body contains no Arabic-script characters",
            )

    def test_citizen_rights_are_repeated_in_every_notice(self) -> None:
        for stage, template in TEMPLATES.items():
            if stage is EscalationStage.RESOLVED:
                continue
            roman = template["rm"].lower()
            self.assertIn("saboot", roman, stage)
            self.assertTrue(
                "challenge" in roman or "aitraaz" in roman,
                f"{stage} Roman Urdu notice does not state the right to contest",
            )
            self.assertIn("dispute", template["en"].lower(), stage)


if __name__ == "__main__":
    unittest.main()
