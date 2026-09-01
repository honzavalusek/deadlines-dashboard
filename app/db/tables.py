"""SQLAlchemy 2.0 declarative tables.

Kept separate from the Pydantic domain models on purpose. SQLModel exists to
fuse the two into one class; this design wants them apart, so that the schema
the LLM is constrained to cannot drift because of a persistence concern. The
cost is one explicit mapping function per model, in ``app.db.repositories``.

Datetime convention: every stored datetime is **UTC**. SQLite drops timezone
offsets, so storing local times would silently corrupt them. Values are
converted to UTC on write and re-tagged as UTC on read; presentation converts
to the user's zone.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, overload

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def to_utc(value: datetime) -> datetime:
    """Normalise an aware datetime to UTC for storage."""
    if value.tzinfo is None:
        raise ValueError(f"refusing to store a naive datetime: {value!r}")
    return value.astimezone(UTC)


@overload
def from_utc(value: datetime) -> datetime: ...
@overload
def from_utc(value: None) -> None: ...


def from_utc(value: datetime | None) -> datetime | None:
    """Re-tag a value read back from SQLite as UTC. Overloaded so a non-nullable
    column doesn't come back ``Optional``.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255))

    # Identity the extraction prompt reasons against. `projects` is what makes
    # an `audience: my_team` judgment possible at all.
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    alt_emails: Mapped[list[str]] = mapped_column(JSON, default=list)
    projects: Mapped[list[str]] = mapped_column(JSON, default=list)
    timezone_name: Mapped[str] = mapped_column(String(64), default="Europe/Prague")

    messages: Mapped[list[Message]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Message(Base):
    """A Slack message or email belonging to one user."""

    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("user_id", "external_id", name="uq_message_user_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(255))
    thread_key: Mapped[str] = mapped_column(String(255), index=True)
    author: Mapped[str] = mapped_column(String(255))
    sent_at: Mapped[datetime] = mapped_column(DateTime)  # UTC, see module docstring
    body: Mapped[str] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship(back_populates="messages")


class AnalysisRun(Base):
    """One execution of the pipeline. The dashboard renders the latest run.

    The pipeline is a batch job and the web app reads its output; keeping runs
    as rows means the dashboard renders instantly and never depends on a live
    API call.
    """

    __tablename__ = "analysis_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    engine: Mapped[str] = mapped_column(String(32))

    # Per-stage trace. Renders in the audit footer; this is the evidence behind
    # the model-tiering claim rather than an assertion about it.
    extract_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extract_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    prioritize_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prioritize_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    daily_briefing: Mapped[str] = mapped_column(Text, default="")
    thinking_summary: Mapped[str] = mapped_column(Text, default="")
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    commitments: Mapped[list[CommitmentRow]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    dismissals: Mapped[list[DismissedThread]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class CommitmentRow(Base):
    """A commitment as produced by one run. Regenerated every run — which is
    exactly why completion state must not live here (see CompletionMark)."""

    __tablename__ = "commitments"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)

    commitment_key: Mapped[str] = mapped_column(String(64), index=True)
    thread_key: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16))
    thread_label: Mapped[str] = mapped_column(String(255))

    task: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    owner: Mapped[str] = mapped_column(String(255))
    audience: Mapped[str] = mapped_column(String(16))
    audience_reason: Mapped[str] = mapped_column(Text, default="")

    original_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_kind: Mapped[str] = mapped_column(String(16), default="none")
    date_confidence: Mapped[str] = mapped_column(String(16), default="medium")
    due_raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    evidence_message_external_id: Mapped[str] = mapped_column(String(255))
    evidence_quote: Mapped[str] = mapped_column(Text)
    supersede_chain: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reasoning: Mapped[str] = mapped_column(Text, default="")

    quote_verified: Mapped[bool] = mapped_column(Boolean, default=True)
    alternative_dues: Mapped[list[str]] = mapped_column(JSON, default=list)

    urgency: Mapped[int] = mapped_column(Integer, default=50)
    importance: Mapped[int] = mapped_column(Integer, default=50)
    band: Mapped[str] = mapped_column(String(16), default="medium")
    rationale: Mapped[str] = mapped_column(Text, default="")
    suggested_action: Mapped[str] = mapped_column(Text, default="")
    blocked_by: Mapped[list[str]] = mapped_column(JSON, default=list)

    run: Mapped[AnalysisRun] = relationship(back_populates="commitments")


class DismissedThread(Base):
    """A thread the pipeline deliberately found nothing in.

    Kept and shown. A dashboard that silently drops input is indistinguishable
    from a broken one; showing the rejections with reasons is what makes the
    rest of the board credible.
    """

    __tablename__ = "dismissed_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("analysis_runs.id"), index=True)

    thread_key: Mapped[str] = mapped_column(String(255))
    thread_label: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="")

    run: Mapped[AnalysisRun] = relationship(back_populates="dismissals")


class CompletionMark(Base):
    """A user saying "this is done".

    Belongs to the **user**, not to a run. Commitment rows are thrown away and
    regenerated on every analysis, so storing completion there would mean a
    completed item marches back onto the board after a re-run — the single most
    annoying bug this kind of app can have. Keyed on the stable
    ``commitment_key`` so it survives.
    """

    __tablename__ = "completion_marks"
    __table_args__ = (UniqueConstraint("user_id", "commitment_key", name="uq_completion_user_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    commitment_key: Mapped[str] = mapped_column(String(64), index=True)
    thread_key: Mapped[str] = mapped_column(String(255))
    """Fallback match: if a re-run cites a different evidence message the key
    changes, but a thread with exactly one commitment can still be re-linked."""
    completed_at: Mapped[datetime] = mapped_column(DateTime)
