"""The real engine: two Claude calls per analysis.

Stage 1 maps over threads concurrently at ``medium`` effort. Stage 2 reduces the
whole set in one call at ``high`` effort, with adaptive thinking, and keeps the
summarised reasoning for the audit panel.

The effort split runs the opposite way to intuition, and that is deliberate.
Prioritisation sounds like the harder problem, but it ranks an already-clean
table. The subtler reasoning is in extraction: resolving "do pátku" against the
date of the message it appears in, noticing that a later message supersedes an
earlier deadline rather than adding a second task, and reading "dodavatel
odstoupil" as a cancellation. That is where the headroom goes.

Both stages use ``messages.parse`` with a Pydantic model, so the response is
schema-validated before it reaches us. Note that ``output_format`` and
``output_config`` compose: the SDK merges the generated schema into whatever
``output_config`` we pass, so ``effort`` survives.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

import anthropic

from app.config import Settings
from app.domain.models import (
    Commitment,
    ExtractionOutput,
    Identity,
    PrioritizationOutput,
    PrioritizationResult,
    StageTrace,
    Thread,
    ThreadExtraction,
)

log = logging.getLogger(__name__)

PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# Streaming isn't needed at these output sizes, and 16k keeps us clear of the
# SDK's non-streaming timeout while leaving room for a long thread.
MAX_TOKENS = 16_000


def _load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def _fill(template: str, **values: str) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def _render_identity(identity: Identity) -> dict[str, str]:
    return {
        "PERSON": identity.display_name.split()[0] or identity.display_name,
        "DISPLAY_NAME": identity.display_name,
        "ALIASES": ", ".join(identity.aliases) or "(none recorded)",
        "EMAILS": ", ".join(identity.emails) or "(none recorded)",
        "PROJECTS": ", ".join(identity.projects) or "(none recorded)",
    }


def _render_thread(thread: Thread, tz) -> str:
    """Render messages with weekday and local time.

    The weekday name is load-bearing: "do pátku" cannot be resolved from an ISO
    timestamp alone without the model doing calendar arithmetic in its head,
    which is exactly what we don't want it doing.
    """
    lines = []
    for message in thread.messages:
        local = message.sent_at.astimezone(tz)
        lines.append(
            f"### Message `{message.external_id}`\n"
            f"- From: {message.author}\n"
            f"- Sent: {local:%A %d %B %Y, %H:%M} ({local:%z})\n\n"
            f"{message.body}\n"
        )
    return "\n".join(lines)


def _render_commitments(commitments: list[Commitment], tz) -> str:
    lines = []
    for c in commitments:
        due = c.current_due.isoformat() if c.current_due else "no date stated"
        moved = ""
        if c.supersede_chain:
            moved = " (already moved: " + "; ".join(
                f"{ch.from_due} -> {ch.to_due or 'cancelled'} because {ch.reason}"
                for ch in c.supersede_chain
            ) + ")"
        lines.append(
            f"### `{c.key}`\n"
            f"- Task: {c.task}\n"
            f"- Due: {due}{moved}\n"
            f"- Confidence in that date: {c.date_confidence}"
            f"{' — DATE NEVER AGREED' if c.status == 'ambiguous' else ''}\n"
            f"- Directed at: {c.audience} ({c.audience_reason})\n"
            f"- From: {c.source} — {c.thread_label}\n"
            f"- Evidence: “{c.evidence_quote}”\n"
            f"- Extraction notes: {c.reasoning}\n"
        )
    return "\n".join(lines)


class ClaudeCommitmentEngine:
    """Implementation of :class:`app.domain.ports.CommitmentEngine`."""

    name = "claude"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._extract_template = _load_prompt("extract.md")
        self._prioritize_template = _load_prompt("prioritize.md")

    # -- stage 1 -----------------------------------------------------------

    async def extract_all(
        self,
        threads: list[Thread],
        identity: Identity,
        now: datetime,
    ) -> ExtractionOutput:
        settings = self._settings
        # Bounded concurrency: enough to keep the wall clock short, low enough
        # not to trip rate limits on a fresh key.
        gate = asyncio.Semaphore(settings.max_concurrent_extractions)
        started = time.perf_counter()

        async def one(thread: Thread) -> tuple[str, ThreadExtraction | None, dict[str, int]]:
            async with gate:
                return await self._extract_thread(thread, identity, now)

        # return_exceptions: one bad thread must degrade to a warning, not blank
        # the whole page.
        results = await asyncio.gather(*(one(t) for t in threads), return_exceptions=True)

        per_thread: dict[str, ThreadExtraction] = {}
        warnings: list[str] = []
        usage = {"input": 0, "output": 0, "cached": 0}

        # strict: gather preserves order and length, and this pairing is what
        # attributes a failure to the right thread. If that ever stopped holding,
        # silently zipping short would mislabel every warning after the gap.
        for thread, result in zip(threads, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("extraction failed for %s: %s", thread.thread_key, result)
                warnings.append(f"{thread.label}: extraction failed ({type(result).__name__})")
                per_thread[thread.thread_key] = ThreadExtraction(
                    commitments=[],
                    dismissal_reason=f"Extraction failed for this thread: {type(result).__name__}.",
                )
                continue

            key, extraction, counts = result
            per_thread[key] = extraction or ThreadExtraction(
                commitments=[], dismissal_reason="Model returned no structured output."
            )
            for field in usage:
                usage[field] += counts.get(field, 0)

        return ExtractionOutput(
            per_thread=per_thread,
            trace=StageTrace(
                stage="extract",
                model=settings.extract_model,
                effort=settings.extract_effort,
                calls=len(threads),
                input_tokens=usage["input"],
                output_tokens=usage["output"],
                cached_tokens=usage["cached"],
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
            warnings=warnings,
        )

    async def _extract_thread(
        self,
        thread: Thread,
        identity: Identity,
        now: datetime,
    ) -> tuple[str, ThreadExtraction | None, dict[str, int]]:
        settings = self._settings
        prompt = _fill(
            self._extract_template,
            **_render_identity(identity),
            NOW=f"{now:%A %d %B %Y}",
            SOURCE=thread.source,
            THREAD_LABEL=thread.label,
            MESSAGES=_render_thread(thread, settings.tz),
        )

        response = await self._client.messages.parse(
            model=settings.extract_model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            output_format=ThreadExtraction,
            output_config={"effort": settings.extract_effort},
            thinking={"type": "adaptive"},
        )

        if response.stop_reason == "max_tokens":
            raise RuntimeError("extraction hit max_tokens before finishing")
        if response.stop_reason == "refusal":
            raise RuntimeError(f"extraction refused: {getattr(response.stop_details, 'category', '?')}")

        return thread.thread_key, response.parsed_output, _usage_of(response)

    # -- stage 2 -----------------------------------------------------------

    async def prioritize(
        self,
        commitments: list[Commitment],
        identity: Identity,
        now: datetime,
    ) -> PrioritizationOutput:
        settings = self._settings
        started = time.perf_counter()

        prompt = _fill(
            self._prioritize_template,
            **_render_identity(identity),
            NOW=f"{now:%A %d %B %Y}",
            COMMITMENTS=_render_commitments(commitments, settings.tz),
        )

        try:
            response = await self._client.messages.parse(
                model=settings.prioritize_model,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                output_format=PrioritizationResult,
                output_config={"effort": settings.prioritize_effort},
                # display="summarized" is opt-in: the default omits the text, and
                # the audit panel is meant to show how the ranking was reasoned.
                thinking={"type": "adaptive", "display": "summarized"},
            )
        except anthropic.APIError as exc:
            log.warning("prioritisation failed: %s", exc)
            return PrioritizationOutput(
                result=PrioritizationResult(
                    daily_briefing="Prioritisation is unavailable for this run; "
                    "the board below is ordered by date only."
                ),
                trace=StageTrace(
                    stage="prioritize",
                    model=settings.prioritize_model,
                    effort=settings.prioritize_effort,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                ),
                warnings=[f"prioritisation call failed: {type(exc).__name__}"],
            )

        warnings: list[str] = []
        if response.stop_reason == "max_tokens":
            warnings.append("prioritisation hit max_tokens; some items may be unranked")

        usage = _usage_of(response)
        return PrioritizationOutput(
            result=response.parsed_output or PrioritizationResult(),
            trace=StageTrace(
                stage="prioritize",
                model=settings.prioritize_model,
                effort=settings.prioritize_effort,
                calls=1,
                input_tokens=usage["input"],
                output_tokens=usage["output"],
                cached_tokens=usage["cached"],
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
            thinking_summary=_thinking_of(response),
            warnings=warnings,
        )


def _usage_of(response) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input": 0, "output": 0, "cached": 0}
    return {
        "input": getattr(usage, "input_tokens", 0) or 0,
        "output": getattr(usage, "output_tokens", 0) or 0,
        "cached": getattr(usage, "cache_read_input_tokens", 0) or 0,
    }


def _thinking_of(response) -> str:
    parts = [
        block.thinking
        for block in getattr(response, "content", []) or []
        if getattr(block, "type", None) == "thinking" and getattr(block, "thinking", "")
    ]
    return "\n\n".join(parts)
