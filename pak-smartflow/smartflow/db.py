"""SQLite persistence with an append-only case audit trail.

Every state change is written as an event row with an actor, so the demo can
show a reviewer a complete, chronological case file: who did what, when, and
on the basis of which evidence root hash.

Thread safety
-------------
This store is safe to share across threads. That is not a nicety: hosted
runtimes such as Streamlit Community Cloud execute every script rerun on a
*different* worker thread, so a default ``sqlite3`` connection (which is bound
to its creating thread) raises ``ProgrammingError`` on the second interaction.
Two things make it safe:

* ``check_same_thread=False``, so the connection may cross threads, and
* an ``RLock`` serialising every statement, so writes cannot interleave.

The lock also protects reads, because a read interleaved with a write on the
same connection can otherwise observe a partially applied statement.

The store is intentionally small. A production deployment would swap this for
PostgreSQL plus an immutable log; the interface is the same.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import (
    AgentTrace,
    Challan,
    EnforcementRequest,
    PaymentRecord,
    utcnow,
)
from .util import jsonable

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    scenario     TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    payload      TEXT
);
CREATE TABLE IF NOT EXISTS challans (
    challan_id     TEXT PRIMARY KEY,
    event_id       TEXT,
    plate          TEXT NOT NULL,
    plate_hash     TEXT,
    violation_type TEXT NOT NULL,
    base_fine      REAL NOT NULL,
    issued_at      TEXT NOT NULL,
    due_at         TEXT NOT NULL,
    risk_score     REAL,
    risk_level     TEXT,
    evidence_root  TEXT,
    status         TEXT NOT NULL,
    policy_version TEXT,
    simulation     INTEGER DEFAULT 1,
    payload        TEXT
);
CREATE INDEX IF NOT EXISTS idx_challans_plate ON challans(plate);
CREATE INDEX IF NOT EXISTS idx_challans_status ON challans(status);
CREATE TABLE IF NOT EXISTS case_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    challan_id TEXT,
    plate      TEXT,
    at         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    actor      TEXT NOT NULL,
    detail     TEXT,
    payload    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_challan ON case_events(challan_id);
CREATE TABLE IF NOT EXISTS payments (
    payment_id   TEXT PRIMARY KEY,
    challan_id   TEXT NOT NULL,
    amount       REAL NOT NULL,
    paid_at      TEXT NOT NULL,
    method       TEXT,
    transaction_ref TEXT,
    simulation   INTEGER DEFAULT 1,
    payload      TEXT
);
CREATE TABLE IF NOT EXISTS enforcement_requests (
    request_id     TEXT PRIMARY KEY,
    plate          TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    status         TEXT NOT NULL,
    total_outstanding REAL,
    compliance_score  REAL,
    payload        TEXT
);
CREATE TABLE IF NOT EXISTS agent_traces (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    agent      TEXT NOT NULL,
    level      INTEGER,
    maturity   TEXT,
    verdict    TEXT,
    duration_ms REAL,
    at         TEXT NOT NULL,
    payload    TEXT
);
CREATE INDEX IF NOT EXISTS idx_traces_run ON agent_traces(run_id);
CREATE TABLE IF NOT EXISTS compliance_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    plate      TEXT NOT NULL,
    at         TEXT NOT NULL,
    score      REAL,
    tier       TEXT,
    stage      TEXT,
    payload    TEXT
);
"""


def _dump(obj: Any) -> str:
    return json.dumps(jsonable(obj), sort_keys=True)


