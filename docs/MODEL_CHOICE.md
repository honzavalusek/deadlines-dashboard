# Model choice

## Where the model choice came from

**Opus extracts, Sonnet ranks.** That is not where this started, and the way it
changed is the point.

The original argument was that reaching for the largest model is the opposite of
using a reasoning model *optimally*, so both stages ran on Sonnet — extraction at
`medium`, ranking at `high`, on the theory that stage 1 holds the subtler
reasoning and stage 2 only ranks an already-clean table.

Half of that survived measurement. The other half did not.

`scripts/eval_models.py` scores each configuration against the fixture's
known-correct answers, three runs each, because one run cannot separate a real
difference from output variance:

| Configuration | Checks passing in **every** run |
|---|---|
| **opus-5 extract @ high** *(shipped)* | **19/20** |
| sonnet-5 @ medium/high *(the original default)* | 17/20 |
| sonnet-5 @ low/medium *(cheaper still)* | 17/20 |

Two results changed the design:

- **Sonnet extraction loses two behaviours outright, 0/3 at both effort levels.**
  It never extracts the `someone_else` commitment from `acme-dpa`, so the "Not
  yours" panel stays empty; and it never extracts the blocked, dateless
  commitment from `eng:pricing-copy`. Opus gets both, 3/3. These are not
  borderline scores — they are two of the fixture's showcase cases silently
  producing nothing.
- **The effort split earned nothing.** Sonnet at medium/high and at low/medium
  score identically. The original config spent effort where it could not be
  measured to matter, so the surviving claim is about the *model*, not the knob.

Stage 2 stayed on Sonnet, and that half held up: ranking a clean table is well
within its range, and escalating it changed nothing measurable.

**Haiku for extraction remains a false economy** for a different reason: `effort`
is unsupported on it and thinking still needs the old `budget_tokens` shape, so
it would mean a second request shape in the adapter for no real gain.

The honest summary is that the eval overturned the assumption it was built to
support. That is what it was for.

---

## The fixture is deliberately adversarial

27 messages across 13 threads. Every thread has exactly one job:

| Thread | Case | Correct behaviour |
|---|---|---|
| `legal-ops:msa-redlines` | explicit date, high stakes | baseline |
| `product:roadmap-deck` | **relative date + supersession** | ONE commitment, `moved`, Fri → Mon, chain recorded |
| `acme-security-questionnaire` | **cancellation** | `cancelled`, struck through, no action |
| `uohs-filing` | **statutory, furthest out** | outranks everything due sooner |
| `eng:pricing-copy` | **blocked, no date** | no invented deadline; `blocked_by` set |
| `general:chitchat` | **pure noise** | zero commitments + a specific reason |
| `board-pack` | **conflicting dates, never resolved** | `low` confidence, both candidates shown, action is "ask" |
| `dm-lucie:finance` | **overdue + already done, same thread** | two commitments, one overdue, one `done` |
| `pricing:launch-copy` | **`my_team`, passive voice, no owner** | on the board, tagged "your project" |
| `acme-dpa` | **`someone_else`** | audit panel, not the board |

Cross-cutting: two deliberate rank inversions, every bucket non-empty, all three
`audience` values, Czech vocative address ("Honzo") to exercise alias resolution,
and one thread that code-switches mid-sentence ("musíme to shipnout do pátku").

An adversarial fixture is the point. A happy-path fixture proves nothing, and a
claim a reviewer cannot check is a claim they will discount.

**The same fixture is the test oracle.** `tests/fakes.py` encodes what a
correct analysis of each thread looks like, so it is simultaneously the test
double the suite runs against and the expected-answers table the real engine
is scored against.

---

## Evaluation

`scripts/eval_models.py` runs the fixture through a real engine and diffs the
result against those expectations — 20 checks covering supersession, cancellation,
over-extraction, all three audience values, ambiguity handling, relative-date
resolution, the citation guards, output language, and both rank inversions.

`--sweep` compares the shipped default against two cheaper Sonnet
configurations. `--repeat N` runs each configuration N times and reports
per-check pass rates instead of one score, since output varies between runs. A
check passing 3/3 is evidence; 2/3 is flaky — itself a finding.

```bash
.venv/bin/python scripts/eval_models.py --sweep --repeat 3
```

### Measured

Three configurations, three runs each, against the live API.

| Configuration | Stable | Failing checks | Extract latency |
|---|---|---|---|
| **opus-5 extract @ high** *(shipped)* | **19/20** | `language/tasks-english`\* | ~25 s |
| sonnet-5 @ medium/high | 17/20 | `audience/someone_else` 0/3, `nodate/left-null` 0/3, `language`\* flaky | ~18 s |
| sonnet-5 @ low/medium | 17/20 | same two, 0/3 each; `cancel/detected` 2/3† | ~15 s |

\* **This failure was a bug in the check, not the model.** It flagged
`"Send the Q3 board pack to Eva Marešová"` — English task text whose only
non-ASCII character is a person's name. Opus failed it *more often* precisely
because it writes better tasks, naming the recipient. The check now exempts
proper nouns while still catching a sentence-initial Czech verb. The numbers
above are as measured, before that fix; with it, the two Sonnet rows read 18/20
and the Opus row 20/20. Those corrected figures are inferred, not re-measured —
the sweep has not been re-run since.

It cannot catch diacritic-free Czech ("Dodat podklady"), and no diacritic
heuristic can. Stated rather than papered over.

† One run failed with a live `400 Grammar compilation timed out` from the
structured-output API while extracting one thread. Worth recording for two
reasons: the schema is complex enough to occasionally hit that ceiling, and the
pipeline degraded exactly as designed — one thread became a warning on the board
instead of blanking the whole run.
