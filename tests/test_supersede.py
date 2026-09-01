"""A thread whose deadline moves must reduce to ONE commitment with a history.

This is the case per-message extraction cannot represent, so it is the case most
worth pinning down. The test drives the real validation path — it does not just
assert on the stub's canned data.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.domain.models import (
    CommitmentDraft,
    DueChangeDraft,
    Message,
    Thread,
    ThreadExtraction,
    commitment_key,
)
from app.domain.validation import validate_thread

PRAGUE = ZoneInfo("Europe/Prague")
TODAY = date(2026, 9, 2)


def _thread() -> Thread:
    """A deadline moved twice: Friday -> Monday -> Wednesday."""
    return Thread(
        thread_key="slack:product:deck",
        source="slack",
        messages=(
            Message(external_id="m1", thread_key="slack:product:deck", source="slack",
                    author="Tomáš", sent_at=datetime(2026, 8, 31, 14, 5, tzinfo=PRAGUE),
                    body="Honzo, potřebuju deck. Zvládneš to do pátku?", channel="#product"),
            Message(external_id="m2", thread_key="slack:product:deck", source="slack",
                    author="Tomáš", sent_at=datetime(2026, 9, 1, 11, 30, tzinfo=PRAGUE),
                    body="Petra má dovolenou, posuňme to na pondělí.", channel="#product"),
            Message(external_id="m3", thread_key="slack:product:deck", source="slack",
                    author="Tomáš", sent_at=datetime(2026, 9, 1, 16, 0, tzinfo=PRAGUE),
                    body="Ještě jednou — až ve středu, klient přesunul schůzku.", channel="#product"),
        ),
    )


def _two_step_extraction() -> ThreadExtraction:
    return ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Prepare the deck", status="moved", owner="Jan", audience="me",
                audience_reason="addressed by name",
                original_due="2026-09-04", current_due="2026-09-09",
                due_kind="relative", date_confidence="high",
                due_raw_text="až ve středu",
                evidence_message_external_id="m3",
                evidence_quote="až ve středu, klient přesunul schůzku",
                supersede_chain=[
                    DueChangeDraft(message_external_id="m2", from_due="2026-09-04",
                                   to_due="2026-09-07", reason="Petra on leave"),
                    DueChangeDraft(message_external_id="m3", from_due="2026-09-07",
                                   to_due="2026-09-09", reason="client moved the meeting"),
                ],
                reasoning="One commitment, moved twice.",
            )
        ]
    )


def test_two_move_chain_resolves_to_one_commitment():
    got, warnings = validate_thread(_thread(), _two_step_extraction(), TODAY)

    assert len(got) == 1, "a moved deadline must not become several tasks"
    c = got[0]
    assert c.status == "moved"
    assert c.original_due == date(2026, 9, 4)
    assert c.current_due == date(2026, 9, 9), "the date in force is the last one"
    assert len(c.supersede_chain) == 2
    assert not warnings


def test_chain_is_traceable_end_to_end():
    """Each hop names the message that caused it, so the UI can show the story."""
    c = validate_thread(_thread(), _two_step_extraction(), TODAY)[0][0]
    hops = [(h.from_due, h.to_due, h.message_external_id) for h in c.supersede_chain]
    assert hops == [
        (date(2026, 9, 4), date(2026, 9, 7), "m2"),
        (date(2026, 9, 7), date(2026, 9, 9), "m3"),
    ]
    assert c.supersede_chain[-1].to_due == c.current_due


def test_key_is_stable_across_runs_and_ignores_task_wording():
    """Completion marks hang off this key, so re-worded prose must not move it."""
    original = _two_step_extraction()
    reworded = original.model_copy(deep=True)
    reworded.commitments[0].task = "Get the deck ready for the QBR"

    first = validate_thread(_thread(), original, TODAY)[0][0]
    second = validate_thread(_thread(), reworded, TODAY)[0][0]
    assert first.key == second.key
    assert first.key == commitment_key("slack:product:deck", "m3")


def test_invented_deadline_is_flagged_not_trusted():
    """A due phrase absent from the cited message means the date may be made up."""
    bad = _two_step_extraction()
    bad.commitments[0].due_raw_text = "do 15. 9."  # never appears in any message

    got, warnings = validate_thread(_thread(), bad, TODAY)
    assert got[0].quote_verified is False
    assert got[0].date_confidence == "low", "confidence must be forced down"
    assert any("does not appear" in w for w in warnings)


def test_cancellation_clears_the_date_but_keeps_the_history():
    cancelled = ThreadExtraction(
        commitments=[
            CommitmentDraft(
                task="Prepare the deck", status="cancelled", owner="Jan", audience="me",
                audience_reason="addressed by name",
                original_due="2026-09-04", current_due=None,
                due_kind="relative", date_confidence="high",
                due_raw_text="do pátku",
                evidence_message_external_id="m1",
                evidence_quote="Zvládneš to do pátku?",
                supersede_chain=[
                    DueChangeDraft(message_external_id="m2", from_due="2026-09-04",
                                   to_due=None, reason="no longer needed"),
                ],
                reasoning="Called off.",
            )
        ]
    )
    c = validate_thread(_thread(), cancelled, TODAY)[0][0]
    assert c.status == "cancelled"
    assert c.current_due is None
    assert c.original_due == date(2026, 9, 4), "history is kept, not erased"
    assert c.is_actionable is False
