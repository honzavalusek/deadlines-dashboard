"""Turn model output into trusted domain objects — or into visible doubt.

Nothing here corrects the model silently. Every check that fails produces a
flag the dashboard renders, because a wrong answer shown with a warning is
recoverable and a wrong answer shown confidently is not.

Four guards:

1. **Dates parse in Python, not in the SDK.** A malformed date becomes a
   warning and a null, never an exception mid-run.
2. **Verbatim citation.** ``due_raw_text`` must appear literally in the message
   it cites. If it does not, the model may have invented the deadline, so
   confidence is forced down and a badge appears.
3. **Independent resolution.** ``app.domain.dates`` resolves the same phrase
   separately; a mismatch surfaces as "needs confirmation" rather than a silent
   overwrite of either answer.
4. **Evidence exists.** A cited message id that is not in the thread is a
   fabricated citation and is reported.
"""

from __future__ import annotations

from datetime import date

from app.domain.dates import resolve
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

    date_disagreement = _cross_check(draft, evidence, original_due, current_due, supersede_chain)

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
        date_disagreement=date_disagreement,
        alternative_dues=alternatives,
    )


def _cross_check(
    draft: CommitmentDraft,
    evidence: Message | None,
    original_due: date | None,
    current_due: date | None,
    supersede_chain: list[DueChange],
) -> str | None:
    """Compare the model's resolved date with Python's own reading of the phrase.

    ``due_raw_text`` cites one specific message, and that citation is not
    guaranteed to justify ``current_due`` specifically — a moved deadline can
    still be cited from the message that first set it, and an ambiguous one
    (``status: "ambiguous"``) has two dates on record precisely because two
    messages disagreed, either of which the citation may point at. So a match
    against *any* due date this commitment has ever carried — current,
    original, or a step in the supersede chain — counts as agreement, not just
    a match against ``current_due``.

    Only reports when Python is confident *and* disagrees. ``None`` from the
    resolver means "no opinion", which must never be read as disagreement.
    """
    if evidence is None or not draft.due_raw_text or current_due is None:
        return None

    ours = resolve(draft.due_raw_text, evidence.sent_at)
    if ours is None:
        return None

    known_dues = {
        d
        for d in (
            current_due,
            original_due,
            *(hop.to_due for hop in supersede_chain),
            *(hop.from_due for hop in supersede_chain),
        )
        if d is not None
    }
    if ours in known_dues:
        return None

    # Not a match against anything on record — a genuine disagreement. Name the
    # date the cited message most likely justifies, for a clearer message.
    hop_due = next(
        (hop.to_due for hop in supersede_chain if hop.message_external_id == evidence.external_id),
        None,
    )
    target = hop_due if hop_due is not None else (original_due if supersede_chain else current_due)
    if target is None:
        target = current_due

    return (
        f"Model resolved {draft.due_raw_text!r} to {target.isoformat()}, "
        f"but reading it from the message date gives {ours.isoformat()}. Needs confirmation."
    )
