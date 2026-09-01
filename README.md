# Deadlines Dashboard

An AI deadline radar over Slack and email. It reads a person's conversations,
works out what they are **actually on the hook for** and by when, and renders a
prioritised board.

Slack and email ingestion are faked with seed fixtures. The reasoning is real.

---

## The idea

Finding dates in text is not the problem. A regex finds `2026-09-10`. The problem
is everything around the date, and all three of these need judgment rather than
rules:

**Relative dates.** "do pátku" means nothing until you know which day the message
was written. The same two words in two messages three days apart can mean the
same Friday or different ones.

**A thread is one story.** A deadline that is set, pushed to Monday, then pushed
again is **one commitment that moved twice** — not three tasks. One that gets
called off is one commitment that is **cancelled**, and it should visibly
disappear. Showing that the system correctly *removes* work is more convincing
than showing it finds work, and it is the thing a naive implementation cannot
do at all.

**Priority is comparative.** A statutory filing due in eight days outranks a
blog-image chore due tomorrow. No amount of scoring items one at a time produces
that ordering — it needs the whole set in one context.

And one that turned out to matter as much as any of them:

**"Is this even mine?"** A board full of other people's tasks is worse than no
board. That judgment is three-way, not binary — see below.

---

## What it looks like

The board groups by date, but orders by judgment *within* each group, and repeats
the global order in a strip at the top:

```
HIGHEST PRIORITY — ordered by judgment, not by date
  CRITICAL  Send the MSA redlines back to our counsel          Thu 3 Sep
  CRITICAL  Finalise the copy for the pricing page             Fri 4 Sep
  CRITICAL  File the ÚOHS submission for the public tender     Thu 10 Sep

OVERDUE 1
  [slack] Submit the August expense report
          Fri 21 Aug · 12 days ago   medium confidence          HIGH   [Done]
          Already twelve days overdue and blocking someone else's month-end close.
          → Submit it — it is fifteen minutes of work.

TODAY 1
  [outlook] Deliver the Q3 board pack to the CFO
          Wed 2 Sep · today   low confidence   or Fri 4 Sep?    HIGH   [Done]
          Might be due today — the date was never agreed.
          → Ask the CFO to confirm 2 vs 4 September before doing anything else.

LATER 2
  [outlook] File the ÚOHS submission for the public tender
          Thu 10 Sep · in 8 days                            CRITICAL   [Done]
  [slack] Prepare the roadmap deck for the QBR
          Mon 7 Sep · in 5 days   moved from Fri 4 Sep        MEDIUM   [Done]
```

The two rank inversions are the point. The ÚOHS filing is the **furthest away**
and ranks **first**, because it is statutory and cannot be extended. The blog
alt-text task is due **tomorrow** and ranks **last**, because its own requester
said it was not urgent. A date sort gets both backwards.

Every card carries a Slack or Outlook button. Hovering it opens the original
message — in Czech — alongside the quote the claim rests on. So every English
sentence on the board is one hover from its source.

---

## Architecture

```
              ┌─────────────────────────────────────────┐
   browser ──▶│ api/   routes · deps · session auth     │
              └────────────────┬────────────────────────┘
                               ▼
              ┌─────────────────────────────────────────┐
              │ services/  radar (pipeline) · dashboard │
              └───┬─────────────────────────────┬───────┘
                  ▼                             ▼
    ┌──────────────────────────┐   ┌─────────────────────────────┐
    │ db/repositories.py       │   │ domain/ports.py             │
    │ concrete, SQLAlchemy     │   │ CommitmentEngine (Protocol) │
    └──────────────────────────┘   └──────────────┬──────────────┘
                                                   ▼
                                          claude_engine.py

    domain/{models,scoring,dates,validation}.py — pure. No I/O, SQL or HTTP.
```

### Two rules carry the design

**1. The model supplies judgment; Python supplies arithmetic and order.**

The model says how urgent and how important something is, and why. It never says
what calendar day a phrase means, how many days away that is, or what comes
first. Date resolution, bucketing and the total order are all deterministic
Python.

