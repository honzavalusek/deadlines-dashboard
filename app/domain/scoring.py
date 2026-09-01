"""Deterministic placement and ordering. No model involvement.

The division of labour this file exists to enforce: **the model supplies
judgment, Python supplies arithmetic and order.** The model says how urgent and
how important something is and why; it never says what day that is, how many
days away, or what comes first.

Letting the model emit a sorted array instead would make the ordering unstable
between runs and impossible to explain to the person reading the board.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import NamedTuple

from app.domain.models import (
    Bucket,
    Commitment,
    Priority,
    ScoredCommitment,
)

BUCKET_ORDER: tuple[Bucket, ...] = ("overdue", "today", "this_week", "later", "no_date")

BUCKET_LABELS: dict[Bucket, str] = {
    "overdue": "Overdue",
    "today": "Today",
    "this_week": "This week",
    "later": "Later",
    "no_date": "No date — ask for one",
}

_BAND_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Sorting placeholder for items with no date. Deliberately finite rather than
# math.inf so the sort key stays JSON-serialisable and comparable.
_NO_DATE_SORT = 10_000


def days_until(due: date | None, today: date) -> int | None:
    return None if due is None else (due - today).days


def bucket_for(due: date | None, today: date) -> Bucket:
    """Place a commitment by date.

    "This week" runs to the end of the current calendar week (Sunday), so on a
    Wednesday it means Thursday to Sunday — not a rolling seven days, which
    would put next Tuesday in "this week" and read as a bug.
    """
    if due is None:
        return "no_date"

    delta = (due - today).days
    if delta < 0:
        return "overdue"
    if delta == 0:
        return "today"

    days_left_in_week = 6 - today.weekday()  # Monday == 0
    end_of_week = today + timedelta(days=days_left_in_week)
    return "this_week" if due <= end_of_week else "later"


def sort_key(item: ScoredCommitment) -> tuple[int, int, int]:
    """Total order: priority band, then soonest, then most important.

    Band first because that is the judgment being made. Date second so that
    within one band the calendar still governs. Importance last as a stable
    tie-break, negated so higher sorts first.
    """
    return (
        _BAND_RANK.get(item.priority.band, 9),
        item.days_until_due if item.days_until_due is not None else _NO_DATE_SORT,
        -item.priority.importance,
    )


def score(
    commitments: list[Commitment],
    priorities: dict[str, Priority],
    today: date,
) -> list[ScoredCommitment]:
    """Attach priority and computed placement, then order deterministically."""
    scored = [
        ScoredCommitment(
            commitment=c,
            priority=priorities.get(c.key, Priority()),
            bucket=bucket_for(c.current_due, today),
            days_until_due=days_until(c.current_due, today),
        )
        for c in commitments
    ]
    return sorted(scored, key=sort_key)


class BucketGroup(NamedTuple):
    """One rendered bucket. A NamedTuple so callers can read ``group.items``
    while the template's ``for bucket, label, items in buckets`` still works."""

    bucket: Bucket
    label: str
    items: list[ScoredCommitment]


def group_by_bucket(scored: list[ScoredCommitment]) -> list[BucketGroup]:
    """Group the board into buckets, each internally sorted by ``sort_key``.

    Empty buckets are dropped: an empty column reads as a bug rather than as
    good news.
    """
    grouped: dict[Bucket, list[ScoredCommitment]] = {b: [] for b in BUCKET_ORDER}
    for item in scored:
        grouped[item.bucket].append(item)

    return [
        BucketGroup(bucket, BUCKET_LABELS[bucket], sorted(items, key=sort_key))
        for bucket in BUCKET_ORDER
        if (items := grouped[bucket])
    ]
