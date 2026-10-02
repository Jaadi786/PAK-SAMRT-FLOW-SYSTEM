"""Persistence and audit-trail tests."""

from __future__ import annotations

import sqlite3
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from smartflow.db import Store
from smartflow.models import (
    Challan,
    ChallanStatus,
    PaymentRecord,
    RiskLevel,
    ViolationType,
)

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def make_challan(challan_id: str = "CH-TEST-1") -> Challan:
    return Challan(
        challan_id=challan_id,
        event_id="EVT-1",
        plate="LEB-1234",
        violation_type=ViolationType.RED_LIGHT,
        base_fine=1000.0,
        issued_at=NOW,
        due_at=NOW,
        risk_score=83.2,
        risk_level=RiskLevel.HIGH,
        evidence_root_hash="root-abc",
        evidence_frame_count=4,
        status=ChallanStatus.ISSUED,
        explanation="test",
        policy_version="v-test",
        plate_hash="platehash",
    )


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = Store(":memory:")

    def tearDown(self) -> None:
        self.store.close()

    def test_challan_round_trip(self) -> None:
        self.store.save_challan(make_challan())
        rows = self.store.list_challans(plate="LEB-1234")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["challan_id"], "CH-TEST-1")
        self.assertEqual(rows[0]["status"], "ISSUED")
        self.assertEqual(rows[0]["base_fine"], 1000.0)

    def test_upsert_does_not_duplicate(self) -> None:
        self.store.save_challan(make_challan())
        self.store.save_challan(make_challan())
        self.assertEqual(len(self.store.list_challans()), 1)

    def test_status_update(self) -> None:
        self.store.save_challan(make_challan())
        self.store.update_challan_status("CH-TEST-1", "PAID")
        self.assertEqual(self.store.list_challans()[0]["status"], "PAID")

    def test_filter_by_status(self) -> None:
        self.store.save_challan(make_challan("CH-1"))
        self.store.save_challan(make_challan("CH-2"))
        self.store.update_challan_status("CH-2", "PAID")
        self.assertEqual(len(self.store.list_challans(status="PAID")), 1)
        self.assertEqual(len(self.store.list_challans(status="ISSUED")), 1)

    def test_audit_trail_is_chronological(self) -> None:
        self.store.log_event("CHALLAN_ISSUED", "agent-7", challan_id="CH-TEST-1", at=NOW)
        self.store.log_event("PAYMENT_RECEIVED", "agent-12", challan_id="CH-TEST-1", at=NOW)
        trail = self.store.audit_trail("CH-TEST-1")
        self.assertEqual([e["kind"] for e in trail], ["CHALLAN_ISSUED", "PAYMENT_RECEIVED"])
        self.assertEqual([e["actor"] for e in trail], ["agent-7", "agent-12"])

    def test_events_payload_is_json(self) -> None:
        import json

        self.store.log_event(
            "DECISION", "agent-6", challan_id="CH-TEST-1", payload={"score": 83.2}, at=NOW
        )
        row = self.store.conn.execute(
            "SELECT payload FROM case_events WHERE kind='DECISION'"
        ).fetchone()
        self.assertEqual(json.loads(row["payload"]), {"score": 83.2})

    def test_payment_persistence(self) -> None:
        self.store.save_payment(
            PaymentRecord(
                payment_id="PAY-1",
                challan_id="CH-TEST-1",
                amount=1100.0,
                paid_at=NOW,
                method="JazzCash (mock)",
                transaction_ref="MOCK-1",
            )
        )
        rows = self.store.payments_for("CH-TEST-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["amount"], 1100.0)

    def test_stats_are_reported(self) -> None:
        self.store.save_challan(make_challan("CH-1"))
        self.store.save_challan(replace(make_challan("CH-2"), status=ChallanStatus.PAID))
        stats = self.store.stats()
        self.assertEqual(stats["challans"], 2)
        self.assertEqual(stats["by_status"]["PAID"], 1)
        self.assertEqual(stats["outstanding_amount"], 1000.0)

    def test_reset_clears_everything(self) -> None:
        self.store.save_challan(make_challan())
        self.store.log_event("X", "y", at=NOW)
        self.store.reset()
        stats = self.store.stats()
        self.assertEqual(stats["challans"], 0)
        self.assertEqual(stats["events"], 0)

    def test_run_lifecycle(self) -> None:
        self.store.start_run("RUN-1", "unit", NOW)
        self.store.finish_run("RUN-1", NOW, {"ok": True})
        row = self.store.conn.execute("SELECT * FROM runs WHERE run_id='RUN-1'").fetchone()
        self.assertEqual(row["scenario"], "unit")
        self.assertIsNotNone(row["payload"])

    def test_context_manager_closes(self) -> None:
        with Store(":memory:") as store:
            store.save_challan(make_challan())
        with self.assertRaises(Exception):
            store.conn.execute("SELECT 1")


class FileBackedStoreTests(unittest.TestCase):
    """Uses a scratch directory inside the repository.

    ``tempfile`` is avoided on purpose: under a sandboxed runtime the system
    temp directory can be read-only, which turns a passing database test into a
    permission error that has nothing to do with the code under test.
    """

    ROOT = Path(__file__).resolve().parent / "_tmp_store"

    def setUp(self) -> None:
        self.ROOT.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        for path in sorted(self.ROOT.rglob("*"), reverse=True):
            try:
                path.unlink() if path.is_file() else path.rmdir()
            except OSError:
                pass
        try:
            self.ROOT.rmdir()
        except OSError:
            pass

    def test_data_survives_reopening(self) -> None:
        path = self.ROOT / "smartflow.sqlite"
        first = Store(path)
        first.save_challan(make_challan())
        first.log_event("CHALLAN_ISSUED", "agent-7", challan_id="CH-TEST-1", at=NOW)
        first.close()

        second = Store(path)
        try:
            self.assertEqual(len(second.list_challans()), 1)
            self.assertEqual(len(second.audit_trail("CH-TEST-1")), 1)
        finally:
            second.close()

    def test_schema_is_created_for_a_new_file(self) -> None:
        path = self.ROOT / "nested" / "dir" / "smartflow.sqlite"
        store = Store(path)
        try:
            self.assertTrue(path.exists())
            self.assertEqual(store.stats()["challans"], 0)
        finally:
            store.close()


class ThreadSafetyTests(unittest.TestCase):
    """A default sqlite3 connection is bound to its creating thread.

    Hosted runtimes -- Streamlit Community Cloud above all -- execute every
    script rerun on a different worker thread, so a store shared through
    ``st.cache_resource`` raises ``ProgrammingError`` on the second
    interaction unless it is explicitly made thread-safe. This test is the
    reason ``Store`` takes ``check_same_thread`` and holds a lock.
    """

    def test_default_connection_refuses_another_thread(self) -> None:
        store = Store(":memory:")
        try:
            errors: list[Exception] = []

            def use() -> None:
                try:
                    store.save_challan(make_challan())
                except Exception as exc:  # noqa: BLE001 - asserted on below
                    errors.append(exc)

            thread = threading.Thread(target=use)
            thread.start()
            thread.join()
            self.assertTrue(errors, "expected a cross-thread ProgrammingError")
            self.assertIsInstance(errors[0], sqlite3.ProgrammingError)
        finally:
            store.close()

    def test_shared_connection_works_across_threads(self) -> None:
        store = Store(":memory:", check_same_thread=False)
        try:
            errors: list[Exception] = []

            def writer(index: int) -> None:
                try:
                    store.save_challan(make_challan(f"CH-T{index}"))
                    store.log_event("WRITE", f"thread-{index}", at=NOW)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(12)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            self.assertEqual(len(store.list_challans()), 12)
            self.assertEqual(store.stats()["events"], 12)
        finally:
            store.close()

    def test_concurrent_reads_and_writes_do_not_corrupt(self) -> None:
        store = Store(":memory:", check_same_thread=False)
        try:
            errors: list[Exception] = []

            def chaos(index: int) -> None:
                try:
                    for _ in range(15):
                        store.save_challan(make_challan(f"CH-C{index}"))
                        store.list_challans()
                        store.stats()
                        store.audit_trail(f"CH-C{index}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=chaos, args=(i,)) for i in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(errors, [])
            self.assertEqual(len(store.list_challans()), 8)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
