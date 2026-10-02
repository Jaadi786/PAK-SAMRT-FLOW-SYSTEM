"""Command-line interface.

    python -m smartflow scenarios
    python -m smartflow demo                 # all five scenarios
    python -m smartflow demo 4 --urdu        # the differentiator, with Urdu text
    python -m smartflow fuzzy                # engine calibration table
    python -m smartflow compliance RWP-9087 --db smartflow-demo.sqlite
    python -m smartflow db --db smartflow-demo.sqlite
    python -m smartflow legal
    python -m smartflow selftest

Runs on a bare Python 3.10+ install: no third-party packages required.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from . import report
from .config import DEFAULT_POLICY
from .db import Store
from .decision import decide
from .evidence import cross_frame_agreement, seal_evidence, tamper_demo, verify_bundle
from .fuzzy import (
    DEFAULT_ENGINE,
    INPUT_LABELS,
    INPUT_TERMS,
    LEVEL_BANDS,
    OUTPUT_TERMS,
    UNIVERSE,
    level_for_score,
)
from .integrations import MockNADRAVerifier, mask_cnic
from .legal import (
    BLOCKED_CAPABILITIES,
    SAFE_ALTERNATIVES,
    SAFE_STATEMENT,
    ProhibitedOperationError,
)
from .models import EscalationStage, FrameCapture, ViolationType
from .pipeline import run_all, run_scenario
from .prediction import estimate_collision_risk
from .scenarios import SCENARIOS, ScenarioSpec, build_event, get_scenario, synthesise_frames
from .util import bar


def _utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):  # pragma: no cover - platform specific
                pass


def _print(text: str) -> None:
    print(text)


# --------------------------------------------------------------------------- #
def cmd_scenarios(args: argparse.Namespace) -> int:
    lines = [report.rule(), " PAK-SMARTFLOW - DEMO SCENARIOS", report.rule()]
    for spec in SCENARIOS:
        lines.append("")
        lines.append(f"  {spec.number}. {spec.key}  -  {spec.title}")
        lines.extend(report.wrap(spec.subtitle, indent=5))
        lines.append(
            f"     plate {spec.plate} | {spec.frames} frames "
            f"({spec.witnesses} witnessing) | density {spec.density:.0f} | "
            f"history {len(spec.history)} challan(s)"
        )
    lines += ["", "  Run one with:  python -m smartflow demo <number|key>", ""]
    _print("\n".join(lines))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    store = Store(args.db) if args.db else Store(":memory:")
    if args.db and not args.append:
        store.reset()

    specs: Sequence[ScenarioSpec]
    if args.scenario and not args.all:
        specs = (get_scenario(args.scenario),)
    else:
        specs = SCENARIOS

    results = []
    for spec in specs:
        result = run_scenario(spec, store=store, use_llm=args.llm)
        results.append(result)
        _print(report.render_result(result, store, DEFAULT_POLICY, spec, args.urdu))

    if len(results) > 1:
        _print(report.render_summary(results))
    if args.db:
        _print(report.render_db_stats(store))
    store.close()
    return 0


def cmd_fuzzy(args: argparse.Namespace) -> int:
    lines = [report.rule(), " FUZZY ENGINE - CALIBRATION AND RULE BASE", report.rule()]
    lines += report.section("Membership terms")
    for name, term in INPUT_TERMS.items():
        lines.append(
            f"  input  {name.ljust(10)}points {str(term.points).ljust(28)}"
            f"centroid {term.centroid:5.1f}"
        )
    for name, term in OUTPUT_TERMS.items():
        lines.append(
            f"  output {name.ljust(10)}points {str(term.points).ljust(28)}"
            f"centroid {term.centroid:5.1f}"
        )
    lines += report.section("Decision bands")
    previous = 0.0
    for upper, level in LEVEL_BANDS:
        top = min(100.0, upper)
        lines.append(
            f"  {level.value.ljust(10)}{previous:5.1f} - {top:5.1f}  {bar((previous + top) / 2, 24)}"
        )
        previous = upper
    lines += report.section("Rule base")
    for index, rule in enumerate(DEFAULT_ENGINE.rules, start=1):
        conditions = " AND ".join(f"{v} is {t}" for v, t in rule.conditions.items())
        lines.append(f"  {index:2d}. IF {conditions}")
        lines.append(f"      THEN risk is {rule.consequent}   (w={rule.weight:.2f})  {rule.label}")
    lines += report.section("Monotonicity check (severity sweep, other inputs fixed)")
    lines.append(
        f"  {'severity':>9}{'score':>9}{'level':>11}   {'':<20}"
    )
    for severity in range(0, 101, 10):
        assessment = DEFAULT_ENGINE.evaluate(
            {
                "evidence": 100.0,
                "severity": float(severity),
                "collision": 50.0,
                "density": 50.0,
                "context": 50.0,
            }
        )
        lines.append(
            f"  {severity:9d}{assessment.score:9.1f}"
            f"{assessment.level.value:>11}   {bar(assessment.score, 24)}"
        )
    lines += report.section("Reference cases (derived live from the demo scenarios)")
    lines.append(
        "  These inputs are computed from scenarios.py at run time, so this table"
    )
    lines.append(
        "  can never drift from what the pipeline actually feeds the engine."
    )
    lines.append("")
    lines.append(
        f"  {'scenario':<34}{'score':>7}{'engine':>10}{'pipeline':>11}"
    )
    for spec in SCENARIOS:
        event = build_event(spec, as_of=datetime.now(timezone.utc))
        severity = DEFAULT_POLICY.severity_for_event(event.violations)
        context_factor = DEFAULT_POLICY.context_factor(event.context_tags)
        estimate = estimate_collision_risk(
            speed_kmh=event.speed_kmh,
            speed_limit_kmh=event.speed_limit_kmh,
            traffic_density=event.traffic_density,
            context_factor=context_factor,
        )
        confidence = cross_frame_agreement(
            event.frames, event.violations[0].value
        )
        assessment = DEFAULT_ENGINE.evaluate(
            {
                "evidence": confidence,
                "severity": severity,
                "collision": estimate.score,
                "density": event.traffic_density,
                "context": context_factor,
            }
        )
        decision = decide(assessment, DEFAULT_POLICY)
        note = (
            "  <- Safety Overlay promoted it"
            if decision.risk.level is not assessment.level
            else ""
        )
        lines.append(
            f"  {spec.key:<34}{assessment.score:7.1f}"
            f"{assessment.level.value:>10}{decision.risk.level.value:>11}{note}"
        )
    lines.append("")
    lines.append(
        "  The 'engine' column is the raw fuzzy verdict; the 'pipeline' column is"
    )
    lines.append(
        "  the final verdict after the Safety Overlay and the Evidence Gate."
    )
    lines.append(
        "  The Evidence Gate can also suppress the challan entirely at any level"
    )
    lines.append(
        "  (scenario 5: engine HIGH, but the confidence is below the gate, so no"
    )
    lines.append("  challan is issued and the case goes to a human reviewer).")
    lines.append("")
    _print("\n".join(lines))
    return 0


def cmd_compliance(args: argparse.Namespace) -> int:
    from .compliance import build_profile
    from .models import Challan, ChallanStatus

    store = Store(args.db) if args.db else Store(":memory:")
    rows = store.list_challans(plate=args.plate)
    if not rows:
        _print(
            f"No challans for {args.plate}. Run: python -m smartflow demo 4 --db "
            f"{args.db or 'smartflow-demo.sqlite'}"
        )
        return 1
    challans = tuple(
        Challan(
            challan_id=row["challan_id"],
            event_id=row["event_id"] or "",
            plate=row["plate"],
            violation_type=ViolationType(row["violation_type"]),
            base_fine=float(row["base_fine"]),
            issued_at=__import__("datetime").datetime.fromisoformat(row["issued_at"]),
            due_at=__import__("datetime").datetime.fromisoformat(row["due_at"]),
            risk_score=float(row["risk_score"] or 0.0),
            risk_level=level_for_score(float(row["risk_score"] or 0.0)),
            evidence_root_hash=row["evidence_root"] or "",
            evidence_frame_count=0,
            status=ChallanStatus(row["status"]),
            explanation="",
            policy_version=row["policy_version"] or "",
            plate_hash=row["plate_hash"] or "",
        )
        for row in rows
    )
    profile = build_profile(
        args.plate,
        challans,
        notices_sent=len(store.audit_trail(challans[0].challan_id)),
        as_of=None,
    )
    lines = report.section(f"COMPLIANCE - {args.plate}")
    lines.append(report.kv("Unpaid", profile.unpaid_count))
    lines.append(report.kv("Outstanding (base)", f"PKR {profile.outstanding_amount:,.0f}"))
    lines.append(report.kv("Oldest case", f"{profile.oldest_unpaid_days} days"))
    lines.append(report.kv("Score", f"{profile.score:.1f}/100  {bar(profile.score)}"))
    lines.append(report.kv("Tier", profile.tier.value))
    lines.append(report.kv("Recommended stage", profile.recommended_stage.value))
    lines.append("")
    lines.append("  Derivation:")
    lines.extend(f"    {reason}" for reason in profile.reasons)
    _print("\n".join(lines))
    store.close()
    return 0


def cmd_db(args: argparse.Namespace) -> int:
    store = Store(args.db) if args.db else Store(":memory:")
    _print(report.render_db_stats(store))
    store.close()
    return 0


def cmd_legal(args: argparse.Namespace) -> int:
    _print("\n".join(report.render_legal()))
    _print("")
    _print("  Say this verbatim when asked about scope:")
    _print("")
    _print("\n".join(report.wrap(f'"{SAFE_STATEMENT}"', indent=4)))
    _print("")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Attempt every prohibited operation live and show each one failing.

    A raw traceback is a bad stage moment. This prints the same truth in a form a
    judge can read in three seconds.
    """
    nadra = MockNADRAVerifier()
    attempts = (
        ("block a real CNIC", lambda: nadra.request_service_block("3520212345671", "unpaid challans")),
        ("freeze a bank account", lambda: nadra.freeze_bank_account("3520212345671")),
        ("block a SIM", lambda: nadra.block_sim("3520212345671")),
        ("identify the driver by face", lambda: nadra.identify_driver_biometrically(b"\x00\x01")),
    )
    lines = [
        report.rule(),
        " LEGAL PROBE - ATTEMPTING EVERY PROHIBITED OPERATION",
        report.rule(),
        " Each of these is real code in smartflow/integrations.py. Each one fails.",
        "",
    ]
    failures = 0
    for label, call in attempts:
        try:
            call()
            failures += 1
            lines.append(f"  [!!] {label}: SUCCEEDED -- this must never happen")
        except ProhibitedOperationError as exc:
            lines.append(f"  [blocked] {label}")
            lines.extend(report.wrap(str(exc), indent=12))
    lines.append("")
    lines.append(f"  Prohibited operations that succeeded: {failures} (must be 0)")
    lines.append(f"  Network calls made to any external system: {nadra.network_calls}")
    lines.append("")
    lines.append("  Instead of each blocked capability:")
    for capability in BLOCKED_CAPABILITIES:
        lines.append(f"    x {capability}")
        lines.extend(report.wrap("-> " + SAFE_ALTERNATIVES[capability], indent=8))
    lines.extend(report.section("Say this verbatim"))
    lines.extend(report.wrap(f'"{SAFE_STATEMENT}"', indent=2))
    lines.append("")
    _print("\n".join(lines))
    return 1 if failures else 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Fast invariant checks. The full suite lives in tests/ (stdlib unittest)."""
    checks: list[tuple[str, bool, str]] = []

    # 1. Fuzzy monotonicity in severity.
    scores = [
        DEFAULT_ENGINE.evaluate(
            {
                "evidence": 100.0,
                "severity": float(s),
                "collision": 50.0,
                "density": 50.0,
                "context": 50.0,
            }
        ).score
        for s in range(0, 101, 5)
    ]
    monotone = all(b >= a - 1e-6 for a, b in zip(scores, scores[1:]))
    checks.append(("fuzzy score is monotone in severity", monotone, f"{scores[0]:.1f} -> {scores[-1]:.1f}"))

    # 2. Input validation.
    try:
        DEFAULT_ENGINE.evaluate(
            {"evidence": 150.0, "severity": 50.0, "collision": 50.0, "density": 50.0, "context": 50.0}
        )
        checks.append(("out-of-range input rejected", False, "no error raised"))
    except ValueError as exc:
        checks.append(("out-of-range input rejected", True, str(exc)[:48]))

    # 3. Evidence tamper detection.
    frames = synthesise_frames(4, 4, ViolationType.RED_LIGHT, "CAM-T", __import__("datetime").datetime.now())
    bundle = seal_evidence("CASE-T", frames)
    intact = verify_bundle(bundle)
    broken = not verify_bundle(tamper_demo(bundle))
    checks.append(("sealed bundle verifies", intact, bundle.root_hash[:16]))
    checks.append(("tampered bundle detected", broken, "root hash mismatch"))

    # 4. Weak evidence reduces confidence.
    weak = cross_frame_agreement(synthesise_frames(3, 1, ViolationType.RED_LIGHT, "C", __import__("datetime").datetime.now()), ViolationType.RED_LIGHT.value)
    strong = cross_frame_agreement(frames, ViolationType.RED_LIGHT.value)
    checks.append(("frame disagreement lowers confidence", weak < strong, f"{weak:.1f} < {strong:.1f}"))

    # 5. Prohibited operations are hard failures.
    nadra = MockNADRAVerifier()
    blocked_ok = False
    detail = ""
    try:
        nadra.request_service_block("3520212345671", "demo")
    except ProhibitedOperationError as exc:
        blocked_ok = True
        detail = str(exc)[:48]
    checks.append(("service-block attempt raises", blocked_ok, detail))
    checks.append(("NADRA performs zero network calls", nadra.network_calls == 0, "network_calls == 0"))
    checks.append(("CNIC masking hides middle digits", mask_cnic("3520212345671").endswith("1") and "XXXXXXX" in mask_cnic("3520212345671"), mask_cnic("3520212345671")))

    # 6. Full pipeline on the differentiator scenario.
    store = Store(":memory:")
    spec = get_scenario("4")
    result = run_scenario(spec, store, use_llm=False)
    checks.append(("scenario 4 issues a challan", result.challan is not None, result.challan.challan_id if result.challan else "-"))
    checks.append(
        (
            "scenario 4 reaches an enforcement request",
            result.enforcement_request is not None,
            result.enforcement_request.request_id if result.enforcement_request else "-",
        )
    )
    checks.append(
        (
            "enforcement request is inert (never executable)",
            bool(result.enforcement_request and result.enforcement_request.simulation),
            result.enforcement_request.status.value if result.enforcement_request else "-",
        )
    )
    checks.append(
        (
            "scenario 4 resolves on payment",
            bool(result.payments) and result.compliance is not None and result.compliance.tier.value == "COMPLIANT",
            f"{len(result.payments)} payments, compliance {result.compliance.score if result.compliance else '-'}",
        )
    )

    # 7. Scenario 5 must refuse to penalise on weak evidence.
    weak_result = run_scenario(get_scenario("5"), store, use_llm=False)
    checks.append(
        (
            "scenario 5 issues NO challan (evidence gate)",
            weak_result.challan is None,
            f"score {weak_result.decision.risk.score:.1f}",
        )
    )
    checks.append(
        (
            "scenario 5 cancels the tampered challan",
            any(
                row["status"] == "CANCELLED"
                for row in store.list_challans(plate=weak_result.history[0].plate)
            ),
            "appeal upheld automatically",
        )
    )
    store.close()

    lines = [report.rule(), " SELFTEST - INVARIANTS", report.rule()]
    failures = 0
    for label, ok, detail in checks:
        if not ok:
            failures += 1
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {label.ljust(46)}{detail}")
    lines.append("")
    lines.append(f"  {len(checks) - failures}/{len(checks)} invariant checks passed")
    lines.append("")
    _print("\n".join(lines))
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartflow",
        description="Pak-SmartFlow: from challan generation to compliance resolution (prototype).",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scenarios", help="list demo scenarios").set_defaults(func=cmd_scenarios)

    demo = sub.add_parser("demo", help="run one or all scenarios end to end")
    demo.add_argument("scenario", nargs="?", help="scenario number (1-5) or key")
    demo.add_argument("--all", action="store_true", help="run every scenario")
    demo.add_argument("--db", help="SQLite path (default: in-memory)")
    demo.add_argument("--append", action="store_true", help="keep existing rows in --db")
    demo.add_argument("--urdu", action="store_true", help="also print Urdu citizen notice")
    demo.add_argument("--llm", action="store_true", help="use Groq for wording if configured")
    demo.set_defaults(func=cmd_demo)

    sub.add_parser("fuzzy", help="print engine calibration and rule base").set_defaults(func=cmd_fuzzy)

    comp = sub.add_parser("compliance", help="compliance profile for one plate from the DB")
    comp.add_argument("plate")
    comp.add_argument("--db", help="SQLite path")
    comp.set_defaults(func=cmd_compliance)

    db = sub.add_parser("db", help="database statistics")
    db.add_argument("--db", help="SQLite path")
    db.set_defaults(func=cmd_db)

    sub.add_parser("legal", help="print the legal boundary map").set_defaults(func=cmd_legal)
    sub.add_parser(
        "probe", help="attempt every prohibited operation and show each one fail"
    ).set_defaults(func=cmd_probe)
    sub.add_parser("selftest", help="run fast invariant checks").set_defaults(func=cmd_selftest)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except KeyError as exc:
        _print(f"error: {exc}")
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
