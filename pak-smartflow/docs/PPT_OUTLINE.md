# Slide deck outline

13 slides. Every number below was measured from this codebase — put the real
numbers on the slides, never a rounder-looking fiction. Build the deck from this
file in one sitting.

Design rules for the deck:

- One idea per slide, ≤ 6 bullets, ≥ 24pt body text
- Every number on a slide must be reproducible with a command on the slide notes
- No stock photos of traffic. Use your own screenshots of the actual terminal output
- Put the 3-second version of each slide in the title, so the deck reads correctly
  even if you are cut off

---

## Slide 1 — Title

**Pak-SmartFlow: from challan generation to compliance resolution**

- Subtitle: *Challan banane ke baad kya hota hai?*
- Team name, members, contact
- One line: "A working reference prototype. 12 agents, 187 tests, zero dependencies."

> **Notes:** Open with the question, not the tech. The question is the whole pitch.

---

## Slide 2 — The gap

**Everyone can issue a challan. Nobody finishes the job.**

| Existing systems | Pak-SmartFlow |
|---|---|
| Detect → Challan → *nothing* | Detect → Verify → Score → Explain → Challan → Notify → Escalate → Review → Recover → **Resolve** |

- 80% of the story happens *after* the challan
- No follow-up, no compliance tracking, no dispute path, no closure

> **Notes:** Do **not** put a non-payment percentage on this slide unless you have a
> source you can cite. If you have one, cite it in 10pt at the bottom. If you do not,
> say "we did not measure it; it is on our roadmap with a published methodology."
> Judges reward that answer far more than a made-up statistic.

---

## Slide 3 — The four unanswered questions

1. What happens when the challan is **not paid**?
2. What happens when the evidence is **wrong**?
3. What does the citizen **actually receive**?
4. Who is **allowed** to do what?

> **Notes:** This is the spine of the pitch. Refer back to it on slides 6 and 8.

---

## Slide 4 — Architecture

**6 layers, 12 agents, one shared case context**

```
PERCEPTION      Detection · ANPR & Registry
INTELLIGENCE    Evidence · Risk & Context · Predictive Safety · Fuzzy Decision
ACTION          Action & Notification · Explainability & Dispute
EMERGENCY       Ambulance Priority
OPTIMISATION    Traffic Optimisation
COMPLIANCE      Smart Compliance · Payment Recovery
```

- Maturity labelled in code and printed per run: `deep` / `heuristic` / `mock`
- 4 agents are `deep` (real algorithm + tests), 5 `heuristic`, 3 `mock`

> **Notes:** The maturity labels are your credibility. Show one screenshot of the
> trace with the labels visible. Nobody else in the room will have done this.

---

## Slide 5 — The fuzzy decision engine

**Five inputs, twenty rules, and it tells you why**

| Input | Weight | Example |
|---|---|---|
| Evidence confidence | 25% | 100 |
| Violation severity | 25% | 88 |
| Collision risk | 20% | 52 |
| Traffic density | 15% | 60 |
| Context factor | 15% | 58 |

- → **Score 83.2 / 100 → HIGH → challan + safety alert + patrol hint**
- Weighted centre-average defuzzification; centroid shown as a reference
- Every run prints the fired rules *and* each input's contribution

> **Notes:** If you have a laptop, run `python -m smartflow demo 1` here and let the
> rule list scroll. This slide is the one that makes engineers lean forward.

---

## Slide 6 — The Safety Overlay (the honest engineering slide)

**A soft score recommends. A hard overlay guarantees.**

- Every CRITICAL rule is a *superset* of a HIGH rule → its firing strength can never
  exceed it → the soft score tops out near **86/100**
- We documented that instead of tuning it away
- When collision, severity and density are **all** extreme, HIGH is promoted to
  CRITICAL, **and the promotion prints its own reason**

| Scenario 2: wrong-way, 92 in a 60 zone, school, rush hour | |
|---|---|
| Fuzzy score | **88.1** |
| Verdict after overlay | **CRITICAL** |
| Actions | challan, immediate safety alert, patrol hint, signal review, human review |

> **Notes:** Do not rush this slide. "We found a structural limit in our own engine,
> documented it, and put the hard guarantee in policy where it belongs" is the single
> most senior thing anyone will say today.

---

## Slide 7 — Evidence you can defend in a dispute

**Chain of custody, in 60 lines of code**

```
4 frames ──SHA-256──▶ 4 digests ──canonical JSON──▶ root hash ──▶ stored on the challan
```

- Any single changed byte anywhere breaks the root hash
- Re-verification is arithmetic, not opinion
- Scenario 5: a corrupted bundle → **challan cancelled automatically**, citizen told why
- Plates stored as salted HMAC digests; raw images retained 7 days

> **Notes:** This answers "what happens when the citizen disputes the photo?" before
> it is asked. It is the detail evaluators remember.

---

## Slide 8 — The differentiator: compliance resolution

