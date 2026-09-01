#!/usr/bin/env python
"""Score a real engine against the fixture's known-correct answers.

The point: the model and effort choice should be *evidenced*, not asserted.
``tests/fakes.py`` already encodes what a correct analysis of each adversarial
thread looks like; the checks below assert the same expectations against a
real Claude run instead of eyeballing it.

    python scripts/eval_models.py                          # current .env config
    python scripts/eval_models.py --sweep                  # a few (model, effort) pairs
    python scripts/eval_models.py --extract-model claude-opus-5 --extract-effort high

Costs real money — one extraction call per thread per configuration, plus one
prioritisation call. Jan owns 11 of the fixture's 13 threads, so a single
configuration is cents.

``--repeat N`` runs each configuration N times. Worth doing before drawing any
conclusion from a score: model output varies between runs, so a single 19/20 vs
20/20 cannot distinguish a real difference between two configurations from
noise. Pass rates across several runs can.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.db import session as dbs  # noqa: E402
from app.db.repositories import MessageRepository, UserRepository  # noqa: E402
from app.domain.models import Commitment  # noqa: E402
from app.services.radar import run_analysis  # noqa: E402

TARGET_EMAIL = "jan@example.com"


@dataclass
class Check:
    name: str
    detail: str
    passed: bool


def _find(commitments: list[Commitment], thread_key: str) -> list[Commitment]:
    return [c for c in commitments if c.thread_key == thread_key]


def evaluate(commitments: list[Commitment], board_order: list[str]) -> list[Check]:
    """The behaviours each adversarial thread exists to test."""
    checks: list[Check] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append(Check(name, detail, passed))

    # --- supersession: three messages, ONE commitment that moved -----------
    deck = _find(commitments, "slack:product:roadmap-deck")
    add("supersede/one-commitment", len(deck) == 1, f"got {len(deck)} commitments, want 1")
    if deck:
        c = deck[0]
        add("supersede/status-moved", c.status == "moved", f"status={c.status}")
        add("supersede/current-date", c.current_due == date(2026, 9, 7), f"current_due={c.current_due}")
        add("supersede/original-date", c.original_due == date(2026, 9, 4), f"original_due={c.original_due}")
        add("supersede/chain-recorded", len(c.supersede_chain) >= 1, f"chain={len(c.supersede_chain)}")

    # --- cancellation: recognised, not left as an open task ----------------
    quest = _find(commitments, "email:acme-security-questionnaire")
    add("cancel/detected", bool(quest) and quest[0].status == "cancelled",
        f"status={quest[0].status if quest else 'missing'}")

    # --- noise: must produce nothing --------------------------------------
    noise = _find(commitments, "slack:general:chitchat")
    add("noise/zero-commitments", len(noise) == 0, f"invented {len(noise)} task(s)")

    # --- audience: the three-way judgment ---------------------------------
    team = _find(commitments, "slack:pricing:launch-copy")
    add("audience/my_team", bool(team) and team[0].audience == "my_team",
        f"audience={team[0].audience if team else 'missing'}")
    dpa = _find(commitments, "email:acme-dpa")
    add("audience/someone_else", bool(dpa) and dpa[0].audience == "someone_else",
        f"audience={dpa[0].audience if dpa else 'missing'}")

    # --- ambiguity: flag, don't guess -------------------------------------
    board = _find(commitments, "email:board-pack")
    add("ambiguous/low-confidence", bool(board) and board[0].date_confidence == "low",
        f"confidence={board[0].date_confidence if board else 'missing'}")

    # --- done-detection and overdue in one thread -------------------------
    fin = _find(commitments, "slack:dm-lucie:finance")
    add("finance/two-commitments", len(fin) == 2, f"got {len(fin)}, want 2")
    add("finance/one-done", sum(1 for c in fin if c.status == "done") == 1,
        f"{sum(1 for c in fin if c.status == 'done')} marked done")
    overdue = [c for c in fin if c.current_due == date(2026, 8, 21)]
    add("finance/overdue-resolved", len(overdue) == 1, "'minulý pátek' -> 2026-08-21")

    # --- no invented deadline --------------------------------------------
    press = _find(commitments, "slack:eng:pricing-copy")
    add("nodate/left-null", bool(press) and press[0].current_due is None,
        f"current_due={press[0].current_due if press else 'missing'}")

    # --- guards: quotes verbatim, and an unresolved date keeps both candidates
    unverified = [c.task for c in commitments if not c.quote_verified]
    add("guard/quotes-verbatim", not unverified, f"unverified: {unverified}")
    # An ambiguous deadline must not silently collapse to one date: the date the
    # model didn't pick is still live, and the board has to show it.
    add("guard/both-dates-shown",
        bool(board) and bool(board[0].alternative_dues),
        f"alternative_dues={board[0].alternative_dues if board else 'missing'}")

    # --- output language --------------------------------------------------
    czech_markers = ("ě", "š", "č", "ř", "ž", "ů", "ď", "ň")
    czech_tasks = [c.task for c in commitments if any(m in c.task.lower() for m in czech_markers)]
    add("language/tasks-english", not czech_tasks, f"non-English task text: {czech_tasks}")
    citations_kept = [c for c in commitments if c.due_raw_text]
    add("language/citations-verbatim", bool(citations_kept),
        f"{len(citations_kept)} commitments kept a verbatim due phrase")

    # --- the rank inversions: the reason stage 2 exists -------------------
    def rank(fragment: str) -> int | None:
        for i, task in enumerate(board_order):
            if fragment.lower() in task.lower():
                return i
        return None

    uohs, alt = rank("ÚOHS"), rank("alt text")
    pricing = rank("pricing page")
    add("inversion/statutory-over-trivial",
        uohs is not None and alt is not None and uohs < alt,
        f"ÚOHS at #{uohs}, alt text at #{alt} (statutory must rank higher)")
    add("inversion/launch-blocker-over-trivial",
        pricing is not None and alt is not None and pricing < alt,
        f"pricing copy at #{pricing}, alt text at #{alt}")

    return checks


async def run_one(settings: Settings) -> tuple[list[Check], str]:
    from app.adapters.claude_engine import ClaudeCommitmentEngine

    engine = ClaudeCommitmentEngine(settings)

    dbs.init_engine(settings.database_url)
    async with dbs.get_sessionmaker()() as db:
        users = UserRepository(db)
        user = await users.get_by_email(TARGET_EMAIL)
        if user is None:
            raise SystemExit(f"{TARGET_EMAIL} not found — run scripts/seed.py first")
        threads = await MessageRepository(db).threads_for_user(user.id)
        identity = users.identity_of(user)

    outcome = await run_analysis(
        engine=engine,
        threads=threads,
        identity=identity,
        now=settings.now(),
    )
    await dbs.dispose_engine()

    commitments = [item.commitment for item in outcome.scored]
    board_order = [i.commitment.task for i in outcome.scored if i.commitment.is_actionable]
    trace = " | ".join(
        f"{t.stage}: {t.model} @ {t.effort}, {t.input_tokens}->{t.output_tokens} tok, {t.latency_ms}ms"
        for t in outcome.traces
    )
    return evaluate(commitments, board_order), trace


def report(label: str, checks: list[Check], trace: str) -> bool:
    passed = sum(c.passed for c in checks)
    print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
    for c in checks:
        mark = "PASS" if c.passed else "FAIL"
        print(f"  [{mark}] {c.name:38} {'' if c.passed else c.detail}")
    print(f"\n  {passed}/{len(checks)} checks passed")
    print(f"  {trace}")
    return passed == len(checks)


def report_runs(label: str, runs: list[list[Check]], traces: list[str]) -> bool:
    """Per-check pass rates across N runs of one configuration.

    The point of repeating: model output varies between runs, so one 19/20 next
    to one 20/20 says nothing about which configuration is better. A check that
    passes 3/3 is evidence; a check that passes 2/3 is *flaky*, which is a
    finding in its own right and worth more than a single green tick.

    Checks are conditional (four of them only run if the supersession thread
    yielded a commitment at all), so a check can be absent from a run. The
    denominator stays the total number of runs — an unreached check has not
    passed — and any shortfall is called out separately rather than hidden.
    """
    total = len(runs)
    order: list[str] = []
    passed: dict[str, int] = {}
    present: dict[str, int] = {}
    details: dict[str, str] = {}

    for checks in runs:
        for c in checks:
            if c.name not in present:
                order.append(c.name)
                passed[c.name] = present[c.name] = 0
            present[c.name] += 1
            if c.passed:
                passed[c.name] += 1
            else:
                details.setdefault(c.name, c.detail)

    print(f"\n{'=' * 78}\n{label}  —  {total} runs\n{'=' * 78}")
    flaky = 0
    for name in order:
        hits = passed[name]
        if hits == total:
            mark = "PASS "
        elif hits == 0:
            mark = "FAIL "
        else:
            mark = "FLAKY"
            flaky += 1
        note = "" if hits == total else details.get(name, "")
        if present[name] < total:
            note = f"(not reached in {total - present[name]} run(s)) {note}".strip()
        print(f"  [{mark}] {name:38} {hits}/{total}  {note}")

    stable = sum(1 for name in order if passed[name] == total)
    print(f"\n  {stable}/{len(order)} checks passed in every run"
          f"{f', {flaky} flaky' if flaky else ''}")
    for i, trace in enumerate(traces, start=1):
        print(f"  run {i}: {trace}")
    return stable == len(order)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-model")
    parser.add_argument("--extract-effort")
    parser.add_argument("--prioritize-model")
    parser.add_argument("--prioritize-effort")
    parser.add_argument("--sweep", action="store_true",
                        help="compare a few (model, effort) configurations")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="run each configuration N times and report per-check "
                             "pass rates instead of a single score")
    args = parser.parse_args()
    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")

    base = Settings()
    if not base.anthropic_api_key or base.anthropic_api_key.startswith("sk-ant-your-key"):
        raise SystemExit("ANTHROPIC_API_KEY is not set in .env — the eval calls the real API.")

    print(f"Clock pinned to {base.now():%A %d %B %Y}.")

    if args.sweep:
        configs = [
            ("sonnet-5 @ medium/high  (shipped default)",
             dict(extract_model="claude-sonnet-5", extract_effort="medium",
                  prioritize_model="claude-sonnet-5", prioritize_effort="high")),
            ("sonnet-5 @ low/medium   (cheaper)",
             dict(extract_model="claude-sonnet-5", extract_effort="low",
                  prioritize_model="claude-sonnet-5", prioritize_effort="medium")),
            ("opus-5 extract @ high   (escalated stage 1)",
             dict(extract_model="claude-opus-5", extract_effort="high",
                  prioritize_model="claude-sonnet-5", prioritize_effort="high")),
        ]
    else:
        # "sweep" and "repeat" drive the harness, not the engine — they are not
        # Settings fields and must never reach model_copy.
        overrides = {k: v for k, v in vars(args).items()
                     if v and k not in ("sweep", "repeat")}
        configs = [("current .env configuration", overrides)]

    results = []
    for label, overrides in configs:
        settings = base.model_copy(update=overrides)
        runs: list[list[Check]] = []
        traces: list[str] = []
        for i in range(args.repeat):
            if args.repeat > 1:
                print(f"\n  … {label}: run {i + 1}/{args.repeat}", flush=True)
            checks, trace = await run_one(settings)
            runs.append(checks)
            traces.append(trace)

        if args.repeat == 1:
            ok = report(label, runs[0], traces[0])
        else:
            ok = report_runs(label, runs, traces)
        results.append((label, ok))

    print(f"\n{'=' * 78}\nSUMMARY\n{'=' * 78}")
    for label, ok in results:
        print(f"  {'ALL PASS' if ok else 'FAILURES'}  {label}")


if __name__ == "__main__":
    asyncio.run(main())
