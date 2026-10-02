"""Fail if importing the core package pulls in any third-party dependency.

The project claims that ``smartflow/`` runs on a bare Python interpreter. That
claim is easy to make and easy to break — one stray ``import pandas`` in a
helper module and it silently becomes false. This script turns the claim into a
check that CI runs on every push.

    python tools/check_zero_deps.py

Exits 0 when the core is clean, 1 with the offending modules listed otherwise.

Must run in a *fresh* interpreter. Importing anything third-party first (pytest,
streamlit, pandas) would pollute ``sys.modules`` and produce a false failure —
which is exactly why this is a script rather than a unit test: in the CI job that
installs Streamlit, the test process has already imported it.
"""

from __future__ import annotations

import sys
from pathlib import Path

THIRD_PARTY_MARKERS = ("site-packages", "dist-packages")


def find_leaked_modules() -> list[str]:
    """Import the whole core, then report any third-party module it dragged in."""
    before = set(sys.modules)

    import smartflow  # noqa: F401  (imported for its side effect)
    from smartflow import (  # noqa: F401
        AGENTS,
        DEFAULT_ENGINE,
        DEFAULT_POLICY,
        Store,
        build_profile,
        compute_penalty,
        decide,
        evaluate_risk,
        run_all,
        run_scenario,
        seal_evidence,
        verify_bundle,
    )
    from smartflow.agents import AGENTS as _agents  # noqa: F401
    from smartflow.cli import build_parser  # noqa: F401
    from smartflow.pipeline import run_scenario as _run  # noqa: F401
    from smartflow.report import render_result  # noqa: F401

    leaked: list[str] = []
    for name in sorted(sys.modules):
        if name in before:
            continue
        path = getattr(sys.modules[name], "__file__", None) or ""
        if any(marker in path for marker in THIRD_PARTY_MARKERS):
            leaked.append(f"{name}  <-  {path}")
    return leaked


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    leaked = find_leaked_modules()
    if leaked:
        print("FAIL: importing the core pulled in third-party packages:")
        for item in leaked:
            print(f"  - {item}")
        print(
            "\nThe core must stay standard-library only so the demo runs on a "
            "fresh laptop with no install. Move the dependency behind an "
            "optional adapter."
        )
        return 1

    print(
        "OK: core imports nothing outside the standard library "
        f"({len(sys.modules)} modules loaded, 0 third-party)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
