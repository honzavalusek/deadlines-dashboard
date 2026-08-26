"""Independent date resolution, in Python.

This exists to *disagree* with the model. The extraction prompt asks for a
resolved ISO date; this module resolves the same phrase separately, and where
the two differ the UI shows "needs confirmation" instead of quietly trusting
either. A mini-eval built into the product.

It is deliberately incomplete. It resolves the patterns it is confident about
and returns ``None`` otherwise — silence means "no opinion", never "the model is
wrong". A half-right resolver that guessed would generate false disagreements
and train the user to ignore the badge.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta

# Czech weekday stems, chosen to survive case declension: "do pátku",
# "na pondělí", "ve středu" all reduce to the same stem.
_WEEKDAY_STEMS: list[tuple[tuple[str, ...], int]] = [
    (("pondělí", "pondelí", "pondeli"), 0),
    (("úterý", "utery", "úter", "uter"), 1),
    (("střed", "stred"), 2),
    (("čtvrt", "ctvrt"), 3),
    (("pátek", "pátku", "patek", "patku"), 4),
    (("sobot",), 5),
    (("neděl", "nedel"), 6),
]

_EN_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

# "3. 9.", "10. 9. 2026", "3.9."
_NUMERIC_DATE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.(?:\s*(\d{4}))?")

_PAST_MARKERS = ("minul", "předminul", "predminul", "last ")
_TOMORROW = ("zítra", "zitra", "tomorrow")
_TODAY = ("dnes", "today")
_END_OF_MONTH = ("konce měsíce", "konce mesice", "end of month", "end of the month")


def _find_weekday(text: str) -> int | None:
    for stems, index in _WEEKDAY_STEMS:
        if any(stem in text for stem in stems):
            return index
    for name, index in _EN_WEEKDAYS.items():
        if name in text:
            return index
    return None


def resolve(raw: str | None, sent_at: datetime) -> date | None:
    """Resolve a deadline phrase against the date its message was sent.

    ``sent_at`` is the anchor: "do pátku" means nothing without knowing which
    week it was written in. Returns ``None`` when unsure.
    """
    if not raw:
        return None

    text = raw.lower().strip()
    anchor = sent_at.date()

    # An explicit day.month wins outright — nothing to infer.
    match = _NUMERIC_DATE.search(text)
    if match:
        day, month, year = int(match[1]), int(match[2]), match[3]
        try:
            return date(int(year) if year else anchor.year, month, day)
        except ValueError:
            return None

    if any(marker in text for marker in _END_OF_MONTH):
        return date(anchor.year, anchor.month, monthrange(anchor.year, anchor.month)[1])

    if any(marker in text for marker in _TOMORROW):
        return anchor + timedelta(days=1)

    if any(marker in text for marker in _TODAY):
        return anchor

    weekday = _find_weekday(text)
    if weekday is None:
        return None

    if any(marker in text for marker in _PAST_MARKERS):
        # "minulý pátek": the most recent such weekday strictly before the anchor.
        delta = (anchor.weekday() - weekday) % 7 or 7
        return anchor - timedelta(days=delta)

    # Forward-looking: this week's occurrence, or today if the anchor is that day.
    return anchor + timedelta(days=(weekday - anchor.weekday()) % 7)


def describe_relative(target: date, today: date) -> str:
    """Human relative form for the UI: 'in 5 days', 'today', '3 days ago'."""
    delta = (target - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    if delta == -1:
        return "yesterday"
    if delta > 0:
        return f"in {delta} days"
    return f"{abs(delta)} days ago"
