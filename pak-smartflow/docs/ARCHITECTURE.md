# Architecture

## 1. Layers

```
┌─ PERCEPTION ────────────────────────────────────────────────────────────┐
│ vision/yolo_adapter.py   real detector seam (optional)                   │
│ scenarios.py             deterministic synthetic frames (always works)   │
│ agents 1–2               Detection, ANPR & Registry                      │
├─ INTELLIGENCE ──────────────────────────────────────────────────────────┤
│ agents 3–6               Evidence, Risk & Context, Predictive Safety,    │
│                          Fuzzy Decision                                  │
│ fuzzy.py                 20-rule Mamdani inference + explainability      │
│ decision.py              Safety Overlay, Evidence Gate, action matrix    │
├─ ACTION ────────────────────────────────────────────────────────────────┤
│ agents 7–8               Action & Notification, Explainability & Dispute │
│ messages.py              English / Roman Urdu / Urdu templates           │
├─ EMERGENCY & OPTIMISATION ──────────────────────────────────────────────┤
│ agents 9–10              Ambulance Priority, Traffic Optimisation        │
│ prediction.py            TTC proxy, corridor plan, signal plan           │
├─ COMPLIANCE ────────────────────────────────────────────────────────────┤
│ agents 11–12             Smart Compliance, Payment Recovery              │
│ penalty.py               progressive, capped late fees                   │
│ compliance.py            scoring, escalation ladder, two-key rule         │
├─ GOVERNANCE ────────────────────────────────────────────────────────────┤
│ legal.py                 prohibited capabilities, privacy defaults        │
│ config.py                versioned policy (fines, fees, timelines)        │
│ db.py                    SQLite + append-only audit trail                 │
└─────────────────────────────────────────────────────────────────────────┘
```

Dependencies point downward only. `fuzzy.py` knows nothing about challans;
`compliance.py` knows nothing about cameras. That is what makes each layer
testable in isolation and what makes the legal argument clean: a score is not an
entitlement to act.

## 2. Execution flow of one case

```
ScenarioSpec
   │
   ├─ build_event()        synthetic or real frames → CameraEvent
   ├─ build_history()      prior challans + sealed evidence bundles
   │
   ▼
AgentContext (shared state + append-only traces)
   │
   ├─ 1  Detection            event → primary violation
   ├─ 2  ANPR & Registry      plate → masked VehicleIdentity (0 network calls)
   ├─ 3  Evidence Verification frames → seal_evidence() → root hash + confidence
   ├─ 4  Risk & Context       policy tables → severity, density, context
   ├─ 5  Predictive Safety    kinematics → collision risk + TTC
   ├─ 6  Fuzzy Decision       inputs → RiskAssessment → decide() → Decision
   ├─ 7  Action & Notification Decision → Challan + ISSUED notice
   ├─ 8  Explainability       re-verify every bundle; cancel on integrity failure
   ├─ 9  Ambulance Priority   corridor plan (or NO_EMERGENCY_ACTIVE)
   ├─ 10 Traffic Optimisation signal plan + safety hold
   ├─ 11 Smart Compliance     profile → ladder back-fill → enforcement request
   └─ 12 Payment Recovery     quote → pay → withdraw request → RESOLVED
   │
   ▼
PipelineResult (immutable) + SQLite case file + agent traces
```

Agents run in a fixed order and share an `AgentContext`. `ctx.require(key)` raises
loudly if an agent reads state a predecessor has not written, so an ordering
regression fails immediately instead of silently producing a wrong number.

## 3. Agent contract

Every agent implements:

```python
class Agent:
    name: str
    level: int                      # 1..6, the layer it belongs to
    maturity: AgentMaturity         # deep | heuristic | mock

    def execute(self, ctx) -> tuple[str, Mapping[str, Any]]:
        """Return (human verdict, structured details)."""
```

`Agent.run()` wraps `execute` with timing and appends an `AgentTrace`. That gives
three things for free: a per-agent latency profile, a machine-readable record of
every decision input, and an honest maturity label printed next to each step.

**Maturity is a promise, not decoration.** `mock` means synthetic input with a
documented replacement seam. `deep` means a real algorithm with real tests:
evidence custody, fuzzy inference, dispute verification, compliance scoring.

## 4. Fuzzy inference

**Inputs** (0–100, validated — out-of-range values raise):

| Variable | Weight | Source |
|----------|--------|--------|
| `evidence` | 0.25 | cross-frame agreement from the evidence layer |
| `severity` | 0.25 | policy table, compounded for concurrent violations |
| `collision` | 0.20 | `prediction.estimate_collision_risk` |
| `density` | 0.15 | camera / loop detector |
| `context` | 0.15 | location tags: school, hospital, rush hour, night, rain… |

**Terms.** Inputs use trapezoids so "high" is fully true across its whole range
rather than peaking at one point — this matters because a triangular shoulder makes
the extremes of the scale weakest, which is backwards. Output terms are narrow
trapezoids; narrow consequents give the scale real resolution.

**Inference.** Minimum t-norm for rule firing, weight per rule, weighted
centre-average defuzzification over fired rules, with the centre of gravity
reported alongside as a reference.

**Explainability.** Every assessment returns the fired rules sorted by strength,
each input's share of total firing strength, and an independent policy-weighted
baseline. A divergence above 25 points flags the case for human review — a cheap,
effective sanity check that catches drift between the rule base and the policy.

