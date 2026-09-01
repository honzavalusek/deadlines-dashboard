"""Human-readable relative dates for the UI, in Python.

Dates that the model resolves are never re-derived from natural language
here — this module only formats an already-resolved date relative to today
(e.g. "in 5 days", "yesterday") for display.
"""

from __future__ import annotations

from datetime import date


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
