"""Turn model output into trusted domain objects — or into visible doubt.

Nothing here corrects the model silently. Every check that fails produces a
flag the dashboard renders, because a wrong answer shown with a warning is
recoverable and a wrong answer shown confidently is not.

Three guards:

1. **Dates parse in Python, not in the SDK.** A malformed date becomes a
   warning and a null, never an exception mid-run.
2. **Verbatim citation.** ``due_raw_text`` must appear literally in the message
   it cites. If it does not, the model may have invented the deadline, so
   confidence is forced down and a badge appears.
3. **Evidence exists.** A cited message id that is not in the thread is a
   fabricated citation and is reported.
"""

from __future__ import annotations

from datetime import date

from app.domain.models import (
    Commitment,
    CommitmentDraft,
    DueChange,
    Message,
    Thread,
    ThreadExtraction,
    commitment_key,
)


def _parse_iso_date(value: str | None, label: str, warnings: list[str]) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        warnings.append(f"unparseable {label}: {value!r} — treated as no date")
        return None


def _normalise(text: str) -> str:
    """Collapse whitespace so a quote that crossed a line break still matches."""
    return " ".join(text.split())


def validate_thread(
    thread: Thread,
    extraction: ThreadExtraction,
    today: date,
) -> tuple[list[Commitment], list[str]]:
    """Validate one thread's extraction. Returns ``(commitments, warnings)``."""
    by_id: dict[str, Message] = {m.external_id: m for m in thread.messages}
    commitments: list[Commitment] = []
    warnings: list[str] = []

    for draft in extraction.commitments:
        commitments.append(_validate_one(draft, thread, by_id, warnings))

    return commitments, warnings


def _validate_one(
    draft: CommitmentDraft,
    thread: Thread,
    by_id: dict[str, Message],
    warnings: list[str],
) -> Commitment:
    where = f"{thread.thread_key}/{draft.task[:40]}"

    original_due = _parse_iso_date(draft.original_due, f"original_due in {where}", warnings)
    current_due = _parse_iso_date(draft.current_due, f"current_due in {where}", warnings)

    evidence = by_id.get(draft.evidence_message_external_id)
    quote_verified = True

    if evidence is None:
        # A citation pointing outside the thread it came from is fabricated.
        warnings.append(
            f"{where}: cites message {draft.evidence_message_external_id!r}, "
            "which is not in this thread"
        )
        quote_verified = False
    else:
        body = _normalise(evidence.body)
        if _normalise(draft.evidence_quote) not in body:
            warnings.append(f"{where}: evidence quote is not verbatim in the cited message")
            quote_verified = False
        if draft.due_raw_text and _normalise(draft.due_raw_text) not in body:
            warnings.append(
                f"{where}: due_raw_text {draft.due_raw_text!r} does not appear in the "
                "cited message — the date may be invented"
            )
            quote_verified = False

    # A quote that could not be verified is not trustworthy enough to keep a
    # high-confidence label, whatever the model claimed.
    date_confidence = draft.date_confidence
    if not quote_verified and date_confidence == "high":
        date_confidence = "low"

    supersede_chain = [
        DueChange(
            message_external_id=c.message_external_id,
            from_due=_parse_iso_date(c.from_due, f"chain from_due in {where}", warnings),
            to_due=_parse_iso_date(c.to_due, f"chain to_due in {where}", warnings),
            reason=c.reason,
        )
        for c in draft.supersede_chain
    ]

    # For an unresolved thread, the date the model didn't pick is still a live
    # candidate and the user needs to see both.
    alternatives: list[date] = []
    if draft.status == "ambiguous" and original_due and original_due != current_due:
        alternatives.append(original_due)

    return Commitment(
        key=commitment_key(thread.thread_key, draft.evidence_message_external_id),
        thread_key=thread.thread_key,
        source=thread.source,
        thread_label=thread.label,
        task=draft.task,
        status=draft.status,
        owner=draft.owner,
        audience=draft.audience,
        audience_reason=draft.audience_reason,
        original_due=original_due,
        current_due=current_due,
        due_kind=draft.due_kind,
        date_confidence=date_confidence,
        due_raw_text=draft.due_raw_text,
        evidence_message_external_id=draft.evidence_message_external_id,
        evidence_quote=draft.evidence_quote,
        supersede_chain=supersede_chain,
        reasoning=draft.reasoning,
        quote_verified=quote_verified,
        alternative_dues=alternatives,
    )