class Store:
    """Thread-safe SQLite wrapper. Use ``":memory:"`` for throwaway runs.

    Parameters
    ----------
    path:
        Database file, or ``":memory:"`` for an ephemeral store.
    check_same_thread:
        Set ``False`` when the store will be shared across threads, as any
        hosted runtime (Streamlit, FastAPI with a threadpool) will do. Kept
        ``True`` by default so a genuine threading mistake in single-threaded
        code still raises loudly.
    """

    def __init__(self, path: str | Path = ":memory:", check_same_thread: bool = True) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        if self.path not in (":memory:", "") and not self.path.startswith("file:"):
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=check_same_thread)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # -- internals ------------------------------------------------------- #
    def _exec(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._lock:
            self.conn.execute(sql, params)
            self.conn.commit()

    def _exec_many(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        with self._lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cursor = self.conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def _scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        with self._lock:
            row = self.conn.execute(sql, params).fetchone()
            return None if row is None else row[0]

    # -- lifecycle ------------------------------------------------------- #
    def close(self) -> None:
        with self._lock:
            self.conn.commit()
            self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def reset(self) -> None:
        with self._lock:
            for table in (
                "runs",
                "challans",
                "case_events",
                "payments",
                "enforcement_requests",
                "agent_traces",
                "compliance_snapshots",
            ):
                self.conn.execute(f"DELETE FROM {table}")
            self.conn.commit()

    # -- writes ---------------------------------------------------------- #
    def start_run(self, run_id: str, scenario: str, started_at: datetime) -> None:
        self._exec(
            "INSERT OR REPLACE INTO runs(run_id, scenario, started_at) VALUES (?,?,?)",
            (run_id, scenario, started_at.isoformat()),
        )

    def finish_run(self, run_id: str, finished_at: datetime, payload: Mapping[str, Any]) -> None:
        self._exec(
            "UPDATE runs SET finished_at=?, payload=? WHERE run_id=?",
            (finished_at.isoformat(), _dump(payload), run_id),
        )

    def log_event(
        self,
        kind: str,
        actor: str,
        challan_id: str | None = None,
        plate: str | None = None,
        detail: str | None = None,
        payload: Mapping[str, Any] | None = None,
        at: datetime | None = None,
    ) -> None:
        self._exec(
            "INSERT INTO case_events(challan_id, plate, at, kind, actor, detail, payload) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                challan_id,
                plate,
                (at or utcnow()).isoformat(),
                kind,
                actor,
                detail,
                _dump(payload) if payload is not None else None,
            ),
        )

    def save_challan(self, challan: Challan) -> None:
        self._exec(
            "INSERT OR REPLACE INTO challans(challan_id, event_id, plate, plate_hash, "
            "violation_type, base_fine, issued_at, due_at, risk_score, risk_level, "
            "evidence_root, status, policy_version, simulation, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                challan.challan_id,
                challan.event_id,
                challan.plate,
                challan.plate_hash,
                challan.violation_type.value,
                challan.base_fine,
                challan.issued_at.isoformat(),
                challan.due_at.isoformat(),
                challan.risk_score,
                challan.risk_level.value,
                challan.evidence_root_hash,
                challan.status.value,
                challan.policy_version,
                1 if challan.simulation else 0,
                _dump(challan),
            ),
        )

    def update_challan_status(self, challan_id: str, status: str) -> None:
        self._exec(
            "UPDATE challans SET status=? WHERE challan_id=?", (status, challan_id)
        )

    def save_payment(self, payment: PaymentRecord) -> None:
        self._exec(
            "INSERT OR REPLACE INTO payments(payment_id, challan_id, amount, paid_at, "
            "method, transaction_ref, simulation, payload) VALUES (?,?,?,?,?,?,?,?)",
            (
                payment.payment_id,
                payment.challan_id,
                payment.amount,
                payment.paid_at.isoformat(),
                payment.method,
                payment.transaction_ref,
                1 if payment.simulation else 0,
                _dump(payment),
            ),
        )

    def save_enforcement_request(self, request: EnforcementRequest) -> None:
        self._exec(
            "INSERT OR REPLACE INTO enforcement_requests(request_id, plate, created_at, "
            "status, total_outstanding, compliance_score, payload) VALUES (?,?,?,?,?,?,?)",
            (
                request.request_id,
                request.plate,
                request.created_at.isoformat(),
                request.status.value,
                request.total_outstanding,
                request.compliance_score,
                _dump(request),
            ),
        )

    def save_traces(self, traces: Sequence[AgentTrace]) -> None:
        self._exec_many(
            "INSERT INTO agent_traces(run_id, agent, level, maturity, verdict, "
            "duration_ms, at, payload) VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    t.run_id,
                    t.agent,
                    t.level,
                    t.maturity.value,
                    t.verdict,
                    t.duration_ms,
                    t.at.isoformat(),
                    _dump(t.details),
                )
                for t in traces
            ],
        )

    def save_compliance_snapshot(self, plate: str, profile: Any, at: datetime | None = None) -> None:
        self._exec(
            "INSERT INTO compliance_snapshots(plate, at, score, tier, stage, payload) "
            "VALUES (?,?,?,?,?,?)",
            (
                plate,
                (at or utcnow()).isoformat(),
                profile.score,
                profile.tier.value,
                profile.recommended_stage.value,
                _dump(profile),
            ),
        )

    # -- reads ----------------------------------------------------------- #
    def audit_trail(self, challan_id: str) -> list[dict[str, Any]]:
        return self._query(
            "SELECT at, kind, actor, detail FROM case_events WHERE challan_id=? ORDER BY id",
            (challan_id,),
        )

    def list_challans(self, plate: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM challans"
        clauses: list[str] = []
        params: list[Any] = []
        if plate:
            clauses.append("plate=?")
            params.append(plate)
        if status:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY issued_at"
        return self._query(query, params)

    def payments_for(self, challan_id: str) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM payments WHERE challan_id=? ORDER BY paid_at", (challan_id,)
        )

    def traces_for(self, run_id: str) -> list[dict[str, Any]]:
        return self._query(
            "SELECT agent, level, maturity, verdict, duration_ms FROM agent_traces "
            "WHERE run_id=? ORDER BY id",
            (run_id,),
        )

    def stats(self) -> dict[str, Any]:
        def count(table: str) -> int:
            return int(self._scalar(f"SELECT COUNT(*) FROM {table}") or 0)

        by_status = {
            row["status"]: row["n"]
            for row in self._query(
                "SELECT status, COUNT(*) AS n FROM challans GROUP BY status"
            )
        }
        outstanding = self._scalar(
            "SELECT COALESCE(SUM(base_fine),0) FROM challans "
            "WHERE status NOT IN ('PAID','CANCELLED')"
        )
        return {
            "challans": count("challans"),
            "events": count("case_events"),
            "payments": count("payments"),
            "enforcement_requests": count("enforcement_requests"),
            "agent_traces": count("agent_traces"),
            "by_status": by_status,
            "outstanding_amount": float(outstanding or 0.0),
        }
