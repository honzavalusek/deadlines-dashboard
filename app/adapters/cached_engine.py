"""Caching decorator over any :class:`~app.domain.ports.CommitmentEngine`.

Stage 1 is deterministic given (thread content, identity, prompt): the same
thread yields the same commitments. Stage 2 is not cached — it is one call, and
it is the call whose prompt you actually want to iterate on.

That asymmetry is the whole point. Tuning the prioritisation prompt otherwise
means re-running every extraction on every attempt: a dozen calls and twenty-odd
seconds per edit. With extractions cached, the loop is one call and a couple of
seconds, which is the difference between iterating on the prompt and giving up
on it.

The cache key includes a hash of the prompt file, so editing ``extract.md``
invalidates it automatically rather than silently serving results from the old
instructions.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.domain.models import (
    Commitment,
    ExtractionOutput,
    Identity,
    PrioritizationOutput,
    StageTrace,
    Thread,
    ThreadExtraction,
)
from app.domain.ports import CommitmentEngine

log = logging.getLogger(__name__)


class CachedCommitmentEngine:
    """Wraps an engine, memoising stage-1 results to disk."""

    def __init__(self, inner: CommitmentEngine, cache_dir: Path, prompt_fingerprint: str) -> None:
        self._inner = inner
        self._dir = cache_dir
        self._fingerprint = prompt_fingerprint
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return self._inner.name

    def _key(self, thread: Thread, identity: Identity, now: datetime) -> str:
        payload = json.dumps(
            {
                "fingerprint": self._fingerprint,
                "thread": [
                    {"id": m.external_id, "author": m.author,
                     "sent": m.sent_at.isoformat(), "body": m.body}
                    for m in thread.messages
                ],
                # Identity changes the audience judgment, so it belongs in the key.
                "identity": identity.model_dump(),
                # "do pátku" resolves against the message date, not today, but
                # the prompt still states today — so it is part of the input.
                "now": now.date().isoformat(),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    async def extract_all(
        self,
        threads: list[Thread],
        identity: Identity,
        now: datetime,
    ) -> ExtractionOutput:
        cached: dict[str, ThreadExtraction] = {}
        misses: list[Thread] = []

        for thread in threads:
            path = self._dir / f"{self._key(thread, identity, now)}.json"
            if path.exists():
                try:
                    cached[thread.thread_key] = ThreadExtraction.model_validate_json(
                        path.read_text(encoding="utf-8")
                    )
                    continue
                except Exception as exc:  # corrupt entry: re-fetch rather than crash
                    log.warning("discarding unreadable cache entry %s: %s", path.name, exc)
                    path.unlink(missing_ok=True)
            misses.append(thread)

        if not misses:
            log.info("extraction fully cached (%d threads)", len(threads))
            return ExtractionOutput(
                per_thread=cached,
                trace=StageTrace(
                    stage="extract",
                    model=f"{self._inner.name} (all {len(threads)} threads cached)",
                    effort="cached",
                    calls=0,
                ),
            )

        fresh = await self._inner.extract_all(misses, identity, now)

        for thread in misses:
            extraction = fresh.per_thread.get(thread.thread_key)
            # Never cache a failure: a transient error would otherwise be frozen
            # in as though the thread genuinely contained nothing.
            if extraction is None or (not extraction.commitments and _looks_like_failure(extraction)):
                continue
            path = self._dir / f"{self._key(thread, identity, now)}.json"
            path.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")

        merged = {**cached, **fresh.per_thread}
        trace = fresh.trace.model_copy(update={"cached_tokens": fresh.trace.cached_tokens})
        note = f" ({len(cached)} of {len(threads)} threads from cache)" if cached else ""
        return ExtractionOutput(
            per_thread=merged,
            trace=trace.model_copy(update={"model": f"{trace.model}{note}"}),
            warnings=fresh.warnings,
        )

    async def prioritize(
        self,
        commitments: list[Commitment],
        identity: Identity,
        now: datetime,
    ) -> PrioritizationOutput:
        # Deliberately not cached — this is the prompt you iterate on.
        return await self._inner.prioritize(commitments, identity, now)


def _looks_like_failure(extraction: ThreadExtraction) -> bool:
    reason = (extraction.dismissal_reason or "").lower()
    return "failed" in reason or "no structured output" in reason


def build_claude_engine(settings: Settings) -> CommitmentEngine:
    """Factory used by the DI layer: the real engine behind the cache."""
    from app.adapters.claude_engine import PROMPT_DIR, ClaudeCommitmentEngine

    # Prompt text is part of the cache key: editing extract.md must invalidate
    # cached results rather than silently serving output from old instructions.
    fingerprint = hashlib.sha256(
        (PROMPT_DIR / "extract.md").read_bytes()
        + settings.extract_model.encode()
        + settings.extract_effort.encode()
    ).hexdigest()[:16]

    return CachedCommitmentEngine(
        inner=ClaudeCommitmentEngine(settings),
        cache_dir=Path(settings.llm_cache_dir),
        prompt_fingerprint=fingerprint,
    )