This is not purism. Letting the model return a sorted array makes the ordering
unstable between runs and impossible to explain to the person reading the board.
The prompt says so explicitly: *"the list order is ignored… your job is the
judgment, not the sort."*

**2. Every query is scoped by `user_id`.**

Not a filter bolted on at the route — a required parameter on every repository
method. Sign in as the second seeded user and the board changes completely.

### One port, and why only one

`CommitmentEngine` is the only `Protocol` here. The app itself always talks to
Claude — there is no offline mode, and a missing `ANTHROPIC_API_KEY` fails loudly
rather than silently. The port still earns its keep:

- **the whole test suite runs with no API key and no network**, against a fake
  engine (`tests/fakes.py`) injected via a dependency override, so tests are
  free, instant and deterministic without the production code path knowing;
- "swap in Bedrock" or "swap in real Slack ingestion" is a one-file claim rather
  than hand-waving.

Data loading deliberately does **not** get a port. One implementation, forever —
an interface there would be indirection with nothing to justify it.

### Deliberately not an agent

This is a bounded two-stage workflow, not a tool loop. The input set is fixed and
known, so tool-calling autonomy would add cost and nondeterminism for no benefit.
The agentic version is the interesting extension — an agent that could *ask*
("is the board pack due the 2nd or the 4th?") and act on the answer — but that
needs a human-in-the-loop channel, which is a different project.

---

## The pipeline

```
threads
  → extract      per thread, concurrent, opus-5 @ high effort
  → validate     three guards, pure Python
  → apply marks  completion state, pure Python
  → prioritize   ONE call over what's left, sonnet-5 @ high effort
  → score        dates, buckets, total order, pure Python
```

**Extraction maps over *threads*, not messages.** This is the most important
decision in the codebase. Per-message extraction on a three-message thread yields
three commitments where a human sees one that moved twice — and the prioritisation
stage cannot repair that, because it only ever sees extracted rows, not the raw
text. Thread-level extraction is also cheaper and gives each call more context.

**Completion marks apply *between* the two model stages.** So the prioritisation
call never sees finished work — the daily briefing cannot tell you to do something
you already did — and it is a smaller set to rank, making the expensive call
cheaper. User state feeding back into the pipeline as a deterministic pre-filter
ahead of the reasoning.

### Where the model choice came from

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

### The three guards

Nothing corrects the model silently. Every failed check produces a flag the UI
renders, because a wrong answer shown with a warning is recoverable and a wrong
answer shown confidently is not.

| Guard | What it catches |
|---|---|
| **Dates parse in Python** | A malformed date becomes a warning and a null, never an exception mid-run. |
| **Verbatim citation** | `due_raw_text` must appear literally in the cited message. If it does not, the deadline may be invented — confidence is forced to `low` and an "unverified quote" badge appears. |
| **Evidence exists** | A cited message id that is not in the thread is a fabricated citation, and is reported. |

An earlier version added a fourth guard: a Python date resolver that re-derived
the same phrase independently, so a mismatch could be surfaced as "date
disputed". It was removed. Resolving Czech relative dates well enough to
*disagree usefully* with the model turned out to need most of the judgment the
model was there to supply — and a resolver that is wrong more often than the
thing it checks trains the user to ignore the badge. The honest version of that
guard is the ambiguity path below: when a date is genuinely unresolved, both
candidates are shown and the suggested action is to ask.

### "Is this mine?" — three values, not a boolean

| `audience` | Meaning | Example | On the board? |
|---|---|---|---|
| `me` | personally on the hook | "Honzo, pošli redlines do pátku" | yes |
| `my_team` | a project I'm accountable for owes it, even if nobody is named | "Pricing page pořád nemá finální copy" | yes |
| `someone_else` | another named person owns it | "DPA pro Acme řeším já… nic od tebe nepotřebuju" | no — audit panel |

`my_team` is why the user record carries a list of projects. Without it, "the
pricing page still has no copy" is genuinely undecidable — there is nothing in the
sentence to say whose problem it is.

### Nothing is silently dropped

Five collapsed panels below the board account for every commitment that isn't on
it: **Completed** (with undo), **Looks already done** (inferred from the thread,
not confirmed), **Cancelled**, **Not yours** (with the reason), and **Considered
and dismissed** (threads that yielded nothing, with what they actually contained).

