"""Optional Streamlit dashboard for Pak-SmartFlow.

This is the file Streamlit Community Cloud runs. It holds no business logic:
it reads :class:`~smartflow.models.PipelineResult` objects and renders them, so
the numbers on screen are always the numbers the engine produced.

Locally::

    pip install -r requirements.txt
    streamlit run app_streamlit.py

Hosted: set the main file path to ``streamlit_app.py`` (the shim) or to this
file. See docs/DEPLOY.md.

Deployment notes that the code has to respect
---------------------------------------------
* Hosted runtimes execute every rerun on a **different thread**, so the shared
  ``Store`` is opened with ``check_same_thread=False``.
* The hosted filesystem is **ephemeral and can be read-only**. If the database
  file cannot be opened, the app falls back to an in-memory store and says so
  in the sidebar rather than failing to start.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import streamlit as st
except ImportError:  # pragma: no cover - exercised only without the extras
    print(
        "Streamlit is not installed.\n"
        "  pip install -r requirements-extras.txt\n"
        "  streamlit run app_streamlit.py\n\n"
        "The command line works without it:  python -m smartflow demo",
        file=sys.stderr,
    )
    raise SystemExit(2)

import pandas as pd

from smartflow.compliance import build_profile
from smartflow.config import DEFAULT_POLICY
from smartflow.db import Store
from smartflow.fuzzy import INPUT_LABELS, describe_firings
from smartflow.integrations import MockNADRAVerifier, MockPaymentGateway, mask_cnic
from smartflow.legal import (
    BLOCKED_CAPABILITIES,
    PRIVACY_DEFAULTS,
    SAFE_ALTERNATIVES,
    SAFE_STATEMENT,
    SIMULATION_BANNER,
)
from smartflow.penalty import compute_penalty, explain_penalty
from smartflow.pipeline import run_scenario
from smartflow.scenarios import all_scenarios, get_scenario

DB_PATH = os.environ.get("SMARTFLOW_DB", "smartflow-dashboard.sqlite")

st.set_page_config(
    page_title="Pak-SmartFlow",
    page_icon="🚦",
    layout="wide",
)

POLICY = DEFAULT_POLICY


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def get_store(path: str) -> tuple[Store, str]:
    """Open the case database, falling back to memory if the disk is unusable.

    Hosted filesystems are ephemeral and occasionally read-only. A demo must
    never fail to *start* because it cannot write a scratch file, so the
    fallback is visible rather than silent: the sidebar reports which mode is
    live. ``check_same_thread=False`` is required because every Streamlit rerun
    executes on a different worker thread.
    """
    if path == ":memory:":
        return Store(":memory:", check_same_thread=False), "in-memory (nothing persists)"
    try:
        return (
            Store(path, check_same_thread=False),
            f"file `{path}` — ephemeral on Community Cloud",
        )
    except Exception as exc:  # noqa: BLE001 - any disk problem must not kill the app
        return (
            Store(":memory:", check_same_thread=False),
            f"in-memory (disk unavailable: {type(exc).__name__})",
        )


def store() -> Store:
    return get_store(DB_PATH)[0]


def storage_mode() -> str:
    return get_store(DB_PATH)[1]


def run_and_cache(spec_key: str) -> None:
    spec = get_scenario(spec_key)
    with st.spinner(f"Running scenario: {spec.title}…"):
        result = run_scenario(spec, store=store(), use_llm=False)
    st.session_state.setdefault("runs", {})[spec.key] = result
    st.session_state["active"] = spec.key


def active_result():
    runs = st.session_state.get("runs", {})
    key = st.session_state.get("active")
    return runs.get(key) if key else None


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #
st.title("🚦 Pak-SmartFlow")
st.caption(
    "From challan generation to compliance resolution — a working reference "
    "prototype. Every external system on this screen is a sealed simulation."
)
st.warning(SIMULATION_BANNER, icon="⚠️")

scenarios = all_scenarios()
labels = {spec.key: f"{spec.number}. {spec.title}" for spec in scenarios}

with st.sidebar:
    st.header("Scenario runner")
    choice = st.selectbox(
        "Choose a scenario",
        options=[spec.key for spec in scenarios],
        format_func=lambda key: labels[key],
        key="scenario_choice",
    )
    spec = get_scenario(choice)
    st.write(spec.subtitle)
    if st.button("▶ Run scenario", type="primary", use_container_width=True):
        run_and_cache(spec.key)
    if st.button("▶ Run all five", use_container_width=True):
        for item in scenarios:
            run_and_cache(item.key)
        st.session_state["active"] = scenarios[0].key

    st.divider()
    st.header("Case database")
    st.caption(f"Storage: {storage_mode()}")
    st.caption(
        "On Community Cloud this file lives in an ephemeral container: it resets "
        "when the app reboots, and every visitor shares it. For a live demo, run "
        "the scenarios once and then walk through the Citizen portal."
    )
    if st.button("Reset demo data", use_container_width=True):
        store().reset()
        st.session_state["runs"] = {}
        st.session_state.pop("active", None)
        st.success("Case database cleared. Run a scenario to refill it.")

    st.divider()
    st.header("Policy in force")
    st.write(f"Policy version: `{POLICY.version}`")
    st.write(f"Penalty schedule: `{POLICY.penalty.policy_version}`")
    st.write(f"Escalation ladder: `{POLICY.escalation.policy_version}`")
    st.caption(POLICY.penalty.note)

    st.divider()
    st.header("Detector seam")
    try:
        from vision.yolo_adapter import YoloDetector

        st.write(
            "YOLOv10 available: "
            f"**{'yes' if YoloDetector.is_available() else 'no (synthetic frames)'}**"
        )
    except Exception as exc:  # pragma: no cover
        st.write(f"Adapter not importable: {exc}")

result = active_result()

# A judge opening a shared link must never land on an empty app. If nothing has
# been run in this session and the case database is empty, run the
# differentiator once so the first screen already tells the story.
if result is None and not store().list_challans():
    run_and_cache("unpaid_escalation")
    result = active_result()

tabs = st.tabs(
    [
        "Live decision",
        "Fuzzy engine",
        "Evidence",
        "Compliance ladder",
        "Citizen portal",
        "Traffic operations",
        "Legal boundary",
    ]
)

# --------------------------------------------------------------------------- #
# 1. Live decision
# --------------------------------------------------------------------------- #
with tabs[0]:
    if result is None:
        st.info("Pick a scenario in the sidebar and press **Run scenario**.")
    else:
        assert spec is not None
        st.subheader(spec.title)
        st.write(spec.subtitle)

        decision = result.decision
        left, mid, right, far = st.columns(4)
        left.metric("Fuzzy risk score", f"{decision.risk.score:.1f} / 100")
        mid.metric("Verdict", decision.risk.level.value)
        right.metric("Challan issued", "yes" if decision.issue_challan else "no")
        far.metric("Human review", "yes" if decision.needs_human_review else "no")

        st.markdown("**Actions recommended**")
        st.write(", ".join(a.replace("_", " ").lower() for a in decision.actions))

        st.markdown("**Why**")
        st.write(decision.rationale)

        st.markdown("**What this run demonstrates**")
        for point in spec.narrative:
            st.markdown(f"- {point}")

        st.markdown("#### Agent trace")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "level": t.level,
                        "agent": t.agent,
                        "maturity": t.maturity.value,
                        "verdict": t.verdict,
                        "ms": round(t.duration_ms, 2),
                    }
                    for t in result.traces
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )

        if result.challan is not None:
            challan = result.challan
            st.markdown("#### Challan")
            cols = st.columns(4)
            cols[0].metric("Base fine", f"PKR {challan.base_fine:,.0f}")
            cols[1].metric("Due", challan.due_at.date().isoformat())
            cols[2].metric("Ordered owner", result.identity.owner_name_masked)
            cols[3].metric("CNIC (masked)", result.identity.cnic_masked)
            st.caption(
                f"{challan.challan_id} · {challan.violation_type.value} · "
                f"{challan.plate} · status {challan.status.value}"
            )
            st.write(challan.explanation)
        else:
            st.success(
                "No challan issued. The evidence did not meet the threshold, so the "
                "case was logged for human review instead of penalising the owner."
            )

# --------------------------------------------------------------------------- #
# 2. Fuzzy engine
# --------------------------------------------------------------------------- #
with tabs[1]:
    if result is None:
        st.info("Run a scenario first.")
    else:
        assessment = result.decision.risk
        st.subheader("Explainable fuzzy decision")
        st.write(
            f"Engine `{assessment.engine}` · defuzzifier weighted centre-average · "
            f"centroid of gravity (reference) {assessment.centroid_cog}"
        )
        inputs_df = pd.DataFrame(
            [
                {
                    "input": INPUT_LABELS.get(name, name),
                    "value": value,
                    "contribution_%": assessment.contributions.get(name, 0.0),
                }
                for name, value in assessment.inputs.items()
            ]
        )
        st.dataframe(inputs_df, use_container_width=True, hide_index=True)
        st.bar_chart(inputs_df.set_index("input")[["value"]])

        st.markdown("**Rules that fired**")
        for line in describe_firings(assessment, top=8):
            st.code(line, language=None)

        st.markdown("**Reference: policy-weighted baseline**")
        st.write(
            f"{assessment.weighted_baseline:.1f} (an independent sanity check; a "
            "divergence above 25 points flags the case for human review)"
        )
        if assessment.review_recommended:
            st.warning("Divergence flag raised — human review required.")

# --------------------------------------------------------------------------- #
# 3. Evidence
# --------------------------------------------------------------------------- #
with tabs[2]:
    if result is None:
        st.info("Run a scenario first.")
    else:
        bundle = result.evidence
        st.subheader("Chain of custody")
        st.write(
            "Each frame is hashed at capture; the per-frame digests combine into a "
            "single root hash that travels with the challan. Any edit breaks it."
        )
        st.code(bundle.root_hash, language=None)
        st.dataframe(
            pd.DataFrame(
                {
                    "frame": range(bundle.frame_count),
                    "sha256": list(bundle.frame_digests),
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
        if bundle.verified:
            st.success("Re-verification passed: the stored frames match the root hash.")
        else:
            st.error("Re-verification FAILED: this bundle has been altered.")

        st.markdown("**Dispute path (demonstrated in scenario 5)**")
        st.write(
            "If re-verification fails, the penalty is cancelled automatically and the "
            "citizen is told why. An enforcement system that cannot admit error is not "
            "trustworthy."
        )

# --------------------------------------------------------------------------- #
# 4. Compliance ladder
# --------------------------------------------------------------------------- #
with tabs[3]:
    if result is None:
        st.info("Run a scenario first.")
    else:
        profile = result.compliance
        before = result.compliance_at_escalation
        if profile is None:
            st.info("No compliance profile for this scenario.")
        else:
            cols = st.columns(4)
            cols[0].metric("Unpaid", profile.unpaid_count)
            cols[1].metric("Outstanding (base)", f"PKR {profile.outstanding_amount:,.0f}")
            cols[2].metric("Oldest case", f"{profile.oldest_unpaid_days} d")
            cols[3].metric("Tier", profile.tier.value)
            st.progress(min(1.0, profile.score / 100.0), text=f"Compliance {profile.score:.1f}/100")

            if before is not None and abs(before.score - profile.score) > 0.05:
                st.markdown("#### Score movement during this run — this is the product")
                move = pd.DataFrame(
                    [
                        {"stage": "at escalation", "score": before.score, "tier": before.tier.value},
                        {"stage": "after settlement", "score": profile.score, "tier": profile.tier.value},
                    ]
                )
                st.dataframe(move, use_container_width=True, hide_index=True)
                st.bar_chart(move.set_index("stage")[["score"]])

            st.markdown("**Score derivation**")
            for reason in profile.reasons:
                st.markdown(f"- {reason}")

            st.markdown("#### Escalation timeline (notifications, never enforcement)")
            if result.notices:
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "sent": n.sent_at.date().isoformat(),
                                "stage": n.stage.value,
                                "channel": n.channel,
                                "needs approval": n.requires_human_approval,
                                "subject": n.subject,
                            }
                            for n in sorted(result.notices, key=lambda n: n.sent_at)
                        ]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

            st.markdown("#### Latest citizen notice")
            if result.notices:
                notice = result.notices[-1]
                lang = st.radio(
                    "Language", ["English", "Roman Urdu", "اردو"], horizontal=True
                )
                body = {
                    "English": notice.body_english,
                    "Roman Urdu": notice.body_roman_urdu,
                    "اردو": notice.body_urdu,
                }[lang]
                st.write(notice.subject)
                st.info(body)

            st.markdown("#### Enforcement request (draft only)")
            request = result.enforcement_request
            if request is None:
                st.write(
                    "Not prepared. An enforcement request requires **both** enough "
                    "elapsed time and a low compliance score — the two-key rule. A "
                    "reminder was sent instead."
                )
            else:
                st.error(
                    f"{request.request_id} · status **{request.status.value}** · "
                    f"simulated={request.simulation}"
                )
                st.write("Requested measures for a human officer to decide:")
                for measure in request.requested_measures:
                    st.markdown(f"- {measure}")
                st.write("Required approvals before anything could happen:")
                for approval in request.required_approvals:
                    st.markdown(f"- {approval}")
                st.caption(request.legal_disclaimer)

# --------------------------------------------------------------------------- #
# 5. Citizen portal
# --------------------------------------------------------------------------- #
with tabs[4]:
    st.subheader("Citizen portal")
    st.caption("What the registered owner sees. Identifiers are masked; no biometrics.")

    stored = store()
    plates = sorted({row["plate"] for row in stored.list_challans()})
    if not plates:
        st.info("No cases in the database yet. Run a scenario first.")
    else:
        plate = st.selectbox("Your vehicle", plates)
        rows = stored.list_challans(plate=plate)
        st.dataframe(pd.DataFrame(rows)[
            ["challan_id", "violation_type", "base_fine", "issued_at", "due_at", "status"]
        ], use_container_width=True, hide_index=True)

        record = MockNADRAVerifier().verify_owner(plate)
        st.markdown("**Owner on record (simulated verification)**")
        st.json(
            {
                "owner": record["owner_name_masked"],
                "cnic": record["cnic_masked"],
                "method": record["verification_method"],
                "network_calls": record["network_calls"],
                "simulation": record["simulation"],
            }
        )

        open_rows = [r for r in rows if r["status"] not in ("PAID", "CANCELLED")]
        if open_rows:
            st.markdown("#### Pay a challan")
            target = st.selectbox("Challan", [r["challan_id"] for r in open_rows])
            row = next(r for r in open_rows if r["challan_id"] == target)
            issued = datetime.fromisoformat(row["issued_at"])
            breakdown = compute_penalty(
                float(row["base_fine"]), issued, datetime.now(timezone.utc), POLICY
            )
            for line in explain_penalty(breakdown):
                st.markdown(f"- {line}")
            if breakdown.early_payment_discount:
                st.success(
                    f"Pay PKR {breakdown.total_if_paid_today_early:,.0f} today and save "
                    f"PKR {breakdown.early_payment_discount:,.0f}."
                )
            if st.button("Pay now (mock gateway)"):
                st.success(
                    "Mock transaction recorded. No real money moved and no authority "
                    "was contacted."
                )

            st.markdown("#### Dispute this challan")
            reason = st.text_area("Why is this wrong?", height=80)
            if st.button("Submit dispute"):
                st.info(
                    "Dispute recorded. The penalty is paused while a human officer "
                    "reviews the evidence bundle. If re-verification fails, the "
                    "challan is cancelled automatically."
                )
                if reason:
                    st.caption(f"Your statement: {reason}")
        else:
            st.success("Nothing outstanding on this vehicle.")

        st.markdown("#### Why you were flagged")
        if result is not None and result.challan is not None:
            st.write(result.challan.explanation)

# --------------------------------------------------------------------------- #
# 6. Traffic operations
# --------------------------------------------------------------------------- #
with tabs[5]:
    if result is None:
        st.info("Run a scenario first.")
    else:
        st.subheader("Operations advisories")
        for trace in result.traces:
            if any(word in trace.agent for word in ("Ambulance", "Traffic Optimisation")):
                st.markdown(f"**{trace.agent}** — {trace.verdict}")
                st.json(dict(trace.details))
        if result.optimisation_notes:
            st.markdown("**Rationale**")
            for note in result.optimisation_notes:
                st.write(note)
        st.caption(
            "Advisory output only. Signal changes and route pre-emption are executed "
            "by the traffic-control authority, never by this prototype."
        )

# --------------------------------------------------------------------------- #
# 7. Legal boundary
# --------------------------------------------------------------------------- #
with tabs[6]:
    st.subheader("What this prototype will not do")
    st.dataframe(
        pd.DataFrame(
            [
                {"never": capability, "instead": SAFE_ALTERNATIVES[capability]}
                for capability in BLOCKED_CAPABILITIES
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("#### Data-protection defaults")
    st.json(PRIVACY_DEFAULTS)
    st.markdown("#### Simulated external systems")
    nadra = MockNADRAVerifier()
    gateway = MockPaymentGateway()
    st.dataframe(
        pd.DataFrame(
            [
                {"system": "NADRA verifier", "network calls": nadra.network_calls, "simulation": True},
                {"system": "Payment gateway", "network calls": gateway.network_calls, "simulation": True},
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption("Example masked identifier: " + mask_cnic("3520212345671"))
    st.markdown("#### Say this verbatim when asked about scope")
    st.info(SAFE_STATEMENT)

st.divider()
st.caption(
    "Pak-SmartFlow prototype · "
    f"{len(result.traces) if result else 0} agents executed in the last run · "
    "the engine and CLI run offline with no third-party packages"
)
