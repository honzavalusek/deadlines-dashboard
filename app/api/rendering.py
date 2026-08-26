"""Small presentation helpers registered as Jinja filters."""

from __future__ import annotations

from datetime import date, datetime

from markupsafe import Markup, escape


def highlight(body: str, *spans: str | None) -> Markup:
    """Escape ``body`` and wrap each given span in a ``<mark>``.

    Used in the hover popover so the exact text a claim rests on is visible
    inside the original message. Escaping happens first and the ``<mark>`` tags
    are injected afterwards, so message content can never inject markup.
    """
    rendered = str(escape(body))
    for span in spans:
        if not span:
            continue
        needle = str(escape(span))
        if needle in rendered:
            rendered = rendered.replace(needle, f"<mark>{needle}</mark>", 1)
    return Markup(rendered.replace("\n", "<br>"))


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
