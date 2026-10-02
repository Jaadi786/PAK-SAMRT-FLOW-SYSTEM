# Roles, ownership and the seven-day plan

Six roles. If you have four people, merge Vision into Decision and Traffic into
Backend — but **keep the Demo Lead separate**. Hackathons are won on storytelling,
not on lines of code.

---

## The roles

### 1. Lead / Integrator

**Owns:** the interfaces, the end-to-end run, and the merge.

- Freezes the interfaces in week-zero: `CameraEvent` in, `PipelineResult` out
- Owns `pipeline.py` and `agents.py` ordering
- Runs `python -m unittest discover -s tests -t .` before every commit
- Authority to say "no" to scope

**Definition of done:** `python -m smartflow demo --all` runs clean on a laptop that
has never seen the repository.

---

### 2. Vision Engineer

**Owns:** agents 1–2, and `vision/yolo_adapter.py`.

- YOLOv10 for vehicle/helmet/violation classes; ANPR via EasyOCR or Tesseract
- Produces `CameraEvent` objects — and nothing else
- Must not block anyone: the synthetic path in `scenarios.py` is the fallback and
  stays working at all times

**Definition of done:** a real image file becomes a `CameraEvent` with a sealed
evidence bundle, and the rest of the pipeline is unchanged.

**Hard rule:** no driver face recognition. Ever. See the legal boundary below.

---

### 3. Decision Engineer

**Owns:** agents 3–6, `fuzzy.py`, `decision.py`, `evidence.py`, `prediction.py`.

- Owns the rule base, the membership functions, and their calibration
- Owns the monotonicity tests — a score that falls when danger rises is a bug
- Owns the evidence chain of custody
- Must be able to explain any score in sixty seconds, out loud, without the laptop

**Definition of done:** `python -m smartflow fuzzy` produces a calibration table you
can defend, and every scenario's score is reproducible from the spec.

---

### 4. Agents / Messaging Engineer

**Owns:** agents 7–9 and `messages.py`.

- Challan generation and the issuance notice
- Trilingual templates: English, Roman Urdu, Urdu script — all three, from one source
- Urdu voice note via Edge-TTS into a real audio file to play on stage
- Optional Groq wording, with the deterministic template as the fallback

**Definition of done:** a citizen notice exists in three languages, and an actual
Urdu audio file plays during the demo.

**Hard rule:** a failed network call may never prevent a notice from being produced.

---

### 5. Backend & Compliance Engineer

**Owns:** agents 11–12, `compliance.py`, `penalty.py`, `db.py`, `integrations.py`.

- Compliance scoring, penalty arithmetic, the escalation ladder
- The mock NADRA and payment adapters, with **zero** network calls
- The append-only audit trail
- The two-key rule: time **and** score, never one alone

**Definition of done:** scenario 4 runs end to end, and the audit trail shows the
full 127-day history with correct timestamps.

---

### 6. Demo & Story Lead

**Owns:** the deck, the script, the rehearsal, the backup video, the clock.

- Builds the deck from `docs/PPT_OUTLINE.md`
- Writes and times the script from `docs/DEMO_SCRIPT.md`
- Records the backup video on **day 5**, not day 7
- Runs three full rehearsals and cuts whatever overruns
- Prepares the Q&A answers and the numbers sheet

**Definition of done:** the 7-minute run happens twice in a row without notes, and
the backup video exists and plays.

**This role is not optional and is not a spare-time job.**

---

## Interfaces (freeze these on day 1)

| Produced by | Object | Consumed by |
|---|---|---|
| Vision | `CameraEvent` | Evidence, Risk & Context |
| ANPR | `VehicleIdentity` | Action, Compliance |
| Evidence | `EvidenceBundle` (root hash, confidence) | Decision, Dispute, Challan |
| Decision | `RiskAssessment` + `Decision` | Action, Explainability |
| Compliance | `ComplianceProfile` | Enforcement, Payment |
| Enforcement | `EnforcementRequest` (always inert) | Report, UI |

Nobody changes an interface without telling the Lead. That single rule prevents the
classic day-6 integration collapse.

---

## Seven-day plan

| Day | Lead | Vision | Decision | Messaging | Backend | Demo |
|---|---|---|---|---|---|---|
| **1** | Repo, interfaces, CI script | Dataset + YOLO env | Rule base draft + tests | Notice templates (3 languages) | SQLite schema + mocks | Deck skeleton from outline |
| **2** | Wire agents 1–6 | Detector → `CameraEvent` | Fuzzy engine + monotonicity tests | Challan PDF + notices | Penalty engine + tests | Slide 4–7 drafts |
| **3** | Wire agents 7–12 | ANPR + evidence frames | Evidence custody + dispute path | Urdu voice note | Compliance scoring + ladder | Slide 8–9 drafts |
| **4** | Full pipeline green | Real footage dry run | Calibration + calibration table | Groq wording (optional) | Mock NADRA + payments | Slide 10–13 drafts |
| **5** | End-to-end on a clean machine | Fallback path verified | Safety Overlay + Evidence Gate | Audio plays on stage | Audit trail verified | **Record the backup video** |
| **6** | Bug bash, all tests pass | — | Edge cases | Wording review | Data integrity check | Rehearsal 1 + 2, cut content |
| **7** | Freeze. No new features. | — | Freeze | Freeze | Freeze | Rehearsal 3, 10-minute buffer |

**Day 7 has no development in it.** If something is not finished by the end of day 6,
it is not in the demo — it becomes a roadmap slide.

---

## If you fall behind, cut in this order

1. Streamlit dashboard → the CLI tells the same story
2. Real detector → synthetic frames are honestly labelled `mock` anyway
3. Urdu voice audio → keep the Urdu *text*, drop the audio
4. Traffic optimisation agent → one less advisory in the trace
5. Scenario 3 (ambulance) → 4 scenarios is still a strong demo

**Never cut:**

- Scenario 4 (the compliance loop) — it is the entire differentiator
- Scenario 5 (the false positive) — it is your credibility
- The legal boundary slide and the `probe` command
- The maturity labels in the agent trace
- The backup video

---

## The three decisions to settle on day 1

1. **Who owns each of the six roles, by name?** Write the names on the deck's title slide.
2. **Which scenario leads the demo?** Recommendation: scenario 4, with scenario 5 as
   the credibility beat immediately after.
3. **Who is on stage, and who drives the keyboard?** One person talks; one person
   types. Never the same person, and never two people talking.

---

## Ground rules

- **Commit to `main` at least twice a day.** A merge conflict at hour 60 is a real
  risk, not a theoretical one.
- **Tests pass before merge.** The suite is fast; there is no excuse.
- **The synthetic path always works.** If a feature can break the demo offline, it
  needs a fallback.
- **No new dependencies after day 4.** Dependency installs are the most common cause
  of a dead stage laptop.
- **No invented numbers.** If you did not measure it, say "on the roadmap with a
  published methodology". Judges check.
- **No driver biometrics, ever.** It is a legal hazard, and registered-owner
  liability is both lawful and sufficient.
