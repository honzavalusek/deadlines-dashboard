# Deadlines Dashboard

An AI deadline radar over Slack and email. It reads a person's conversations,
works out what they are **actually on the hook for** and by when, and renders a
prioritised board.

Slack and email ingestion are faked with seed fixtures. The reasoning is real.

## Why this exists

When I saw the brief for **ONEPOST – hlídací agent termínů** (a deadline-watching
agent), I recognized a project I'd already built at my job — so I rebuilt it from
scratch as a standalone piece.

The original was Nuxt.js, authenticated through the company SSO (Entra ID), and
used Glean as the LLM layer — a user-token-based integration acting on the
user's behalf, which already had access to that user's Slack messages, email
and documents. This version replaces that whole stack: FastAPI instead of Nuxt,
local email/password auth instead of Entra ID SSO, a direct Anthropic Claude
integration instead of Glean, and seed fixtures standing in for the real
ingestion Glean got for free.

## Tech stack

- Python 3.13, FastAPI + Uvicorn
- SQLAlchemy (async) + SQLite (`aiosqlite`)
- Server-rendered Jinja2 templates, no JS framework or frontend build
- Session auth: Starlette `SessionMiddleware` + `itsdangerous`, `argon2-cffi` password hashing
- Anthropic Python SDK — a two-stage Claude pipeline (Opus extracts, Sonnet prioritizes), see below

## Running it (demo)

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
```

Set `ANTHROPIC_API_KEY` in `.env` — required, there is no offline mode. *Reading*
a dashboard that already has a stored run doesn't need it; only pressing
**Re-run analysis** does.

`.env.example` ships with working demo defaults already, but two are worth
knowing about:

- `NOW_OVERRIDE=2026-09-02T09:00:00+02:00` pins "today" so the fixtures'
  relative Czech dates ("do pátku") resolve consistently. Without it the demo's
  dates rot as real time passes.
- `COOKIE_SECURE=false` must stay `false` for local plain HTTP — setting it
  `true` makes login silently redirect back to `/login`.

```bash
.venv/bin/python scripts/seed.py
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1
```

Open <http://127.0.0.1:8000>. Demo accounts (seeded by `scripts/seed.py`):

- `jan@example.com` / `deadlines-demo`
- `petra@example.com` / `deadlines-demo`

Each user sees only their own conversations — sign in as the other to see the
board change.

## Development

```bash
.venv/bin/python -m pytest       # 35 tests, no network, no cost
.venv/bin/ruff check .
.venv/bin/mypy
```

All three run in CI on every push, with no API key configured.

## How the models were chosen

Extraction runs on `claude-opus-5` (high effort), prioritization on
`claude-sonnet-5` (high effort) — configurable via `EXTRACT_MODEL` /
`PRIORITIZE_MODEL` in `.env`. This wasn't the original design: both stages
started on Sonnet. An eval harness (`scripts/eval_models.py`), scoring each
configuration against a known-answer fixture, showed Sonnet extraction
silently missing two behaviours outright (0/3) — which is what moved
extraction to Opus. Full rationale and measured numbers:
[docs/MODEL_CHOICE.md](docs/MODEL_CHOICE.md).

## Known limitations

Scoped deliberately — a PoC, not a product.

- **Completion re-linking** is fragile: if a re-run cites a different message
  as evidence, the completion mark can be orphaned.
- **Localhost, plain HTTP only** — no TLS, no CSRF token, `COOKIE_SECURE=false`.
- **Schema created with `create_all`**, not Alembic migrations.
- **Seeded demo passwords are printed by the seed script** — fine for a demo, not for a real deployment.
- **No independent check on the model's date arithmetic** — every resolved date rests on the model plus the citation guard.

## Where this would go next

- **Real ingestion** — one adapter behind `MessageRepository` (Slack, Graph API); nothing above the repository changes.
- **Bedrock** — `AnthropicBedrockMantle` behind the same `CommitmentEngine` port.
- **The nudge** — draft and send the `suggested_action` message to actually close the loop.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — design rationale, the pipeline, validation guards, the audience model
- [docs/MODEL_CHOICE.md](docs/MODEL_CHOICE.md) — model-choice history, the adversarial fixture, and measured eval results