**The Safety Overlay.** The rule base has a structural ceiling (documented in
`fuzzy.py`): CRITICAL rules are supersets of HIGH rules, so the soft score tops out
near 86. `decision.py` therefore promotes HIGH to CRITICAL when collision, severity
and density are simultaneously extreme, and prints the reason. Hard safety
constraints belong in policy, not in membership-function tuning.

**The Evidence Gate.** Two independent guards: nothing is penalised below 55%
confidence, and a serious allegation (severity ≥ 70) below 45% confidence is routed
to a human rather than a challan. Over-enforcement is modelled as a failure mode.

## 5. Evidence custody

```
frame bytes ──SHA-256──▶ per-frame digest
                              │
                    canonical JSON (sorted keys)
                              │
                         SHA-256 ──▶ root hash ──▶ stored on the challan
```

`verify_bundle()` recomputes everything from the frames currently held. Any byte
change, any removed frame, any reordering of the *content* breaks it — while
reordering the frame list itself does not, because frames are canonicalised by
index. The citizen dispute path is therefore arithmetic, not opinion: scenario 5
demonstrates a corrupted bundle being detected and the challan cancelled
automatically.

Plates are stored as salted HMAC digests for analytics, with plaintext retained
only for active cases.

## 6. Policy model

All numbers an authority would set live in one frozen `PolicyConfig`:

```
PolicyConfig
├─ base_fines / severity_scores / context_scores        per violation type, per location tag
├─ PenaltyPolicy        due_days, tranches, cap_multiplier, early discount, plans
├─ EscalationPolicy     stage ladder, channels, approval flags, two-key thresholds
├─ ComplianceWeights    per-factor deductions with caps, tier boundaries
├─ SafetyOverlay        extreme-combination thresholds
└─ EvidenceGate         minimum confidence thresholds
```

Each carries its own `policy_version`, stamped on every challan, notice and
profile. Nothing is hard-coded in logic.

## 7. Escalation and the two-key rule

```
day   0  ISSUED               challan + evidence bundle + explanation
day   7  REMINDER_1           SMS + WhatsApp, payment link, early-payment discount
day  15  REMINDER_2           adds an Urdu voice note, offers a payment plan
day  25  FINAL_NOTICE         states the late-fee ladder and the right to dispute
day  60  ENFORCEMENT_REQUEST  ← requires elapsed time AND compliance score ≤ 40
         AUTHORITY_REVIEW       a named human officer decides (never automatic)
         RESOLVED              paid, cancelled, or otherwise closed
```

The ladder back-fills with **historically correct timestamps**, so a 127-day-old
case produces a genuine audit trail rather than six notices arriving in one second.
Reminders always reference the vehicle's *oldest* open case — the case actually
being escalated.

An `EnforcementRequest` is a draft packet: status
`PENDING_AUTHORITY_APPROVAL`, `simulation=True`, named approval chain, cooling-off
window, and an `assert_not_executable()` guard. Payment withdraws it automatically.

## 8. Deliberate exclusions

| Not implemented | Why | Roadmap |
|-----------------|-----|---------|
| Trained trajectory model (LSTM/GNN) | A trained model with no labelled data is a liability; the transparent TTC proxy is honest and replaceable | 180 days |
| RAG over the legal corpus | Guideline retrieval needs a maintained, authoritative corpus and legal review | 90 days |
| PostgreSQL / TimescaleDB / Redis / Celery | SQLite plus a narrow `Store` interface carries the demo; infra adds deployment risk without changing the story | 90 days |
| RL signal control | Needs a simulator and a live signal controller; the advisory plan is the honest version | 180 days |
| Driver biometric identification | Legally radioactive in Pakistan; registered-owner liability is both lawful and sufficient | never |
| Any real government integration | No authority, no mandate, no data-sharing agreement | only under authority |

## 9. Testing strategy

| Area | Tests | What they protect |
|------|-------|-------------------|
| `test_fuzzy.py` | geometry, shoulders, rule-base integrity, reachability, monotonicity, validation | the engine cannot silently empty or invert |
| `test_evidence.py` | seal, verify, tamper, truncate, reorder, confidence, hashing | evidence is tamper-evident |
| `test_penalty.py` | windows, tranches, cap arithmetic, monotonicity, plans | penalty numbers are predictable and the cap binds |
| `test_compliance.py` | proportionality caps, two-key rule both ways, inert requests, ladder | no single factor dominates; enforcement needs two keys |
| `test_legal.py` | every blocked capability raises, masking, zero network | the legal boundary is real |
| `test_agents.py` | structure, ordering, traces, failed state access | the pipeline fails loudly, not silently |
| `test_scenarios.py` | all five outcomes, the full recovery arc, anti-false-positive invariant | the demo tells the story it claims |
| `test_cli.py` | every subcommand exits 0 **and prints output**, `--urdu`, error paths | no command silently prints nothing (two real bugs, both stage-fatal) |
| `test_db.py` | round-trip, upsert, audit order, stats, file persistence | the case file is trustworthy |

Three tests exist specifically as regressions for bugs found during development:
the membership-function shoulders, the dead penalty cap, and the non-monotone rule
base. `test_cli.py` exists because two CLI bugs were invisible to unit tests: a
command that printed a Python list, and a command that printed nothing at all.
See section 7 of the [README](../README.md).

`test_scenarios.py::test_detection_never_issues_a_challan_without_evidence` is the
guard rail worth protecting above all others: **no scenario may ever produce a
challan below the confidence gate.** If a future change breaks it, the suite fails.
