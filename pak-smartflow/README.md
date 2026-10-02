# 🚦 Pak-SmartFlow

[![tests](https://github.com/YOUR-USERNAME/pak-smartflow/actions/workflows/tests.yml/badge.svg)](https://github.com/YOUR-USERNAME/pak-smartflow/actions/workflows/tests.yml)

**From challan generation to compliance resolution.**

A working reference prototype for intelligent traffic enforcement in Pakistan — not
a slide deck. Twelve agents, an explainable fuzzy risk engine, tamper-evident
evidence, a progressive penalty ladder, and a compliance-escalation workflow that
ends in a *closed* case rather than an unpaid fine.

```bash
python -m smartflow demo 4      # the differentiator, end to end
python -m smartflow selftest    # 14 invariants
python -m unittest discover -s tests -t .   # 187 tests
```

**The engine and CLI need no installation.** They run on a bare Python 3.11+
interpreter with zero third-party imports (verified below), no network calls and
no API keys. The optional dashboard needs `streamlit` and `pandas` — see
[Deployment](#13-deployment).

> Replace `YOUR-USERNAME` in the badge above after your first push. See
> [docs/DEPLOY.md](docs/DEPLOY.md).

---

## 1. The gap this closes

```
Existing systems:   Detect → Challan → (nothing)
Pak-SmartFlow:      Detect → Verify → Score → Explain → Challan → Notify
                    → Escalate → Prepare authority review → Recover → Resolve
```

Every deployed system in the region is excellent at the first arrow and silent
about the rest. The interesting questions are the later ones:

- What happens when the challan is **not paid**?
- What happens when the evidence is **wrong**?
- What does the citizen **actually receive**, in a language they read?
- Who is **allowed** to do what, and who approves it?

The prototype answers all four with running code.

> **On invented statistics:** this README deliberately does not claim a national
> non-payment rate, because we did not measure one. If you need that number for a
> pitch, measure it on your own city's data and cite the source. Claiming a
> figure you cannot defend is the fastest way to lose a technical judge.

---

## 2. What is different

| # | Claim | Where it lives in the code |
|---|-------|----------------------------|
| 1 | **It finishes the job.** A case reaches `RESOLVED`, not `ISSUED`. | `compliance.py`, `agents.py` (agents 11–12) |
| 2 | **It says why.** Every verdict prints the rules that fired and each input's contribution. | `fuzzy.py`, `decision.py`, `report.py` |
| 3 | **It refuses to over-penalise.** Weak evidence blocks a challan outright; a serious allegation on weak evidence goes to a human. | `decision.py` (`EvidenceGate`) |
| 4 | **It cannot act against a citizen.** Prohibited operations exist as methods that *always raise*. | `legal.py`, `integrations.py` |

Point 4 is the load-bearing one. Rather than promising restraint in a slide, the
codebase ships `MockNADRAVerifier.request_service_block()`, which is guaranteed to
fail. A reviewer can run it and watch it fail.

---

## 3. Quickstart

```bash
cd pak-smartflow

python -m smartflow scenarios          # list the five scenarios
python -m smartflow demo               # run all five, full case files
python -m smartflow demo 4 --urdu      # the differentiator, with Urdu notices
python -m smartflow demo 2             # the Safety Overlay firing
python -m smartflow fuzzy              # engine calibration + rule base + live cross-check
python -m smartflow legal              # the enforced legal boundary
python -m smartflow probe              # attempt every prohibited operation, watch each fail
python -m smartflow selftest           # fast invariants (CI-friendly, exit code)

# persist a real case file and query it
python -m smartflow demo 4 --db demo.sqlite
python -m smartflow compliance RWP-9087 --db demo.sqlite
python -m smartflow db --db demo.sqlite

# the test suite (stdlib unittest, no install)
python -m unittest discover -s tests -t .

# optional dashboard
pip install -r requirements.txt
streamlit run app_streamlit.py
```

On Windows the two helper scripts are blocked by the default execution policy.
Run them with a bypass, or use the `python -m smartflow` commands above:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
powershell -ExecutionPolicy Bypass -File .\run_demo.ps1 4
```

---

## 4. Verified status

Everything below was measured on this codebase, not estimated.

| Property | Value | How it was verified |
|----------|-------|---------------------|
| Third-party imports in the core | **0** | Imported the full package and inspected every new entry in `sys.modules` for a `site-packages` path. Re-proved in CI on every push |
| Tests | **187 passing** | `python -m unittest discover -s tests -t .` → exit 0 |
| Tests that need Streamlit | 6 (skipped without it) | `tests/test_streamlit_app.py`, run in the CI dashboard job |
| Invariant checks | **14/14** | `python -m smartflow selftest` → exit 0 |
| CI matrix | Python 3.11 / 3.12 / 3.13 | `.github/workflows/tests.yml` |
| Agents executed per scenario | **12** | One `AgentTrace` per agent, asserted in `tests/test_agents.py` |
| Core size | 20 modules / ~5 300 lines | `pathlib` line count over `smartflow/` |
| Test size | 11 files / ~1 900 lines | line count over `tests/` |
| Network calls during a full run | **0** | `MockNADRAVerifier.network_calls == 0`, asserted in tests |
| Runtime for all five scenarios | well under a second of agent time | `RUN SUMMARY` prints per-agent milliseconds |
| Thread safety of the case store | 8 concurrent readers/writers, no corruption | `tests/test_db.py::ThreadSafetyTests` |

### Measured scenario outcomes

These are the actual numbers the engine produced, not targets.

| Scenario | Risk score | Verdict | Challan | Final compliance | Notes |
|----------|-----------|---------|---------|------------------|-------|
| 1. Red light, clean evidence | 83.2 | HIGH | yes | 92 | ordinary path works |
| 2. Wrong-way + speeding, school zone | 88.1 | **CRITICAL** | yes | 92 | Safety Overlay fired |
| 3. Hospital corridor blocked | 46.4 | MEDIUM | yes | 94 | proportionate, plus a corridor plan |
| 4. **Eight ignored challans** | 84.5 | HIGH | yes | **100** | 11.2 SEVERE → enforcement request → paid → withdrawn → COMPLIANT |
| 5. False positive + appeal | 69.1 | HIGH | **no** | 84 | Evidence Gate blocked it; a tampered bundle was cancelled |

---

## 5. Honest maturity map

The agents carry a maturity label in code and print it in the trace. Nothing is
oversold.

| # | Agent | Level | Maturity | What is real today |
|---|-------|-------|----------|--------------------|
| 1 | Detection | 1 | `mock` | Synthetic frames; multi-violation handling is real |
| 2 | ANPR & Registry | 1 | `mock` | Seeded local registry, masked identities, zero network |
| 3 | Evidence Verification | 2 | **`deep`** | SHA-256 chain of custody, cross-frame agreement |
| 4 | Risk & Context | 2 | `heuristic` | Versioned policy tables, compounding severity |
| 5 | Predictive Safety | 2 | `heuristic` | Transparent TTC proxy model |
| 6 | Fuzzy Decision | 2 | **`deep`** | Mamdani inference, 20 rules, full explainability |
| 7 | Action & Notification | 3 | `heuristic` | Challan, due dates, trilingual notices |
| 8 | Explainability & Dispute | 3 | **`deep`** | Re-verifies every bundle, cancels on integrity failure |
| 9 | Ambulance Priority | 4 | `heuristic` | Corridor clearance plan, signal pre-emption advice |
| 10 | Traffic Optimisation | 5 | `heuristic` | Adaptive green-time with a safety hold |
| 11 | Smart Compliance | 6 | **`deep`** | Scoring, escalation ladder, two-key enforcement request |
| 12 | Payment Recovery | 6 | `mock` | Quotes, payment plans, settlement, auto-withdrawal |

Production replacements are named in the code, e.g. `prediction.py` states which
model would replace each heuristic and `vision/yolo_adapter.py` is the single
seam where YOLOv10 plugs in.

---

## 6. The fuzzy engine, briefly

Five linguistic inputs, 20 rules, four output terms:

```
evidence confidence  25%      severity  25%      collision risk  20%
traffic density      15%      context   15%
```

**Defuzzification is a weighted centre-average over fired rules**, and the choice
is deliberate. Textbook max-aggregation plus centre-of-gravity is *not* strictly
monotone here: growing the HIGH term's mass dilutes the CRITICAL mass and can drag
the centroid down by a fraction of a point as an input rises. A scoring engine that
goes down when danger goes up is a bad engine, so the centre average is reported
and the centroid is shown alongside it as a reference.

**A documented ceiling.** Every CRITICAL rule's condition set is a superset of some
HIGH rule's, so its firing strength can never exceed that HIGH rule's. The soft
score therefore tops out around 86. Rather than fudge membership functions to hide
this, the engine states it and `decision.py` applies a **Safety Overlay**: when
collision exposure, violation severity and traffic density are *all* extreme, a
HIGH verdict is promoted to CRITICAL, and the promotion is printed with its
reason. Soft scores recommend; hard overlays guarantee.

Try it yourself:

```bash
python -m smartflow fuzzy     # calibration table, rule base, monotonicity sweep
```

---

## 7. Engineering findings from the test suite

These are real bugs the tests caught during development. They are documented
because a reader deserves to know what was wrong and how it was found — and because
several of them are the kind that would have surfaced live, on stage.

| # | Defect | Consequence if undetected | Fix |
|---|--------|---------------------------|-----|
| 1 | Trapezoid shoulders returned `0.0` at `x=0` and `x=100` | The rule base silently emptied at the extremes of every input, and the fallback path hid it. Evidence confidence of 100% fired *no* high-evidence rule. | Test the plateau before the boundaries (`tests/test_fuzzy.py::test_left_shoulder_is_true_at_zero`) |
| 2 | A rule mapped *medium severity × medium collision* → `high` | The score **fell** as severity rose from 60 to 70 | Re-targeted the rule to `medium` and added a monotone medium spine |
| 3 | Max-aggregation + centre-of-gravity is not monotone | Risk score drops 0.07/100 while evidence rises | Switched to weighted centre-average; residual documented and tested with a tolerance |
| 4 | **The penalty cap was dead code** — 2.0× ceiling vs tranches summing to 1.85× | The "capped at 200%" line on every receipt could never be true | Cap set to 1.75×, and a regression test asserts `cap < 1 + Σtranches` |
| 5 | Early-payment discount left a 10% residue | The challan stayed `PARTIALLY_PAID` and the citizen stayed in the escalation ladder | Settling the discounted total now closes the case |
| 6 | Notice deductions survived settlement | A citizen who had just paid 9 challans still scored as "ignoring notices" | Notice and dispute deductions only apply while a case is open |
| 7 | Escalation back-fill replayed `ISSUED` and referenced the newest challan | A fabricated second issuance, with reminders dated *before* the challan existed | Issuance is excluded from the ladder; reminders target the oldest open case |
| 8 | Only the first violation's severity counted | Wrong-way *while* speeding scored as one offence, so the Safety Overlay never fired | `severity_for_event()` compounds concurrent violations, capped |
| 9 | The code sample in the specification used `severity['high']` with no membership functions defined | The demo would have raised `KeyError` live | The engine validates its rule base at construction time |

Finding 4 is the one to show a judge: a "safety feature" that had never once
executed, caught by an assertion about arithmetic rather than by a screenshot.

---

## 8. The legal boundary (enforced in code)

| ❌ Never | ✅ Instead |
|---------|-----------|
| Block a real CNIC | Prepare an Enforcement Request for authority review |
| Block a real passport | Prepare an Enforcement Request for authority review |
| Freeze a bank account | Offer a payment plan in the mock gateway |
| Block a SIM | Send a compliance reminder over a stub channel |
| Auto-deduct funds | Mock transaction only; the citizen initiates payment |
| Identify the driver by face | Registered-owner liability; biometrics deliberately excluded |

`legal.py` holds this as data, so the docs cannot drift from the code, and
`tests/test_legal.py` proves each blocked capability raises.

**Data-protection defaults:** evidence retained 30 days, raw images 7 days, plates
hashed for analytics, zero driver biometrics, append-only audit trail with an actor
on every state change, and a citizen right to view their own evidence bundle.

**Say this verbatim when asked about scope:**

> "Our prototype demonstrates how an authorized government ecosystem could
> technically coordinate these workflows, subject to applicable law, policy,
> security, and human/authority approval."

An Enforcement Request is inert by construction: status
`PENDING_AUTHORITY_APPROVAL`, `simulation=True`, and an
`assert_not_executable()` guard that raises if anyone ever flips it to approved.

---

## 9. Repository map

```
pak-smartflow/
├─ smartflow/                 core package — standard library only
│  ├─ legal.py                the enforced boundary (read this first)
│  ├─ config.py               all policy numbers, versioned and frozen
│  ├─ fuzzy.py                Mamdani engine, 20 rules, explainability
│  ├─ decision.py             Safety Overlay + Evidence Gate + action matrix
│  ├─ evidence.py             SHA-256 chain of custody, plate hashing
│  ├─ penalty.py              progressive, capped, explainable late fees
│  ├─ compliance.py           scoring, escalation ladder, two-key rule
│  ├─ agents.py               the twelve agents, with maturity labels
│  ├─ prediction.py           collision / ambulance / signal heuristics
│  ├─ integrations.py         sealed simulations (NADRA, payments, notices)
│  ├─ messages.py             trilingual templates (English / Roman Urdu / Urdu)
│  ├─ scenarios.py            the five demo cases
│  ├─ db.py                   SQLite + append-only case audit trail
│  ├─ report.py               fixed-width console case file
│  └─ cli.py                  `python -m smartflow …`
├─ vision/yolo_adapter.py     the single seam where a real detector plugs in
├─ app_streamlit.py           optional dashboard (7 tabs) — the Cloud entrypoint
├─ streamlit_app.py           Cloud's default entrypoint name; delegates to the above
├─ requirements.txt           streamlit + pandas (dashboard only)
├─ requirements-core.txt      intentionally empty — the engine needs nothing
├─ requirements-extras.txt    real detector, Urdu voice, LLM wording (all optional)
├─ .streamlit/config.toml     theme and server defaults (one config file only)
├─ .github/workflows/tests.yml  CI: 3 Python versions + dashboard smoke tests
└─ docs/                      architecture, demo script, PPT outline, roles, deploy
```

Every domain object is a frozen dataclass, so state transitions produce new values
and the audit trail stays trustworthy. All policy numbers live in one versioned
`PolicyConfig` and are stamped on every challan and notice — a provincial authority
could change the fine schedule without touching logic.

The `Store` is safe to share across threads (`check_same_thread=False` plus an
`RLock`), because hosted runtimes execute every script rerun on a different worker
thread. `tests/test_db.py` proves both that a default connection fails and that the
fixed one survives concurrent use.

---

## 10. Where to extend

| Want to… | Change |
|----------|--------|
| Use a real detector | `vision/yolo_adapter.py` → `YoloDetector` + `frames_from_directory()` |
| Use real LLM wording | `integrations.py` → `GroqExplanationWriter` (templates remain the fallback) |
| Change fines, fees or timelines | `config.py` only |
| Add a scenario | `scenarios.py` — one frozen `ScenarioSpec` |
| Swap SQLite for PostgreSQL | `db.py` — the `Store` interface is deliberately narrow |
| Add a language | `messages.py` — one template dict per stage |
| Deploy elsewhere | `streamlit_app.py` + `requirements.txt`; the engine itself needs no host |

**What is deliberately *not* here:** trained trajectory models, a real RAG
pipeline, Redis/Celery/TimescaleDB, and RL signal control. Those are roadmap items
in `docs/ARCHITECTURE.md`, and claiming them today would be the exact over-reach
that loses a technical evaluation.

---

## 11. Roadmap

| Horizon | Work |
|---------|------|
| 30 days | Real detector on 1–2 cameras; calibrate the rule base against labelled footage; move policy to a config service |
| 90 days | PostgreSQL + immutable audit log; LLM wording with human review; citizen app; field trial with one traffic police unit |
| 180 days | Multi-city deployment, federated policy per province, trained trajectory model, cost-per-case and compliance-rate dashboards with published methodology |

---

## 13. Deployment

**Live dashboard (Streamlit Community Cloud):** `<add your URL here after deploying>`

Full step-by-step instructions, including the four deployment blockers that had to
be fixed first and a troubleshooting table: **[docs/DEPLOY.md](docs/DEPLOY.md)**.

The short version:

```powershell
# 1. Get out of OneDrive first — sync + git corrupts .git
Copy-Item -Recurse "…\pak-smartflow" "C:\dev\pak-smartflow"; cd C:\dev\pak-smartflow

# 2. Push
git init -b main
git add .
git commit -m "Pak-SmartFlow: 12-agent compliance resolution prototype"
git remote add origin https://github.com/YOUR-USERNAME/pak-smartflow.git
git push -u origin main
```

3. On [share.streamlit.io](https://share.streamlit.io): **Create app** → repository
   `YOUR-USERNAME/pak-smartflow`, branch `main`, **Main file path
   `app_streamlit.py`**, Python `3.12`, **no secrets needed**.

Then run the post-deploy checklist in `docs/DEPLOY.md` §5 — on a phone as well as a
laptop.

**Honest note:** the dashboard was written in an environment with no network access
and no Streamlit installed, so it is verified by the CI job and by that checklist,
**not** by local execution. The engine, the CLI and all 187 tests are unaffected by
anything that happens in the browser.

---

## 14. License and acknowledgement

Prototype for demonstration and evaluation. Simulated external systems; no real
government service is contacted. Fines, fees and timelines are illustrative demo
values and are **not** a statement of current Pakistani law.
