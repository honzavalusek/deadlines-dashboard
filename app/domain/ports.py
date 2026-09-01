"""The one port in this design.

``CommitmentEngine`` is a Protocol so tests can inject
``tests.fakes.StubCommitmentEngine`` with no API key and no network. There is
no offline mode for the running app: a missing ``ANTHROPIC_API_KEY`` fails
loudly. The dashboard is still readable without a key because it renders the
last stored run.

Data loading deliberately has no port — see ``app.db.repositories``.
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
