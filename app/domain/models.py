"""Pure domain models. No I/O, no SQL, no HTTP.

Two layers on purpose:

* ``*Draft`` models are the LLM's structured-output schema. Dates are ISO
  *strings* here, because the model must not be trusted to do date arithmetic
  and because a malformed date should be a validation finding rather than a
  crash inside the SDK.
* The non-draft models are the validated domain objects the rest of the app
  works with. Dates are real ``date`` objects, and the extra flags record what
  validation discovered.

The conversion between them lives in ``app.domain.validation``.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------
# Enumerations (Literal rather than Enum: these serialise into the JSON schema
# the model is constrained to, and Literal keeps that schema flat and readable)
# --------------------------------------------------------------------------

Source = Literal["slack", "email"]

CommitmentStatus = Literal["active", "moved", "cancelled", "done", "ambiguous"]
"""``moved`` keeps its history in ``supersede_chain``; ``done`` is the model's
inference from thread text, which is weaker than a user's explicit mark."""

Audience = Literal["me", "my_team", "someone_else"]
"""Whether the commitment is actually directed at the logged-in user. Three
values rather than a boolean: "your project owes this" is neither personally
mine nor somebody else's, and collapsing it either way is wrong."""

DueKind = Literal["explicit", "relative", "implied", "recurring", "none"]
Confidence = Literal["high", "medium", "low"]
PriorityBand = Literal["critical", "high", "medium", "low"]

Bucket = Literal["overdue", "today", "this_week", "later", "no_date"]


# --------------------------------------------------------------------------
# Conversation input
# --------------------------------------------------------------------------


class Message(BaseModel):
    """One Slack message or email, normalised across both sources."""

    model_config = ConfigDict(frozen=True)

    external_id: str
    thread_key: str
    source: Source
    author: str
    sent_at: datetime
    body: str
    channel: str | None = None
    subject: str | None = None

    @property
    def context_label(self) -> str:
        """How the message is described in prompts and in the UI popover."""
        return self.channel or self.subject or self.thread_key


class Thread(BaseModel):
    """A conversation. The unit of extraction.

    Extraction runs per *thread*, never per message: a deadline that moves
    twice is one commitment with a history, and only the whole thread contains
    the evidence for that.
    """

    model_config = ConfigDict(frozen=True)

    thread_key: str
    source: Source
    messages: tuple[Message, ...]

    @property
    def label(self) -> str:
        return self.messages[0].context_label if self.messages else self.thread_key


class Identity(BaseModel):
    """Who "me" is, so the model can judge ``audience``.

    ``projects`` is what makes ``my_team`` decidable — without it there is
    nothing in "the pricing page still has no copy" to tell the model whether
    that sentence is aimed at this user or at somebody else.
    """

    display_name: str
    aliases: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Stage 1 output — what the extraction call returns
# --------------------------------------------------------------------------


class DueChangeDraft(BaseModel):
    """One step in a deadline's history, as reported by the model."""

    message_external_id: str
    from_due: str | None = Field(description="Previous due date, ISO 8601 (YYYY-MM-DD), or null.")
    to_due: str | None = Field(description="New due date, ISO 8601 (YYYY-MM-DD), or null if cancelled.")
    reason: str = Field(description="Why it changed, in English, one short clause.")


class CommitmentDraft(BaseModel):
    """A single obligation as extracted from one thread.

    Every natural-language field is English regardless of the source language,
    with two deliberate exceptions: ``evidence_quote`` and ``due_raw_text`` are
    verbatim citations and must not be translated.
    """

    task: str = Field(description="Imperative, second person, English. e.g. 'Send the MSA redlines to counsel'.")
    status: CommitmentStatus
    owner: str = Field(description="Who is on the hook, named as in the thread.")
    audience: Audience
    audience_reason: str = Field(description="One clause, English, explaining the audience choice.")

    original_due: str | None = Field(description="First agreed due date, ISO 8601 (YYYY-MM-DD), or null.")
    current_due: str | None = Field(description="Due date in force now, ISO 8601 (YYYY-MM-DD), or null.")
    due_kind: DueKind
    date_confidence: Confidence
    due_raw_text: str | None = Field(
        description="The span naming the deadline, copied VERBATIM from the message "
        "in its original language. Do not translate. Null if no date was stated."
    )

    evidence_message_external_id: str = Field(description="external_id of the message this came from.")
    evidence_quote: str = Field(description="Verbatim quote in the ORIGINAL language. Do not translate.")
    supersede_chain: list[DueChangeDraft] = Field(default_factory=list)
    reasoning: str = Field(description="Why this is a real commitment and how the date was resolved. English.")


