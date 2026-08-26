# Stage 2 — prioritise the whole set against itself

Below is every outstanding commitment for {{PERSON}}, already extracted from his
conversations. Judge them **relative to each other**.

This is the step that cannot be done one item at a time. Urgency is mostly a
function of the date, and the code already knows the dates. What you are here to
supply is **importance** — the consequence of a thing slipping — which only makes
sense in comparison.

Today is **{{NOW}}**.

{{PERSON}} is accountable for: {{PROJECTS}}

## What to weigh

Rank by consequence, not by proximity. A deadline three weeks out can matter far
more than one tomorrow. Specifically:

- **Irreversibility.** A statutory or regulatory deadline that cannot be extended
  outranks almost anything, because missing it destroys the option permanently.
  Internal deadlines usually can be moved and usually are.
- **Who else is blocked.** Work that other people or other commitments wait on
  costs more than its own size. A fifteen-minute task holding up someone's
  month-end close is worth more attention than its effort suggests.
- **Unowned work.** An obligation on a project with no named individual is the
  most likely thing here to be quietly dropped. Weight it up, not down.
- **Stated non-urgency.** If the requester said it can wait, believe them.
- **Genuine blockage.** Something that cannot be started until another item lands
  is not urgent today, however close its date. Say so, and record the dependency
  in `blocked_by` using the other item's `commitment_key`.
- **Ambiguity.** A commitment whose date was never agreed needs its date settled
  before the work matters. The next action is usually "ask", not "do".

Explicitly resist ordering by date. If your ranking happens to come out in date
order, check whether you have actually made a judgment.

## Scores

- `urgency` 0-100 — how soon action is needed.
- `importance` 0-100 — what it costs if it slips. This is the field that carries
  your judgment; spread it out and use the whole range.
- `band` — `critical`, `high`, `medium`, `low`. Be sparing with `critical`; if
  everything is critical the board tells the user nothing.

Do **not** try to return these in ranked order. The list order is ignored: the
application sorts deterministically from `band`, the date, and `importance`, so
that the ordering is stable between runs and explainable to the user. Your job is
the judgment, not the sort.

`rationale` — one sentence, and it must be **comparative**: why this sits where
it does *relative to the rest*. "Due Thursday" is not a rationale; "due Thursday
but the requester said it can wait, and three heavier items land the same week"
is.

`suggested_action` — the single next physical action, imperative. If the right
move is to ask someone a question, say that.

## The daily briefing

Also write `daily_briefing`: three sentences on what actually matters today.
This is the only part of the app a busy person will read, so make it worth
reading — name the one thing that must move, the thing most likely to be
forgotten, and anything that needs a decision from someone else. Plain English,
no preamble, no restating the list.

## Output language

English throughout.

## The commitments

{{COMMITMENTS}}
