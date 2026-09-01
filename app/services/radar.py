"""Pipeline orchestration.

    threads
      -> extract (per thread, concurrent, in the engine)
      -> validate (guards, in Python)
      -> apply completion marks
      -> prioritize (one comparative pass over what's left)
      -> score and bucket (Python)

Completion marks are applied **between** the two model stages, not after. Two
reasons, and both matter: the prioritisation call never sees finished work, so
the daily briefing cannot tell you to do something you already did; and it is a
smaller set to rank, so the more expensive call gets cheaper. User state feeds
back into the pipeline as a deterministic pre-filter ahead of the reasoning.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from app.domain.models import (
    AnalysisOutcome,
    Commitment,
    DismissedThreadInfo,
    Identity,
    Priority,
    Thread,
)
from app.domain.ports import CommitmentEngine
from app.domain.scoring import score
from app.domain.validation import validate_thread


async def run_analysis(
    *,
    engine: CommitmentEngine,
    threads: list[Thread],
    identity: Identity,
    now: datetime,
    completion_marks: dict[str, datetime] | None = None,
    completion_marks_by_thread: dict[str, datetime] | None = None,
) -> AnalysisOutcome:
    today = now.date()
    marks = completion_marks or {}
    thread_marks = completion_marks_by_thread or {}
    warnings: list[str] = []

    # --- stage 1: extract, per thread -------------------------------------
    extraction = await engine.extract_all(threads, identity, now)
    warnings.extend(extraction.warnings)

    commitments: list[Commitment] = []
    dismissed: list[DismissedThreadInfo] = []

    for thread in threads:
        result = extraction.per_thread.get(thread.thread_key)
        if result is None:
            warnings.append(f"no extraction returned for thread {thread.thread_key}")
            continue

        found, thread_warnings = validate_thread(thread, result, today)
        warnings.extend(thread_warnings)

        if found:
            commitments.extend(found)
        else:
            # Kept, not discarded. A board that silently drops input is
            # indistinguishable from a broken one.
            dismissed.append(
                DismissedThreadInfo(
                    thread_key=thread.thread_key,
                    thread_label=thread.label,
                    source=thread.source,
                    reason=result.dismissal_reason or "No commitments found.",
                )
            )

    commitments = _apply_completion_marks(commitments, marks, thread_marks)

    # --- stage 2: prioritize, one pass over what still needs doing --------
    to_rank = [c for c in commitments if c.is_actionable]
    priorities: dict[str, Priority] = {}
    thinking_summary = ""

    if to_rank:
        output = await engine.prioritize(to_rank, identity, now)
        warnings.extend(output.warnings)
        thinking_summary = output.thinking_summary
        priorities = {
            p.commitment_key: Priority(
                urgency=p.urgency,
                importance=p.importance,
                band=p.band,
                rationale=p.rationale,
                suggested_action=p.suggested_action,
                blocked_by=list(p.blocked_by),
            )
            for p in output.result.priorities
        }
        missing = {c.key for c in to_rank} - set(priorities)
        if missing:
            warnings.append(
                f"{len(missing)} commitment(s) came back without a priority; "
                "they fall back to medium"
            )
        briefing = output.result.daily_briefing
        traces = [extraction.trace, output.trace]
    else:
        briefing = "Nothing outstanding — every commitment is done, cancelled, or someone else's."
        traces = [extraction.trace]

    # --- Python's half: dates, buckets, order -----------------------------
    return AnalysisOutcome(
        scored=score(commitments, priorities, today),
        dismissed=dismissed,
        daily_briefing=briefing,
        thinking_summary=thinking_summary,
        traces=traces,
        warnings=warnings,
        engine=engine.name,
    )


def _apply_completion_marks(
    commitments: list[Commitment],
    marks: dict[str, datetime],
    thread_marks: dict[str, datetime],
) -> list[Commitment]:
    """Re-attach the user's "done" marks to a freshly generated set of rows.

    Primary match is the stable ``commitment_key``. The fallback covers the one
    known weakness: if a re-run cites a different message in the same thread as
    evidence, the key changes and the mark would be orphaned. When a thread
    produced exactly one commitment there is no ambiguity about what the mark
    referred to, so it is safe to re-link by thread.
    """
    per_thread: dict[str, int] = defaultdict(int)
    for c in commitments:
        per_thread[c.thread_key] += 1

    updated: list[Commitment] = []
    for c in commitments:
        completed_at = marks.get(c.key)
        if completed_at is None and per_thread[c.thread_key] == 1:
            completed_at = thread_marks.get(c.thread_key)
        updated.append(c.model_copy(update={"completed_at": completed_at}) if completed_at else c)

    return updated
