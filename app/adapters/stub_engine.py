"""Deterministic engine with canned answers. No network, no API key, no cost.

This file does triple duty:

1. It lets the whole app — and every test — run offline. A demo that depends on
   connectivity is a demo that can die in front of an audience.
2. It is the **expected-answers table** for ``scripts/eval_models.py``. Each
   entry below is what a correct analysis of that thread looks like, so the
   real engine can be diffed against it instead of eyeballed.
3. It documents the fixture. Reading this next to ``data/seed_*.json`` shows
   what each adversarial thread is *for*.

Every ``due_raw_text`` here is a verbatim substring of the cited message body,
because validation enforces exactly that on real output too — the stub must not
get a pass the real engine doesn't.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.models import (
    Commitment,
    CommitmentDraft,
    DueChangeDraft,
    ExtractionOutput,
    Identity,
    PrioritizationOutput,
    PrioritizationResult,
    PriorityDraft,
    StageTrace,
    Thread,
    ThreadExtraction,
)

# ---------------------------------------------------------------------------
# Stage 1 expectations, keyed by thread_key.
# ---------------------------------------------------------------------------

EXPECTED_EXTRACTIONS: dict[str, ThreadExtraction] = {
    # Baseline: an explicit date, named owner, high stakes. Nothing tricky.
    "slack:legal-ops:msa-redlines": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Send the MSA redlines back to our counsel",
                status="active",
                owner="Jan Valušek",
                audience="me",
                audience_reason="Addressed by name ('Honzo') and he accepted the task in the thread.",
                original_due="2026-09-03",
                current_due="2026-09-03",
                due_kind="explicit",
                date_confidence="high",
                due_raw_text="do čtvrtka 3. 9.",
                evidence_message_external_id="slack:legal-ops:msa-redlines:1",
                evidence_quote="Potřebujeme je zpátky u našeho counsela do čtvrtka 3. 9., jinak nestihneme signing.",
                reasoning="Explicit calendar date stated in the request; Jan accepted it directly. "
                "Signing depends on it, so slipping has an external consequence.",
            )
        ]
    ),
    # The case per-message extraction cannot represent: one deadline that moved.
    # Three messages, ONE commitment, with the move recorded rather than a
    # second task invented.
    "slack:product:roadmap-deck": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Prepare the roadmap deck for the QBR",
                status="moved",
                owner="Jan Valušek",
                audience="me",
                audience_reason="Asked directly ('Honzo, potřebuju') and he agreed.",
                original_due="2026-09-04",
                current_due="2026-09-07",
                due_kind="relative",
                date_confidence="high",
                due_raw_text="na pondělí",
                evidence_message_external_id="slack:product:roadmap-deck:3",
                evidence_quote="Posuňme to na pondělí.",
                supersede_chain=[
                    DueChangeDraft(
                        message_external_id="slack:product:roadmap-deck:3",
                        from_due="2026-09-04",
                        to_due="2026-09-07",
                        reason="Petra is on leave and the deck needs her numbers",
                    )
                ],
                reasoning="'do pátku' on Mon 31 Aug resolves to Fri 4 Sep. Message 3 moves it to "
                "'pondělí' (Mon 7 Sep) and Jan confirms. One commitment that moved, not two tasks.",
            )
        ]
    ),
    # No date at all, and blocked on another thread. The correct behaviour is to
    # keep it without inventing a deadline.
    "slack:eng:pricing-copy": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Publish the partnership press release",
                status="active",
                owner="Jan Valušek",
                audience="me",
                audience_reason="He committed to doing it himself ('Pustíme to').",
                original_due=None,
                current_due=None,
                due_kind="none",
                date_confidence="high",
                due_raw_text=None,
                evidence_message_external_id="slack:eng:pricing-copy:2",
                evidence_quote="Pustíme to hned jak legal odsouhlasí MSA.",
                reasoning="A real commitment with no date: it is gated on legal approving the MSA. "
                "Confidently no deadline stated, rather than a low-confidence guess at one.",
            )
        ]
    ),
    # Must yield nothing. 'Měli bychom někdy' has no owner and no date, which is
    # precisely what over-extraction looks like.
    "slack:general:chitchat": ThreadExtraction(
        commitments=[],
        dismissal_reason="Congratulations, a lunch poll and a deploy notification. The one "
        "task-shaped sentence ('Měli bychom někdy uklidit wiki') has no owner and no date, "
        "so it is an idea rather than a commitment.",
    ),
    # Two commitments in one thread: one overdue, one the thread itself says is
    # finished. Tests that 'done' is detected from text, not assumed from age.
    "slack:dm-lucie:finance": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Submit the August expense report",
                status="active",
                owner="Jan Valušek",
                audience="me",
                audience_reason="Addressed by name and chased directly; he says he will finish it.",
                original_due="2026-08-21",
                current_due="2026-08-21",
                due_kind="relative",
                date_confidence="medium",
                due_raw_text="minulý pátek",
                evidence_message_external_id="slack:dm-lucie:finance:1",
                evidence_quote="výkaz nákladů za srpen měl být hotový minulý pátek a pořád tam nic není",
                reasoning="Sent Fri 28 Aug, so 'minulý pátek' resolves to Fri 21 Aug — already "
                "overdue. Medium confidence because the phrasing is relative, not a stated date.",
            ),
            CommitmentDraft(
                task="Send the client list for the audit",
                status="done",
                owner="Jan Valušek",
                audience="me",
                audience_reason="Requested of him directly.",
                original_due="2026-08-31",
                current_due="2026-08-31",
                due_kind="relative",
                date_confidence="high",
                due_raw_text="do pondělí",
                evidence_message_external_id="slack:dm-lucie:finance:2",
                evidence_quote="A ještě bych potřebovala seznam klientů pro audit, do pondělí.",
                reasoning="Requested Fri 28 Aug for 'pondělí' (Mon 31 Aug). Message 3 states it was "
                "sent, so it is done — inferred from the thread, which is weaker than a user's mark.",
            ),
        ]
    ),
    # The audience case a boolean cannot express: passive voice, no named owner,
    # but it lands on a project this user is accountable for.
    "slack:pricing:launch-copy": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Finalise the copy for the pricing page",
                status="active",
                owner="unassigned (pricing page team)",
                audience="my_team",
                audience_reason="No individual is named, but Jan is accountable for the "
                "'pricing page' project, so it is his to land.",
                original_due="2026-09-04",
                current_due="2026-09-04",
                due_kind="relative",
                date_confidence="high",
                due_raw_text="do pátku",
                evidence_message_external_id="slack:pricing:launch-copy:1",
                evidence_quote="Musíme to shipnout do pátku, jinak nám to blokne celý launch.",
                reasoning="Sent Tue 1 Sep, so 'do pátku' is Fri 4 Sep. Phrased as a team obligation "
                "('musíme'); it blocks the 7 Sep launch, which is what makes it important.",
            )
        ]
    ),
    # Low-stakes but due soon. Exists to be outranked — the foil that makes
    # comparative prioritisation checkable rather than a claim.
    "slack:marketing:blog-alt-text": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Add alt text to the blog images",
                status="active",
                owner="Jan Valušek",
                audience="me",
                audience_reason="Asked by name ('Honzo, můžeš').",
                original_due="2026-09-03",
                current_due="2026-09-03",
                due_kind="relative",
                date_confidence="high",
                due_raw_text="do čtvrtka",
                evidence_message_external_id="slack:marketing:blog-alt-text:1",
                evidence_quote="můžeš do čtvrtka doplnit alt texty u obrázků na blogu?",
                reasoning="Sent Tue 1 Sep, so 'do čtvrtka' is Thu 3 Sep. The requester explicitly "
                "says it is not urgent, so it should rank below weightier work due later.",
            )
        ]
    ),
    # Cancelled outright. Showing the system correctly REMOVES work is more
    # convincing than showing it finds work.
    "email:acme-security-questionnaire": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Complete the Acme security questionnaire",
                status="cancelled",
                owner="Jan Valušek",
                audience="me",
                audience_reason="Requested of him directly.",
                original_due="2026-09-03",
                current_due=None,
                due_kind="explicit",
                date_confidence="high",
                due_raw_text="do čtvrtka 3. 9.",
                evidence_message_external_id="email:acme-security-questionnaire:1",
                evidence_quote="Potřebujeme to odeslat do čtvrtka 3. 9., abychom stihli schvalovací kolečko.",
                supersede_chain=[
                    DueChangeDraft(
                        message_external_id="email:acme-security-questionnaire:2",
                        from_due="2026-09-03",
                        to_due=None,
                        reason="Acme withdrew from the tender, so the questionnaire is not needed",
                    )
                ],
                reasoning="Originally due 3 Sep, then explicitly withdrawn: 'už není potřeba. Nic "
                "nevyplňuj.' No action remains — it should be visibly cancelled, not silently dropped.",
            )
        ]
    ),
    # The rank inversion: furthest away, but statutory and unextendable. Must
    # outrank everything due sooner.
    "email:uohs-filing": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="File the ÚOHS submission for the public tender",
                status="active",
                owner="Jan Valušek",
                audience="me",
                audience_reason="Counsel addresses him directly and needs the material from him.",
                original_due="2026-09-10",
                current_due="2026-09-10",
                due_kind="explicit",
                date_confidence="high",
                due_raw_text="nejpozději 10. 9. 2026",
                evidence_message_external_id="email:uohs-filing:1",
                evidence_quote="podání k ÚOHS musí být na podatelně nejpozději 10. 9. 2026. Jde o "
                "zákonnou lhůtu, kterou nelze prodloužit ani prominout",
                reasoning="A statutory deadline that cannot be extended or waived, and the right "
                "lapses once it passes. Furthest out of anything here and the most consequential.",
            )
        ]
    ),
    # Conflicting dates that were never resolved. Correct behaviour is to FLAG,
    # not to pick a winner and look confident about it.
    "email:board-pack": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Deliver the Q3 board pack to the CFO",
                status="ambiguous",
                owner="Jan Valušek",
                audience="me",
                audience_reason="The CFO asks him for it directly.",
                original_due="2026-09-04",
                current_due="2026-09-02",
                due_kind="explicit",
                date_confidence="low",
                due_raw_text="na 2. 9.",
                evidence_message_external_id="email:board-pack:2",
                evidence_quote="myslel jsem, že jsme se na poradě dohodli na 2. 9.?",
                reasoning="The CFO asked for 4 Sep, Jan recalls 2 Sep, and the thread ends "
                "unresolved ('musím se podívat do zápisu'). Taking the earlier date so the deadline "
                "cannot be missed, but flagged low confidence — this needs confirming, not guessing.",
            )
        ]
    ),
    # Somebody else's work, and the message says so explicitly. Kept, but off
    # the board.
    "email:acme-dpa": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Deliver the Acme DPA",
                status="active",
                owner="Petra Nováková",
                audience="someone_else",
                audience_reason="Petra states she is handling it and that nothing is needed from Jan.",
                original_due="2026-09-03",
                current_due="2026-09-03",
                due_kind="explicit",
                date_confidence="high",
                due_raw_text="do 3. 9.",
                evidence_message_external_id="email:acme-dpa:1",
                evidence_quote="DPA pro Acme řeším já, dodám ho do 3. 9. Posílám jen pro přehled, "
                "nic od tebe nepotřebuju.",
                reasoning="Petra owns it and rules Jan out in the same sentence. Recorded for "
                "visibility but it does not belong on his board.",
            )
        ]
    ),
    # --- Petra's own threads, so switching login visibly changes the board ---
    "slack:legal-ops:acme-dpa": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Deliver the Acme DPA",
                status="active",
                owner="Petra Nováková",
                audience="me",
                audience_reason="She took it on herself ('beru já').",
                original_due="2026-09-03",
                current_due="2026-09-03",
                due_kind="explicit",
                date_confidence="high",
                due_raw_text="do 3. 9.",
                evidence_message_external_id="slack:legal-ops:acme-dpa:1",
                evidence_quote="DPA pro Acme si beru já, dodám do 3. 9.",
                reasoning="Self-assigned with an explicit date. The mirror of the thread that "
                "appears on Jan's board as someone else's work.",
            )
        ]
    ),
    "email:vendor-contract-review": ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Review the Contoso vendor contract",
                status="active",
                owner="Petra Nováková",
                audience="me",
                audience_reason="Asked by name and she accepted.",
                original_due="2026-09-08",
                current_due="2026-09-08",
                due_kind="explicit",
                date_confidence="high",
                due_raw_text="do 8. 9.",
                evidence_message_external_id="email:vendor-contract-review:1",
                evidence_quote="prosím o revizi smlouvy s Contoso do 8. 9.",
                reasoning="Explicit date, accepted in the reply.",
            )
        ]
    ),
}


# ---------------------------------------------------------------------------
# Stage 2 expectations, keyed by task text (keys are hashes, unreadable here).
#
# Two deliberate rank inversions a naive date sort gets wrong:
#   * the ÚOHS filing (10 Sep) must outrank the blog alt text (3 Sep)
#   * the pricing page copy (4 Sep) must outrank the blog alt text (3 Sep)
# ---------------------------------------------------------------------------

EXPECTED_PRIORITIES: dict[str, dict] = {
    "Send the MSA redlines back to our counsel": dict(
        urgency=92, importance=90, band="critical",
        rationale="Due in two days and signing slips if it misses; also unblocks the press release.",
        suggested_action="Review the redlines today and send them to counsel.",
    ),
    "Finalise the copy for the pricing page": dict(
        urgency=88, importance=85, band="critical",
        rationale="Blocks the 7 Sep launch, and nobody is named on it — so it is the most likely "
                  "thing here to be quietly dropped.",
        suggested_action="Assign an owner for the copy today, or write it yourself.",
    ),
    "File the ÚOHS submission for the public tender": dict(
        urgency=70, importance=98, band="critical",
        rationale="Furthest away but the only irreversible item: a statutory deadline that cannot "
                  "be extended, after which the right lapses entirely.",
        suggested_action="Block time this week to prepare the material for counsel.",
    ),
    "Deliver the Q3 board pack to the CFO": dict(
        urgency=90, importance=75, band="high",
        rationale="Might be due today — the date was never agreed, so treat it as today until the "
                  "CFO confirms.",
        suggested_action="Ask the CFO to confirm 2 vs 4 September before doing anything else.",
    ),
    "Submit the August expense report": dict(
        urgency=95, importance=40, band="high",
        rationale="Already twelve days overdue and blocking someone else's month-end close. Small "
                  "task, disproportionate cost to others.",
        suggested_action="Submit it — it is fifteen minutes of work.",
    ),
    "Prepare the roadmap deck for the QBR": dict(
        urgency=45, importance=60, band="medium",
        rationale="Already moved once to Monday and dependent on Petra's numbers, which she cannot "
                  "supply until she is back.",
        suggested_action="Ask Petra for the numbers now so Monday does not slip again.",
    ),
    "Add alt text to the blog images": dict(
        urgency=55, importance=15, band="low",
        rationale="Due Thursday, but the requester said it is not urgent and nothing depends on it.",
        suggested_action="Batch it with other small tasks; it can wait.",
    ),
    "Publish the partnership press release": dict(
        urgency=20, importance=50, band="low",
        rationale="Genuinely blocked on the MSA approval; no useful work is possible until that lands.",
        suggested_action="Nothing yet — it unblocks when the redlines are signed off.",
    ),
    "Deliver the Acme DPA": dict(
        urgency=80, importance=70, band="high",
        rationale="Due in a day and externally committed.",
        suggested_action="Finish the DPA and send it.",
    ),
    "Review the Contoso vendor contract": dict(
        urgency=50, importance=55, band="medium",
        rationale="Nearly a week out with no dependency on it.",
        suggested_action="Schedule a review slot before 8 September.",
    ),
}

_BLOCKED_BY_TASK = {"Publish the partnership press release": "Send the MSA redlines back to our counsel"}

DEFAULT_PRIORITY = dict(
    urgency=50, importance=50, band="medium",
    rationale="No canned judgment for this item in the stub.",
    suggested_action="Review manually.",
)


class StubCommitmentEngine:
    """Canned implementation of :class:`app.domain.ports.CommitmentEngine`."""

    name = "stub"

    async def extract_all(
        self,
        threads: list[Thread],
        identity: Identity,
        now: datetime,
    ) -> ExtractionOutput:
        per_thread: dict[str, ThreadExtraction] = {}
        warnings: list[str] = []
        for thread in threads:
            expected = EXPECTED_EXTRACTIONS.get(thread.thread_key)
            if expected is None:
                warnings.append(f"stub has no canned analysis for thread {thread.thread_key}")
                per_thread[thread.thread_key] = ThreadExtraction(
                    commitments=[], dismissal_reason="No canned analysis in the stub engine."
                )
                continue
            per_thread[thread.thread_key] = expected.model_copy(deep=True)

        return ExtractionOutput(
            per_thread=per_thread,
            trace=StageTrace(stage="extract", model="stub", effort="n/a", calls=len(threads)),
            warnings=warnings,
        )

    async def prioritize(
        self,
        commitments: list[Commitment],
        identity: Identity,
        now: datetime,
    ) -> PrioritizationOutput:
        by_task = {c.task: c.key for c in commitments}
        priorities = []
        for c in commitments:
            spec = EXPECTED_PRIORITIES.get(c.task, DEFAULT_PRIORITY)
            blocker_task = _BLOCKED_BY_TASK.get(c.task)
            priorities.append(
                PriorityDraft(
                    commitment_key=c.key,
                    blocked_by=[by_task[blocker_task]] if blocker_task in by_task else [],
                    **spec,
                )
            )

        return PrioritizationOutput(
            result=PrioritizationResult(
                priorities=priorities,
                daily_briefing=_briefing(commitments),
            ),
            trace=StageTrace(stage="prioritize", model="stub", effort="n/a", calls=1),
            thinking_summary="(stub engine — no model reasoning to show)",
        )


def _briefing(commitments: list[Commitment]) -> str:
    if not commitments:
        return "Nothing outstanding."
    tasks = {c.task for c in commitments}
    if "Send the MSA redlines back to our counsel" in tasks:
        return (
            "The MSA redlines are the one thing that has to move today — signing slips without "
            "them, and the press release is waiting on them too. Chase the CFO for a straight "
            "answer on whether the board pack is due today or Friday before you plan the rest of "
            "the week. The ÚOHS filing is still a week out but it is the only deadline here you "
            "cannot recover from, so protect time for it now."
        )
    return "Review the board below; the highest-priority items are listed first."
