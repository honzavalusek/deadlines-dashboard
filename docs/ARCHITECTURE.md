# Architecture

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

For why extraction runs on Opus and prioritization on Sonnet specifically, see
[MODEL_CHOICE.md](MODEL_CHOICE.md).

### The three guards

Nothing corrects the model silently. Every failed check produces a flag the UI
renders, because a wrong answer shown with a warning is recoverable and a wrong
answer shown confidently is not.

| Guard | What it catches |
|---|---|
| **Dates parse in Python** | A malformed date becomes a warning and a null, never an exception mid-run. |
| **Verbatim citation** | `due_raw_text` must appear literally in the cited message. If it does not, the deadline may be invented — confidence is forced to `low` and an "unverified quote" badge appears. |
| **Evidence exists** | A cited message id that is not in the thread is a fabricated citation, and is reported. |

An earlier version added a fourth guard — an independent Python date resolver
to flag mismatches as "date disputed". Removed: resolving Czech relative dates
well enough to disagree usefully needed the same judgment the model was there
to supply. The ambiguity path above is the honest version of that guard.

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
