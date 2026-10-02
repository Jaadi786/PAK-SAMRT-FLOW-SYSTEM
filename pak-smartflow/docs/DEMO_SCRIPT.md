# Demo script

**Total: 7 minutes.** Rehearse it three times. Record it once. Never demo live
without the recording.

---

## Pre-flight (do this 10 minutes before)

```bash
cd pak-smartflow
python -m unittest discover -s tests -t .    # must be exit 0
python -m smartflow selftest                 # must be 14/14
python -m smartflow demo 4 --db demo.sqlite  # must print RUN SUMMARY with no error
```

- [ ] Terminal font ≥ 16pt, dark background, window maximised
- [ ] `python -m smartflow demo 1` already run so scrolling is warm
- [ ] Backup video open in a second tab, paused at 0:00
- [ ] `demo.sqlite` present so the citizen-portal step has data
- [ ] Phone on silent, notifications off, second monitor disconnected
- [ ] `--urdu` flag to hand if a judge asks about localisation

---

## 0:00 — The gap (45 s)

> "Every smart-enforcement system in the region is excellent at one thing: turning a
> camera into a challan. None of them answers the next question. Challan banane ke
> baad kya hota hai? Our prototype answers it — and it answers it with running code,
> not slides."

Say the four questions out loud. They are the spine of the whole pitch:

1. What happens when the challan is **not paid**?
2. What happens when the evidence is **wrong**?
3. What does the citizen **actually receive**?
4. Who is **allowed** to do what?

---

## 0:45 — Scenario 1: the boring path (45 s)

```bash
python -m smartflow demo 1
```

While it runs, point at the **agent trace**: twelve agents, each with a maturity
label — `mock`, `heuristic`, `deep`.

> "We label our own maturity honestly. Detection is a mock; the fuzzy engine,
> evidence custody, dispute verification and compliance scoring are real, and they
> have tests."

Then the fuzzy block:

> "Score 83.2, HIGH. Here is *why*: the rules that fired, each input's contribution,
> and an independent weighted baseline of 74.1 as a sanity check. If a citizen asks
> why they were fined, this is the answer, and it is not a black box."

---

## 1:30 — Scenario 2: the Safety Overlay (60 s)

```bash
python -m smartflow demo 2
```

> "Wrong-way driving at 92 in a 60 zone, outside a school, at rush hour. Score 88.1.
> But watch — the soft score alone cannot reach CRITICAL, and we say so in the code.
> Every CRITICAL rule is a superset of a HIGH rule, so its firing strength can never
> exceed it. Rather than fudge the membership functions, we added a hard Safety
> Overlay, and it prints its reason."

Read the overlay line from the rationale. Then:

> "This is the engineering judgement we want you to notice: a soft score recommends,
> a hard overlay guarantees. And the recommendation is not just a fine — it is a
> safety alert, a patrol hint and a signal review."

---

## 2:30 — Scenario 4: **the differentiator** (2 min 30 s)

```bash
python -m smartflow demo 4 --urdu
```

This is the scenario that wins or loses the room. Walk it slowly.

**(a) Prior history.** Point at the eight challans, oldest 127 days.

> "An existing system would have issued these eight and stopped. Watch what happens
> to a vehicle with a history."

**(b) Compliance profile.**

> "Compliance score 11.2 out of 100, tier SEVERE. And here is the derivation, factor
> by factor, each one capped so no single item can dominate. Proportionality is
> enforced in code."

**(c) The escalation ladder.**

> "The reminders are back-filled with the timestamps they *would* have had — day 7,
> day 15, day 25. This is a real 127-day audit trail, not six notices in one second."

**(d) The enforcement request.** Read the status line out loud:

> "Status `WITHDRAWN_ON_PAYMENT`. And before that, it was
> `PENDING_AUTHORITY_APPROVAL` with `simulation=True`. This object cannot be
> executed. There is a method called `assert_not_executable()` and a test that
> proves it raises."

Then the two-key rule:

> "It took two keys to get here: 60 days elapsed **and** a compliance score under 40.
> Either alone only earns a reminder. We never escalate on time alone, and never on
> score alone."

**(e) The payment.**

> "Now the citizen pays. Nine challans, PKR 12,700 including late fees — and note
> the flat PKR 1,750 cap on the oldest one, so nothing accrues beyond the ceiling."

**(f) The movement.** Point at the score-movement block:

> "11.2 SEVERE → 100 COMPLIANT. **This movement is the product.** The system does not
> just issue a challan; it drives the case to a closed, paid, compliant state. That
> is the whole thesis of the project in one number."

