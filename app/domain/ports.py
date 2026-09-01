"""The one port in this design.

``CommitmentEngine`` is a Protocol with a single production implementation,
``ClaudeCommitmentEngine``. That is a thin justification on its own, so the
honest case for the abstraction is what it actually buys:

* **the whole test suite runs with no API key and no network**, against a fake
  engine (``tests.fakes.StubCommitmentEngine``) injected by a FastAPI
  dependency override — so tests are free, instant and deterministic without
  the production code path knowing a fake exists;
* "swap in Bedrock" or "swap in real Slack ingestion" is a one-file claim
  rather than hand-waving.

What it deliberately does *not* buy: an offline mode for the running app. There
isn't one, and a missing ``ANTHROPIC_API_KEY`` fails loudly rather than quietly
serving invented data. The dashboard is still readable without a key, but for a
different reason — it renders the last *stored* run, so drawing the board never
depends on a live call.

Data loading deliberately does *not* get a port — see ``app.db.repositories``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.domain.models import (
    Commitment,
    ExtractionOutput,
    Identity,
    PrioritizationOutput,
    Thread,
)


@runtime_checkable
class CommitmentEngine(Protocol):
    """Turns conversations into judged commitments.

    Two stages, deliberately separate:

    ``extract_all``
        Maps over *threads*. A thread is the unit because a deadline that moves
        or gets cancelled is one commitment with a history, and only the whole
        thread contains the evidence for that. Per-message extraction cannot
        represent supersession at all.

    ``prioritize``
        Reduces over the whole set in a single pass, because priority is
        comparative: a statutory filing due in a week outranks a wiki tidy-up
        due tomorrow, and no amount of scoring items in isolation produces that
        ordering.

    Neither method sorts, and neither does date arithmetic. Both are Python's
    job (``app.domain.scoring``).
    """

    name: str

    async def extract_all(
        self,
        threads: list[Thread],
        identity: Identity,
        now: datetime,
    ) -> ExtractionOutput:
        """Extract commitments from every thread. Failures degrade to warnings."""
        ...

    async def prioritize(
        self,
        commitments: list[Commitment],
        identity: Identity,
        now: datetime,
    ) -> PrioritizationOutput:
        """Judge the whole set against itself. Returns scores, never an order."""
        ...
