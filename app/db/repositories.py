"""Repositories: the only place SQL lives, and the only place rows become
domain objects.

Every method that touches user-owned data takes ``user_id`` as a parameter
rather than filtering somewhere upstream. Scoping is a property of the query,
not a convention the caller is trusted to remember.

These are plain concrete classes, not Protocols. There is exactly one
implementation and there always will be; an interface here would be
indirection with nothing to justify it. (``CommitmentEngine`` is different;
see ``app.domain.ports``.)
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import (
    AnalysisRun,
    CommitmentRow,
    CompletionMark,
    DismissedThread,
    User,
    from_utc,
    to_utc,
)
from app.db.tables import (
    Message as MessageRow,
)
from app.domain.models import (
    AnalysisOutcome,
    Commitment,
    DueChange,
    Identity,
    Message,
    Priority,
    Thread,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email.lower().strip()))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        aliases: list[str],
        alt_emails: list[str],
        projects: list[str],
        timezone_name: str = "Europe/Prague",
    ) -> User:
        user = User(
            email=email.lower().strip(),
            password_hash=password_hash,
            display_name=display_name,
            aliases=aliases,
            alt_emails=alt_emails,
            projects=projects,
            timezone_name=timezone_name,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    @staticmethod
    def identity_of(user: User) -> Identity:
        return Identity(
            display_name=user.display_name,
            aliases=list(user.aliases or []),
            emails=[user.email, *(user.alt_emails or [])],
            projects=list(user.projects or []),
        )


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(self, user_id: int, messages: list[dict[str, Any]]) -> int:
        for m in messages:
            self._session.add(
                MessageRow(
                    user_id=user_id,
                    source=m["source"],
                    external_id=m["external_id"],
                    thread_key=m["thread_key"],
                    author=m["author"],
                    sent_at=to_utc(m["sent_at"]),
                    body=m["body"],
                    channel=m.get("channel"),
                    subject=m.get("subject"),
                )
            )
        await self._session.flush()
        return len(messages)

    async def threads_for_user(self, user_id: int) -> list[Thread]:
        """All of a user's conversations, grouped and chronologically ordered.

        Threads, not messages, because extraction happens per thread: a deadline
        that moves is one commitment with a history, and only the whole thread
        holds the evidence for that.
        """
        result = await self._session.execute(
            select(MessageRow)
            .where(MessageRow.user_id == user_id)
            .order_by(MessageRow.thread_key, MessageRow.sent_at)
        )
        grouped: dict[str, list[Message]] = {}
        for row in result.scalars():
            grouped.setdefault(row.thread_key, []).append(self._to_domain(row))

        return [
            Thread(thread_key=key, source=msgs[0].source, messages=tuple(msgs))
            for key, msgs in grouped.items()
        ]

    async def bodies_by_external_id(self, user_id: int) -> dict[str, Message]:
        """Lookup used by the hover popover and by the verbatim-quote guard."""
        result = await self._session.execute(
            select(MessageRow).where(MessageRow.user_id == user_id)
        )
        return {row.external_id: self._to_domain(row) for row in result.scalars()}

    @staticmethod
    def _to_domain(row: MessageRow) -> Message:
        return Message(
            external_id=row.external_id,
            thread_key=row.thread_key,
            source=row.source,  # type: ignore[arg-type]
            author=row.author,
            sent_at=from_utc(row.sent_at),
            body=row.body,
            channel=row.channel,
            subject=row.subject,
        )


class CompletionRepository:
    """Completion marks. Independent of any run — that is the whole point."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def marks_for_user(self, user_id: int) -> dict[str, datetime]:
        result = await self._session.execute(
            select(CompletionMark).where(CompletionMark.user_id == user_id)
        )
        return {m.commitment_key: from_utc(m.completed_at) for m in result.scalars()}

    async def marks_by_thread(self, user_id: int) -> dict[str, datetime]:
        """Fallback index for re-linking a mark when the evidence message moved."""
        result = await self._session.execute(
            select(CompletionMark).where(CompletionMark.user_id == user_id)
        )
        return {m.thread_key: from_utc(m.completed_at) for m in result.scalars()}

    async def mark(self, user_id: int, commitment_key: str, thread_key: str) -> None:
        existing = await self._session.execute(
            select(CompletionMark).where(
                CompletionMark.user_id == user_id,
                CompletionMark.commitment_key == commitment_key,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return  # idempotent: double-submit must not create a second row
        self._session.add(
            CompletionMark(
                user_id=user_id,
                commitment_key=commitment_key,
                thread_key=thread_key,
                completed_at=datetime.now(UTC),
            )
        )
        await self._session.flush()

    async def unmark(self, user_id: int, commitment_key: str) -> None:
        await self._session.execute(
            delete(CompletionMark).where(
                CompletionMark.user_id == user_id,
                CompletionMark.commitment_key == commitment_key,
            )
        )


class AnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_run(self, user_id: int) -> AnalysisRun | None:
        result = await self._session.execute(
            select(AnalysisRun)
            .where(AnalysisRun.user_id == user_id, AnalysisRun.finished_at.is_not(None))
            .order_by(AnalysisRun.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def commitments_of(self, run_id: int) -> list[tuple[Commitment, Priority]]:
        result = await self._session.execute(
            select(CommitmentRow).where(CommitmentRow.run_id == run_id)
        )
        return [self._to_domain(row) for row in result.scalars()]

    async def dismissals_of(self, run_id: int) -> list[DismissedThread]:
        result = await self._session.execute(
            select(DismissedThread).where(DismissedThread.run_id == run_id)
        )
        return list(result.scalars())


    async def save_run(self, user_id: int, outcome: AnalysisOutcome, started_at: datetime) -> AnalysisRun:
        """Persist a completed run.

        ``finished_at`` is set last and ``latest_run`` filters on it being
        non-null, so a run that dies partway through is never served to the
        dashboard as if it were complete.
        """
        extract = next((t for t in outcome.traces if t.stage == "extract"), None)
        prioritize = next((t for t in outcome.traces if t.stage == "prioritize"), None)

        run = AnalysisRun(
            user_id=user_id,
            started_at=to_utc(started_at),
            finished_at=None,
            engine=outcome.engine,
            extract_model=extract.model if extract else None,
            extract_effort=extract.effort if extract else None,
            prioritize_model=prioritize.model if prioritize else None,
            prioritize_effort=prioritize.effort if prioritize else None,
            input_tokens=sum(t.input_tokens for t in outcome.traces),
            output_tokens=sum(t.output_tokens for t in outcome.traces),
            cached_tokens=sum(t.cached_tokens for t in outcome.traces),
            cost_usd=outcome.total_cost_usd,
            latency_ms=sum(t.latency_ms for t in outcome.traces),
            daily_briefing=outcome.daily_briefing,
            thinking_summary=outcome.thinking_summary,
            warnings=list(outcome.warnings),
        )
        self._session.add(run)
        await self._session.flush()

        for item in outcome.scored:
            c, pr = item.commitment, item.priority
            self._session.add(
                CommitmentRow(
                    run_id=run.id,
                    commitment_key=c.key,
                    thread_key=c.thread_key,
                    source=c.source,
                    thread_label=c.thread_label,
                    task=c.task,
                    status=c.status,
                    owner=c.owner,
                    audience=c.audience,
                    audience_reason=c.audience_reason,
                    original_due=c.original_due,
                    current_due=c.current_due,
                    due_kind=c.due_kind,
                    date_confidence=c.date_confidence,
                    due_raw_text=c.due_raw_text,
                    evidence_message_external_id=c.evidence_message_external_id,
                    evidence_quote=c.evidence_quote,
                    supersede_chain=[ch.model_dump(mode="json") for ch in c.supersede_chain],
                    reasoning=c.reasoning,
                    quote_verified=c.quote_verified,
                    alternative_dues=[d.isoformat() for d in c.alternative_dues],
                    urgency=pr.urgency,
                    importance=pr.importance,
                    band=pr.band,
                    rationale=pr.rationale,
                    suggested_action=pr.suggested_action,
                    blocked_by=list(pr.blocked_by),
                )
            )

        for d in outcome.dismissed:
            self._session.add(
                DismissedThread(
                    run_id=run.id,
                    thread_key=d.thread_key,
                    thread_label=d.thread_label,
                    source=d.source,
                    reason=d.reason,
                )
            )

        run.finished_at = to_utc(datetime.now(UTC))
        await self._session.flush()
        return run

    async def prune_old_runs(self, user_id: int, keep: int = 5) -> int:
        """Keep the run history bounded; re-running during a demo is cheap."""
        result = await self._session.execute(
            select(AnalysisRun.id)
            .where(AnalysisRun.user_id == user_id)
            .order_by(AnalysisRun.started_at.desc())
            .offset(keep)
        )
        stale = list(result.scalars())
        for run_id in stale:
            run = await self._session.get(AnalysisRun, run_id)
            if run is not None:
                await self._session.delete(run)
        return len(stale)

    @staticmethod
    def _to_domain(row: CommitmentRow) -> tuple[Commitment, Priority]:
        commitment = Commitment(
            key=row.commitment_key,
            thread_key=row.thread_key,
            source=row.source,  # type: ignore[arg-type]
            thread_label=row.thread_label,
            task=row.task,
            status=row.status,  # type: ignore[arg-type]
            owner=row.owner,
            audience=row.audience,  # type: ignore[arg-type]
            audience_reason=row.audience_reason,
            original_due=row.original_due,
            current_due=row.current_due,
            due_kind=row.due_kind,  # type: ignore[arg-type]
            date_confidence=row.date_confidence,  # type: ignore[arg-type]
            due_raw_text=row.due_raw_text,
            evidence_message_external_id=row.evidence_message_external_id,
            evidence_quote=row.evidence_quote,
            supersede_chain=[DueChange(**c) for c in (row.supersede_chain or [])],
            reasoning=row.reasoning,
            quote_verified=row.quote_verified,
            alternative_dues=[date.fromisoformat(d) for d in (row.alternative_dues or [])],
        )
        priority = Priority(
            urgency=row.urgency,
            importance=row.importance,
            band=row.band,  # type: ignore[arg-type]
            rationale=row.rationale,
            suggested_action=row.suggested_action,
            blocked_by=list(row.blocked_by or []),
        )
        return commitment, priority
