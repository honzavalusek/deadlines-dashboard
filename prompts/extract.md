# Stage 1 — extract commitments from one conversation thread

You are analysing a single conversation thread from {{PERSON}}'s Slack or email.
Your job is to find what **{{PERSON}} is actually on the hook for**, and by when.

## Who "me" is

- Name: {{DISPLAY_NAME}}
- Also addressed as: {{ALIASES}}
- Email addresses: {{EMAILS}}
- Accountable for these projects: {{PROJECTS}}

Czech declines names, so "Honzo", "Honzovi" and "Jane" are all the same person
as "Jan". Treat any alias above as this user.

## What counts as a commitment

All three must hold:

1. **An obligation** — something must be produced, sent, reviewed or decided.
   Not an idea, an opinion, or a possibility.
2. **An identifiable owner** — a named person, or a team/project that has one.
3. **A due signal** — a date, a relative date, or a clear event it must precede.
   A commitment with no due signal still counts *if* the obligation and owner are
   unambiguous; record it with `due_kind: "none"`.

Things that are **not** commitments, and must not be extracted:

- "We should tidy the wiki sometime" — no owner, no date. An intention.
- "Nice work on the launch!" — praise.
- "Deployed api-gateway v2.14.1" — a notification.
- "Who's going to lunch?" — coordination, not an obligation.

When in doubt, do not extract. A dismissed thread with a clear reason is far
more useful than a false task, because a board with invented work on it stops
being trusted.

## A thread is one story

This is the most important instruction here.

If a deadline is **set and then changed**, that is **ONE commitment whose date
moved** — not two commitments. Put the original date in `original_due`, the date
now in force in `current_due`, record each change in `supersede_chain`, and set
`status: "moved"` (unless it is also cancelled, done, or ambiguous, in which case
that status wins).

If a deadline is **cancelled**, that is **ONE commitment with
`status: "cancelled"`** — set `current_due` to null, keep `original_due`, and
record the cancellation in `supersede_chain` with `to_due: null`.

If the thread says the work is **already finished**, use `status: "done"`.

If two people state **different dates and never resolve it**, do NOT pick a
winner and present it confidently. Use `status: "ambiguous"`, set `current_due`
to the **earlier** candidate so the deadline cannot be missed, put the other in
`original_due`, and set `date_confidence: "low"`. Flagging beats guessing.

## Dates

Today is **{{NOW}}**. Every message below carries its own send time and weekday.

Resolve every relative expression against **the date of the message it appears
in**, never against today. "do pátku" written on Monday 31 August means Friday
4 September; the same words on Wednesday 2 September mean Friday 4 September too,
but the reasoning differs, so use the message's own date each time.

- "do pátku" / "v pátek" → the coming Friday, on or after the message date
- "minulý pátek" → the most recent Friday strictly before the message date
- "do konce měsíce" → the last day of the message's month
- "do zítra" → the day after the message date

Output every date as ISO `YYYY-MM-DD`.

When someone else states a **fixed deadline for a filing, hearing or other event**
and asks {{PERSON}} for his contribution "in time" / "with enough lead time"
before it, with no separate date given for his own hand-off, treat that named
deadline as `current_due` (`due_kind: "explicit"`) rather than leaving the
commitment undated — his real deadline is that date, not some unstated earlier
one.

`due_raw_text` must be the deadline phrase **copied character-for-character from
the message, in its original language**. Do not translate it, do not tidy it, do
not expand abbreviations. It is checked against the message text automatically,
and a mismatch is treated as a sign the date may be invented.

The same rule applies to `evidence_quote`: it must be **one uninterrupted span of
characters, copied exactly**, from a single sentence or two adjacent sentences.
Never splice separate parts of the message together with "..." — that is checked
as a literal substring too, so an elided quote fails verification and the
citation is treated as unverified even when the underlying claim is correct. If
the date and the obligation are stated in different sentences, quote the one
that states the due signal.

## Is it aimed at me?

- `me` — {{PERSON}} is personally on the hook: addressed by name or alias, or he
  volunteered.
- `my_team` — no individual is named, but the work belongs to a project he is
  accountable for (see the list above). "The pricing page still has no copy" is
  `my_team` when he owns the pricing page.
- `someone_else` — another named person owns it. Use this even when the message
  is addressed to {{PERSON}}, if the content makes clear somebody else is doing
  the work ("I'm handling the DPA, just FYI").

Explain your choice in one clause in `audience_reason`.

## Output language

Write **English** in every field, even though most input is Czech. `task`,
`audience_reason`, `reasoning`, `dismissal_reason` and every `reason` in the
chain are all English.

Two exceptions, both because they are citations rather than prose:
`evidence_quote` and `due_raw_text` stay **verbatim in the original language**.

`task` should read as an instruction to the user: "Send the MSA redlines to
counsel", not "Jan needs to send the redlines" and not the Czech original.

## The thread

Source: {{SOURCE}} — {{THREAD_LABEL}}

{{MESSAGES}}

---

Return the commitments you found. If there are none, return an empty list and a
specific `dismissal_reason` — name what the thread actually contained, so the
user can see you read it rather than skipped it.
