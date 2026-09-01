"""Small presentation helpers registered as Jinja filters."""

from __future__ import annotations

from datetime import date, datetime

from markupsafe import Markup, escape


def render_body(body: str) -> Markup:
    """Escape a message body for the hover popover, preserving line breaks."""
    return Markup(str(escape(body)).replace("\n", "<br>"))


def day(value: date | datetime | None) -> str:
    """Short English date: 'Thu 3 Sep'. The UI is English throughout."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        value = value.date()
    return f"{value:%a} {value.day} {value:%b}"


def stamp(value: datetime | None, tz=None) -> str:
    if value is None:
        return "—"
    if tz is not None:
        value = value.astimezone(tz)
    return f"{value:%a} {value.day} {value:%b}, {value:%H:%M}"


def money(value: float) -> str:
    return f"${value:,.4f}" if value < 1 else f"${value:,.2f}"
