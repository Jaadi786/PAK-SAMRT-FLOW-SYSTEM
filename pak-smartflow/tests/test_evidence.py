"""Evidence chain-of-custody tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from smartflow.evidence import (
    compute_root_hash,
    cross_frame_agreement,
    hash_payload,
    hash_plate,
    seal_evidence,
    tamper_demo,
    verify_bundle,
)
from smartflow.models import FrameCapture, ViolationType

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def frames(count: int = 4, witnesses: int = 4, violation: str = "RED_LIGHT") -> tuple[FrameCapture, ...]:
    out = []
    for index in range(count):
        header = f"VF:{violation}:{1 if index < witnesses else 0}".encode()
        out.append(
            FrameCapture(
                index=index,
                captured_at=NOW + timedelta(milliseconds=250 * index),
                payload=header + b"|" + bytes([index] * 64),
                camera_id="CAM-TEST",
            )
        )
    return tuple(out)


class SealAndVerifyTests(unittest.TestCase):
    def test_sealed_bundle_verifies(self) -> None:
        bundle = seal_evidence("CASE-1", frames())
        self.assertTrue(verify_bundle(bundle))
        self.assertEqual(bundle.frame_count, 4)
        self.assertEqual(len(bundle.frame_digests), 4)

    def test_seal_is_deterministic(self) -> None:
        first = seal_evidence("CASE-1", frames())
        second = seal_evidence("CASE-1", frames())
        self.assertEqual(first.root_hash, second.root_hash)

    def test_case_id_is_bound_into_the_root_hash(self) -> None:
        self.assertNotEqual(
            compute_root_hash(frames(), "CASE-1"),
            compute_root_hash(frames(), "CASE-2"),
        )

    def test_frame_order_does_not_change_the_root_hash(self) -> None:
        ordered = frames()
        shuffled = (ordered[2], ordered[0], ordered[3], ordered[1])
        self.assertEqual(
            compute_root_hash(ordered, "CASE-1"),
            compute_root_hash(shuffled, "CASE-1"),
        )

    def test_tampering_is_detected(self) -> None:
        bundle = seal_evidence("CASE-1", frames())
        self.assertFalse(verify_bundle(tamper_demo(bundle, frame_index=2)))

    def test_removing_a_frame_is_detected(self) -> None:
        bundle = seal_evidence("CASE-1", frames())
        truncated = type(bundle)(
            violation_id=bundle.violation_id,
            frames=bundle.frames[:-1],
            frame_digests=bundle.frame_digests,
            root_hash=bundle.root_hash,
            sealed_at=bundle.sealed_at,
        )
        self.assertFalse(verify_bundle(truncated))

    def test_empty_bundle_rejected(self) -> None:
        with self.assertRaises(ValueError):
            seal_evidence("CASE-1", ())

    def test_duplicate_frame_indices_rejected(self) -> None:
        first = frames()[0]
        with self.assertRaises(ValueError):
            seal_evidence("CASE-1", (first, first))


class ConfidenceTests(unittest.TestCase):
    def test_full_agreement_gives_top_confidence(self) -> None:
        self.assertGreaterEqual(
            cross_frame_agreement(frames(4, 4), "RED_LIGHT"), 99.0
        )

    def test_partial_agreement_reduces_confidence(self) -> None:
        weak = cross_frame_agreement(frames(3, 1), "RED_LIGHT")
        strong = cross_frame_agreement(frames(3, 3), "RED_LIGHT")
        self.assertLess(weak, strong)

    def test_no_agreement_is_low(self) -> None:
        self.assertLess(cross_frame_agreement(frames(3, 0), "RED_LIGHT"), 20.0)

    def test_mismatched_violation_type_does_not_witness(self) -> None:
        self.assertLess(
            cross_frame_agreement(frames(3, 3), "OVERSPEEDING"), 20.0
        )

    def test_confidence_is_bounded(self) -> None:
        for count in range(1, 9):
            value = cross_frame_agreement(frames(count, count), "RED_LIGHT")
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 100.0)


class PrivacyTests(unittest.TestCase):
    def test_plate_hash_is_salted_and_stable(self) -> None:
        a = hash_plate("LEB-1234", "salt-a")
        b = hash_plate("LEB-1234", "salt-a")
        c = hash_plate("LEB-1234", "salt-b")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_plate_hash_hides_the_plate(self) -> None:
        digest = hash_plate("LEB-1234")
        self.assertNotIn("LEB", digest)
        self.assertEqual(len(digest), 16)

    def test_payload_hash_is_sha256(self) -> None:
        self.assertEqual(len(hash_payload(b"hello")), 64)


if __name__ == "__main__":
    unittest.main()
