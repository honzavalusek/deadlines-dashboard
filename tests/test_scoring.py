"""Bucket boundaries against a frozen clock.

Boundaries are where date logic actually breaks, and a frozen "now" is what
makes the assertions meaningful — with a real clock these pass today and fail on
Sunday.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.models import Commitment, Priority, ScoredCommitment
from app.domain.scoring import bucket_for, days_until, sort_key

WEDNESDAY = date(2026, 9, 2)


@pytest.mark.parametrize(
    ("due", "expected"),
    [
        (date(2026, 8, 21), "overdue"),
        (date(2026, 9, 1), "overdue"),      # yesterday
        (date(2026, 9, 2), "today"),
        (date(2026, 9, 3), "this_week"),
        (date(2026, 9, 6), "this_week"),    # Sunday, last day of this week
        (date(2026, 9, 7), "later"),        # Monday, next week
        (date(2026, 9, 10), "later"),
        (None, "no_date"),
    ],
)
def test_bucket_boundaries(due, expected):
    assert bucket_for(due, WEDNESDAY) == expected


def test_this_week_ends_on_sunday_not_seven_days_out():
    """A rolling seven days would put next Tuesday in "this week"."""
    assert bucket_for(date(2026, 9, 8), WEDNESDAY) == "later"


def test_bucket_from_a_sunday_has_no_this_week():
    """On the last day of the week, everything future is "later"."""
    sunday = date(2026, 9, 6)
    assert bucket_for(sunday, sunday) == "today"
    assert bucket_for(date(2026, 9, 7), sunday) == "later"


def test_days_until_is_signed():
    assert days_until(date(2026, 8, 21), WEDNESDAY) == -12
    assert days_until(date(2026, 9, 10), WEDNESDAY) == 8
    assert days_until(None, WEDNESDAY) is None


def _entry(task: str, band: str, due: date | None, importance: int = 50) -> ScoredCommitment:
    return ScoredCommitment(
        commitment=Commitment(
            key=task, thread_key="t", source="slack", thread_label="#x", task=task,
            status="active", owner="Jan", audience="me", audience_reason="",
            current_due=due, evidence_message_external_id="m", evidence_quote="q",
        ),
        priority=Priority(band=band, importance=importance),
        bucket=bucket_for(due, WEDNESDAY),
        days_until_due=days_until(due, WEDNESDAY),
    )


def test_band_outranks_date():
    """The whole reason stage 2 exists: judgment beats proximity."""
    statutory = _entry("statutory filing", "critical", date(2026, 9, 10))
    trivial = _entry("alt text", "low", date(2026, 9, 3))
    assert sorted([trivial, statutory], key=sort_key)[0] is statutory


def test_date_breaks_ties_within_a_band():
    later = _entry("later", "high", date(2026, 9, 9))
    sooner = _entry("sooner", "high", date(2026, 9, 4))
    assert sorted([later, sooner], key=sort_key)[0] is sooner


def test_importance_breaks_ties_within_band_and_date():
    dull = _entry("dull", "high", date(2026, 9, 4), importance=20)
    weighty = _entry("weighty", "high", date(2026, 9, 4), importance=90)
    assert sorted([dull, weighty], key=sort_key)[0] is weighty


def test_undated_items_sort_last_within_their_band():
    dated = _entry("dated", "low", date(2026, 9, 30))
    undated = _entry("undated", "low", None)
    assert sorted([undated, dated], key=sort_key)[0] is dated
