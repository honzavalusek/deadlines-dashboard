"""Assembles what the dashboard renders.

Kept out of the route so the route stays a thin adapter: fetch, delegate,
render. This is also what the JSON endpoint returns, so the template is a client
of the service rather than the service itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.repositories import (
    AnalysisRepository,
    CompletionRepository,
    MessageRepository,
    UserRepository,
)
from app.db.tables import User
from app.domain.models import AnalysisOutcome, Message, Priority, ScoredCommitment
from app.domain.ports import CommitmentEngine
from app.domain.scoring import BUCKET_LABELS, group_by_bucket, score, sort_key
from app.services.radar import run_analysis


async def analyse_and_store(
    db: AsyncSession,
    user: User,
    engine: CommitmentEngine,
    settings: Settings,
) -> AnalysisOutcome:
    """Run the pipeline for one user and persist the result."""
    started = datetime.now().astimezone()

    messages = MessageRepository(db)
    completions = CompletionRepository(db)

    outcome = await run_analysis(
        engine=engine,
        threads=await messages.threads_for_user(user.id),
        identity=UserRepository.identity_of(user),
        now=settings.now(),
        completion_marks=await completions.marks_for_user(user.id),
        completion_marks_by_thread=await completions.marks_by_thread(user.id),
    )

    analyses = AnalysisRepository(db)
    await analyses.save_run(user.id, outcome, started)
    await analyses.prune_old_runs(user.id)
    return outcome


async def build_view(
    db: AsyncSession,
    user: User,
    engine: CommitmentEngine,
    settings: Settings,
) -> dict[str, Any]:
    """Everything the dashboard template needs.

    Reads the most recent stored run. Runs the pipeline only if there isn't one
    yet, so a page load never depends on a live API call — the analysis is a
    batch job and the web app reads its output.
    """
    analyses = AnalysisRepository(db)
    run = await analyses.latest_run(user.id)

    if run is None:
        await analyse_and_store(db, user, engine, settings)
        await db.commit()
        run = await analyses.latest_run(user.id)

    pairs = await analyses.commitments_of(run.id)
    dismissals = await analyses.dismissals_of(run.id)
    marks = await CompletionRepository(db).marks_for_user(user.id)
    messages_by_id = await MessageRepository(db).bodies_by_external_id(user.id)

    today = settings.now().date()
    commitments = []
    priorities: dict[str, Priority] = {}
    for commitment, priority in pairs:
        # Marks are re-applied on read: a completion made since the run must
        # take effect immediately, without forcing a re-analysis.
        completed_at = marks.get(commitment.key)
        commitments.append(
            commitment.model_copy(update={"completed_at": completed_at}) if completed_at else commitment
        )
        priorities[commitment.key] = priority

    scored = score(commitments, priorities, today)

    board = [item for item in scored if item.commitment.is_actionable]
    completed = [item for item in scored if item.commitment.is_user_completed]
    detected_done = [
        item for item in scored
        if item.commitment.status == "done" and not item.commitment.is_user_completed
    ]
    cancelled = [item for item in scored if item.commitment.status == "cancelled"]
    not_yours = [item for item in scored if item.commitment.audience == "someone_else"]

    return {
        "user": user,
        "today": today,
        "now": settings.now(),
        "run": run,
        "buckets": group_by_bucket(board),
        "bucket_labels": BUCKET_LABELS,
        "top_priorities": sorted(board, key=sort_key)[:3],
        "board_count": len(board),
        "completed": completed,
        "detected_done": detected_done,
        "cancelled": cancelled,
        "not_yours": not_yours,
        "dismissals": dismissals,
        "messages_by_id": messages_by_id,
        "engine_name": run.engine,
        "settings": settings,
    }


def to_json(view: dict[str, Any]) -> dict[str, Any]:
    """The same view as data, for the JSON endpoint."""

    def item(entry: ScoredCommitment) -> dict[str, Any]:
        c, p = entry.commitment, entry.priority
        return {
            "key": c.key,
            "task": c.task,
            "status": c.status,
            "audience": c.audience,
            "owner": c.owner,
            "current_due": c.current_due.isoformat() if c.current_due else None,
            "original_due": c.original_due.isoformat() if c.original_due else None,
            "days_until_due": entry.days_until_due,
            "bucket": entry.bucket,
            "date_confidence": c.date_confidence,
            "quote_verified": c.quote_verified,
            "priority": {
                "band": p.band,
                "urgency": p.urgency,
                "importance": p.importance,
                "rationale": p.rationale,
                "suggested_action": p.suggested_action,
                "blocked_by": p.blocked_by,
            },
            "evidence": {
                "message_id": c.evidence_message_external_id,
                "quote": c.evidence_quote,
                "due_raw_text": c.due_raw_text,
            },
            "supersede_chain": [
                {
                    "message_id": ch.message_external_id,
                    "from_due": ch.from_due.isoformat() if ch.from_due else None,
                    "to_due": ch.to_due.isoformat() if ch.to_due else None,
                    "reason": ch.reason,
                }
                for ch in c.supersede_chain
            ],
            "completed_at": c.completed_at.isoformat() if c.completed_at else None,
        }

    run = view["run"]
    # Globally ordered by sort_key, NOT grouped by bucket. Each entry carries its
    # bucket so a client can group, but the list order is the canonical judgment
    # order — walking the bucket groups instead would silently discard it, since
    # a critical item due next week sorts after a trivial one due tomorrow.
    board = sorted(
        (e for bucket in view["buckets"] for e in bucket[2]),
        key=sort_key,
    )
    return {
        "as_of": view["now"].isoformat(),
        "engine": run.engine,
        "daily_briefing": run.daily_briefing,
        "board": [item(e) for e in board],
        "off_board": {
            "completed": [item(e) for e in view["completed"]],
            "detected_done": [item(e) for e in view["detected_done"]],
            "cancelled": [item(e) for e in view["cancelled"]],
            "not_yours": [item(e) for e in view["not_yours"]],
        },
        "dismissed_threads": [
            {"thread": d.thread_label, "source": d.source, "reason": d.reason}
            for d in view["dismissals"]
        ],
        "trace": {
            "extract_model": run.extract_model,
            "extract_effort": run.extract_effort,
            "prioritize_model": run.prioritize_model,
            "prioritize_effort": run.prioritize_effort,
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "cost_usd_estimate": round(run.cost_usd, 4),
            "latency_ms": run.latency_ms,
        },
        "warnings": run.warnings,
    }