A board that discards rows without explanation is indistinguishable from a broken
one. Showing the rejections is what makes the rest credible — and the dismissal
panel is where a reviewer can check the hardest judgment in the app.

### Two kinds of "done"

The model infers `status: "done"` from thread text ("Seznam klientů hotovo,
poslal jsem ti ho"). That is a **guess**. A user pressing *Done* is a **fact**.
They render differently and the explicit mark always wins.

Completion is keyed on `sha256(thread_key | evidence_message_id)` and belongs to
the **user, not the run**. Commitment rows are regenerated by every analysis, so
completion stored on them would march back onto the board after a re-run — the
single most annoying bug this kind of app can have. `task` is deliberately not in
the key: it is model-generated prose whose wording drifts between runs.

---

## Running it

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
.venv/bin/python scripts/seed.py
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1
```

Open <http://127.0.0.1:8000>. Sign in as `jan@example.com` or `petra@example.com`,
password `deadlines-demo`.

Analysis requires `ANTHROPIC_API_KEY` in `.env` — there is no offline mode. Press
**Re-run analysis** once it's set. *Reading* the board does not need a key: the
dashboard renders the last stored run, so only the analysis itself calls out.

`NOW_OVERRIDE` pins the clock to 2026-09-02. Without it the fixture's relative
dates rot — "do pátku" quietly starts meaning a different day and the demo breaks.

## Development

```bash
.venv/bin/python -m pytest              # 35 tests, no network, no cost
.venv/bin/ruff check .
.venv/bin/mypy
```

All three run in CI on every push (`.github/workflows/ci.yml`), with no API key
in the job — so "no network, no cost" is enforced rather than asserted. The test
fixtures pass `_env_file=None` for the same reason: `Settings` reads `.env` by
default, and a developer with a real key in theirs would otherwise get a live
engine the moment a test resolved the engine dependency without overriding it.

`mypy` runs `strict` over `app/domain` and `app/services` — the layers with no
framework machinery in them, where strictness finds defects rather than
arguments with plugin-shaped types.

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
configurations. `--repeat N` runs each one N times and reports per-check pass
rates instead of a single score — worth doing before drawing any conclusion,
because model output varies between runs and one 19/20 next to one 20/20 cannot
distinguish a real difference from noise. A check that passes 3/3 is evidence;
one that passes 2/3 is flaky, which is itself a finding.

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

---

## Known limitations

Scoped deliberately — a PoC, not a product.

- **Completion re-linking.** If a re-run cites a *different* message in the same
  thread as evidence, the key changes and the mark is orphaned. Mitigated by
  falling back to a thread-level match when a thread produced exactly one
  commitment. The real fix is a server-assigned identity with fuzzy re-matching.
- **Localhost, plain HTTP.** `COOKIE_SECURE=false`, no CSRF token, uvicorn bound
  to `127.0.0.1` so a cleartext session cookie never reaches the LAN. TLS,
  `COOKIE_SECURE=true` and a per-session token are prerequisites for any real
  deployment.
- **Schema created with `create_all`.** Alembic is the production path; not built.
- **Seeded demo passwords** are printed by the seed script. A real deployment
  would invite users.
- **The briefing belongs to a run**, so after an undo it stays stale until the
  next re-run.
- **No independent check on the model's date arithmetic.** Every resolved date
  rests on the model plus the verbatim-citation guard; there is no second
  opinion. See [The three guards](#the-three-guards) for why the one that
  existed was removed rather than kept.

## Where this would go next

- **Real ingestion.** One adapter behind `MessageRepository`: Slack
  `conversations.history` + `thread_ts`, Graph API + `conversationId`. Nothing
  above the repository changes.
- **Bedrock.** `AnthropicBedrockMantle` behind the same `CommitmentEngine` port;
  structured outputs and adaptive thinking are both supported there.
- **The nudge.** `suggested_action` is already "ask the CFO to confirm 2 vs 4
  September". Drafting that message is a small step, and it is where a deadline
  watchdog stops being a dashboard and starts closing the loop.
