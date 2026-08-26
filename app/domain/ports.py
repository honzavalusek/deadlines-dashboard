"""The one port in this design.

``CommitmentEngine`` is a Protocol because it has two real implementations —
``ClaudeCommitmentEngine`` and ``StubCommitmentEngine`` — plus a caching
decorator. That earns the abstraction, and it buys three concrete things:

* the app (and the whole test suite) runs with no API key and no network, so a
  demo cannot be killed by connectivity;
* tests are free and deterministic;
* "swap in Bedrock" or "swap in the real Slack API" is a one-file claim rather
  than hand-waving.

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