class ThreadExtraction(BaseModel):
    """Stage 1 result for one thread. ``commitments`` is often empty."""

    commitments: list[CommitmentDraft] = Field(default_factory=list)
    dismissal_reason: str | None = Field(
        default=None,
        description="If no commitments were found, one sentence in English saying why. "
        "Shown to the user, so it must be specific: 'small talk and a deploy notification, "
        "no obligations' rather than 'nothing found'.",
    )


# --------------------------------------------------------------------------
# Stage 2 output — comparative prioritisation over the whole set
# --------------------------------------------------------------------------


def _clamp_0_100(value: int) -> int:
    """Structured-output schemas can't carry numeric bounds, so clamp here.

    A ``Field(ge=0, le=100)`` would raise a client-side ValidationError when the
    model returns 120 — throwing away a whole good response over one field.
    """
    return max(0, min(100, value))


class PriorityDraft(BaseModel):
    """The model's judgment for one commitment. Note it does not rank.

    Ordering is computed in Python from these scores. Letting the model emit a
    sorted array instead makes the order unstable between runs and impossible
    to explain.
    """

    commitment_key: str
    urgency: int = Field(description="0-100. How soon this must be acted on.")
    importance: int = Field(description="0-100. Consequence of it slipping.")
    band: PriorityBand
    rationale: str = Field(description="One sentence, English, on why it sits here relative to the others.")
    suggested_action: str = Field(description="The single next action, English, imperative.")
    blocked_by: list[str] = Field(
        default_factory=list,
        description="commitment_keys this waits on. Cross-thread dependencies belong here.",
    )

    _clamp_urgency = field_validator("urgency")(_clamp_0_100)
    _clamp_importance = field_validator("importance")(_clamp_0_100)


class PrioritizationResult(BaseModel):
    """Stage 2 result for the whole set."""

    priorities: list[PriorityDraft] = Field(default_factory=list)
    daily_briefing: str = Field(
        default="",
        description="Three sentences, English, on what actually matters today. "
        "The only part of this app a busy person would read.",
    )


# --------------------------------------------------------------------------
# Validated domain objects
# --------------------------------------------------------------------------


def commitment_key(thread_key: str, evidence_message_external_id: str) -> str:
    """Stable identity for a commitment, across re-analyses.

    Both inputs survive a re-run: ``thread_key`` is derived from the source
    conversation and the evidence id points at a real message. ``task`` is
    deliberately excluded — it is model-generated prose whose wording drifts
    between runs, which would silently orphan every completion mark.
    """
    return hashlib.sha256(f"{thread_key}|{evidence_message_external_id}".encode()).hexdigest()[:16]


class Commitment(BaseModel):
    """A validated commitment, with everything validation learned about it."""

    key: str
    thread_key: str
    source: Source
    thread_label: str

    task: str
    status: CommitmentStatus
    owner: str
    audience: Audience
    audience_reason: str

    original_due: date | None = None
    current_due: date | None = None
    due_kind: DueKind = "none"
    date_confidence: Confidence = "medium"
    due_raw_text: str | None = None

    evidence_message_external_id: str
    evidence_quote: str
    supersede_chain: list[DueChange] = Field(default_factory=list)
    reasoning: str = ""

    # --- findings from validation, not from the model ---
    quote_verified: bool = True
    """False when ``due_raw_text`` was not found verbatim in the cited message
    — i.e. the model may have invented the date. Surfaces as a badge."""

    date_disagreement: str | None = None
    """Set when Python's own resolution of a relative date disagrees with the
    model's. A visible 'needs confirmation', not a silent overwrite."""

    alternative_dues: list[date] = Field(default_factory=list)
    """Other candidate dates found in an unresolved thread (conflicting dates)."""

    # --- user state ---
    completed_at: datetime | None = None

    @property
    def is_user_completed(self) -> bool:
        """An explicit mark. Outranks ``status == 'done'``, which is a guess."""
        return self.completed_at is not None

    @property
    def is_actionable(self) -> bool:
        """Belongs on the board, as opposed to one of the audit panels."""
        return (
            not self.is_user_completed
            and self.audience in ("me", "my_team")
            and self.status in ("active", "moved", "ambiguous")
        )


class DueChange(BaseModel):
    message_external_id: str
    from_due: date | None = None
    to_due: date | None = None
    reason: str = ""


class Priority(BaseModel):
    urgency: int = 50
    importance: int = 50
    band: PriorityBand = "medium"
    rationale: str = ""
    suggested_action: str = ""
    blocked_by: list[str] = Field(default_factory=list)


class ScoredCommitment(BaseModel):
    """A commitment plus its priority and computed placement.

    ``bucket``, ``days_until_due`` and the sort position are all Python's work.
    """

    commitment: Commitment
    priority: Priority
    bucket: Bucket
    days_until_due: int | None = None


Commitment.model_rebuild()