**Scenario 4 — eight ignored challans, 127 days, then the ninth violation**

| Step | Value |
|---|---|
| Compliance score at escalation | **11.2 / 100 — SEVERE** |
| Escalation ladder back-filled | day 7, day 15, day 25 (real timestamps) |
| Enforcement Request | prepared, `PENDING_AUTHORITY_APPROVAL`, `simulation=True` |
| Two-key rule | ≥ 60 days **AND** score ≤ 40 — either alone earns only a reminder |
| Citizen pays | 9 challans, PKR 12,700 (oldest capped at PKR 1,750) |
| Final compliance score | **100 / 100 — COMPLIANT** |

**11.2 → 100. That movement is the product.**

> **Notes:** This is your win slide. Spend the most time here. Read the score
> movement out loud, twice.

---

## Slide 9 — It admits its own mistakes

**Scenario 5 — a false positive and a citizen appeal**

- 1 of 3 frames agrees → confidence below the gate → **no challan issued**
- Routed to a human reviewer instead of penalising the owner
- A separate tampered bundle fails re-verification → **the system cancels its own challan**
- A test asserts *no scenario may ever issue a challan below the confidence gate*

> **Notes:** "An enforcement system that cannot admit error is not trustworthy."
> Then: "and this is a live command, not a slide — watch."

---

## Slide 10 — The legal boundary

**Enforced in code, not promised in a deck**

| ❌ Never | ✅ Instead |
|---|---|
| Block a real CNIC / passport | Prepare an Enforcement Request for human review |
| Freeze a bank account | Offer a payment plan in the mock gateway |
| Block a SIM | Send a compliance reminder |
| Auto-deduct funds | Mock transaction; the citizen initiates |
| Identify the driver by face | Registered-owner liability only |

```bash
python -m smartflow probe     # attempts all four; prints the clean refusal for each
# Prohibited operations that succeeded: 0
# Network calls made to any external system: 0
```

> **Notes:** Then say the sentence verbatim:
> *"Our prototype demonstrates how an authorized government ecosystem could
> technically coordinate these workflows, subject to applicable law, policy,
> security, and human/authority approval."*

---

## Slide 11 — Verification

**187 tests. Zero third-party imports. No network. Ten-second setup.**

| Property | Value |
|---|---|
| Tests passing | 187 (`python -m unittest discover -s tests -t .`) |
| Invariant checks | 14 / 14 (`python -m smartflow selftest`) |
| Third-party imports in the core | **0** (verified by inspecting `sys.modules`) |
| Network calls in a full run | **0** |
| Core / test size | ~5 300 / ~1 900 lines |

**Bugs our tests caught before the demo did:** a membership-function shoulder that
silently emptied the rule base at the extremes, a rule that made the score *fall* as
severity rose, and a penalty cap that could never once execute.

> **Notes:** The bug list is the strongest slide in the deck for a technical audience.
> It proves the tests were written to find problems, not to decorate a repository.

---

## Slide 12 — Impact and scale

**What we would measure in a real trial, and how**

| Metric | Baseline | Target | Method |
|---|---|---|---|
| Payment rate | measure | ↑ | paid ÷ issued, per 30-day cohort |
| Time to resolution | measure | ↓ from months to days | issue → `RESOLVED` |
| False-positive rate | measure | ↓ | disputes upheld ÷ challans issued |
| Compliance score recovery | — | ↑ | SEVERE cases reaching COMPLIANT |
| Cost per resolved case | measure | ↓ | infrastructure + officer time ÷ resolved |

- 1 camera → 1 000 cameras: the decision path is sub-millisecond Python; cost lives in edge inference
- Deployment: on-premise, authority-owned, no citizen data leaves the jurisdiction

> **Notes:** Say plainly that the baselines are not measured yet. A credible
> measurement plan beats an invented improvement percentage.

---

## Slide 13 — Roadmap and ask

| Horizon | Work |
|---|---|
| 30 days | Real detector on 1–2 cameras; calibrate the rule base on labelled footage |
| 90 days | PostgreSQL + immutable audit log; citizen app; one traffic-police unit trial |
| 180 days | Multi-city, per-province policy, trained trajectory model, published metrics |

**The ask:** one camera feed and one traffic-police liaison for a 90-day pilot.

- Repo: `<your URL>` · Contact: `<your email>`

> **Notes:** Close on the ask, not on a thank-you slide. A specific, small, grantable
> request converts interest into a next meeting.

---

## Backup slides (keep them behind the main deck)

1. **Full rule base** — all 20 rules with weights (`python -m smartflow fuzzy`)
2. **Penalty arithmetic** — the tranche table, the cap, the early discount
3. **Compliance score derivation** — every component with its cap
4. **Escalation ladder** — stage, day, channel, approval flag
5. **SQLite schema** — the audit trail tables
6. **Roadmap replacements** — exactly which model replaces which heuristic
7. **The nine bugs** — the full table from the README, if asked about testing