**(g) The citizen's actual experience.**

> "And this is what the citizen received, in Urdu — not an English legal notice."

Show the Urdu notice.

---

## 5:00 — Scenario 5: admitting error (60 s)

```bash
python -m smartflow demo 5
```

> "One of three frames agrees. Confidence is below the gate, so we issue **no
> challan**. The case goes to a human instead."

Then the dispute:

> "Separately, an older challan's evidence bundle fails re-verification. The system
> cancels its own challan, tells the citizen why, and records it in the audit trail.
> An enforcement system that cannot admit error is not trustworthy. We think this is
> the most important slide in the deck — and it is a live command, not a slide."

---

## 6:00 — The legal boundary (45 s)

```bash
python -m smartflow legal
python -m smartflow probe
```

> "We do not block CNICs. We do not freeze accounts. We do not read faces. These are
> not promises on a slide — they are methods that always raise."

`probe` attempts all four live and prints the clean refusal for each, then reports
zero successful prohibited operations and zero network calls. Close with the
sentence, **verbatim**:

> "Our prototype demonstrates how an authorized government ecosystem could
> technically coordinate these workflows, subject to applicable law, policy,
> security, and human/authority approval."

---

## 6:45 — Close (15 s)

> "187 tests, zero third-party dependencies, no network calls. Clone it and run it on
> your laptop in ten seconds. We did not build a demonstration — we built the
> reference implementation."

---

# Q&A preparation

## The three hardest questions

**Q: "Where is your real data? These are synthetic frames."**
> "Correct, and we label it in the code: detection and ANPR are `mock` maturity and
> the trace says so on every run. What is real is everything downstream of the
> camera — evidence custody, the decision engine, the compliance ladder. Those are
> what we are claiming, and those are tested. Real footage plugs into exactly one
> file, `vision/yolo_adapter.py`, and the evidence layer never learns the
> difference."

**Q: "Who gives you the authority to do any of this?"**
> "Nobody, and we do not assume it. The system prepares a draft packet; a named human
> officer decides. We excluded driver biometrics entirely and use registered-owner
> liability, which is what the law actually does. The enforcement object is inert by
> construction."

**Q: "Isn't this just a challan app with extra steps?"**
> "A challan app ends at `ISSUED`. Ours ends at `RESOLVED`, and it prints the movement
> from SEVERE to COMPLIANT. Show me another system that reports its own compliance
> recovery rate."

## Questions to expect, with short answers

| Question | Answer |
|----------|--------|
| "What if the AI is wrong?" | Two evidence gates block a challan below 55% confidence; a serious allegation on weak evidence goes to a human; the dispute path cancels the challan automatically and the audit trail records why. Scenario 5 demonstrates it. |
| "How accurate is the fuzzy engine?" | Fuzzy logic encodes expert judgement, it does not learn from data. Accuracy is a policy-calibration question: change `config.py`, and swap the rule base for a trained model behind the same interface once you have labelled data. |
| "Why fuzzy and not just a weighted sum?" | Because thresholds are not linear. "High evidence AND serious violation" is a *rule*, not a sum, and rules can be read back to a citizen. The engine prints every rule that fired. |
| "Can it scale to 1,000 cameras?" | The decision path is a few hundred microseconds of pure Python; the cost is vision inference at the edge. `db.py` is a narrow interface designed to swap for PostgreSQL. We have not load-tested 1,000 cameras and will not claim we have. |
| "What about privacy?" | 30-day evidence retention, 7-day raw images, plates hashed with a salted HMAC for analytics, no driver biometrics, append-only audit trail, citizen access to their own bundle. |
| "How do you handle false positives at scale?" | They are treated as a first-class failure mode: an evidence gate, an automatic dispute path, and a test asserting no scenario may ever issue a challan below the confidence threshold. |
| "What stops the provincial government from misusing it?" | Nothing in software can. What we can do is make misuse visible: every state change is attributed to an actor in an append-only log, and enforcement requires two keys plus named human approval. |
| "Cost per case?" | Not measured. It is on the 180-day roadmap with a published methodology rather than a guess in a pitch. |

## If the demo breaks

1. Switch to the backup video immediately. Do not debug on stage.
2. Say: "Let me show you the recorded run, then I'll show you the code."
3. If a judge wants proof it is live, run `python -m smartflow selftest` — it is fast
   and prints 14 lines.

The CLI has no dependencies, no network and no model weights, so the realistic
failure modes are a wrong working directory or a mistyped scenario number. Both are
recoverable in five seconds — and the backup video covers everything else.
