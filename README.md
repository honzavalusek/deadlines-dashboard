# deadlines-dashboard

AI deadline radar over Slack messages and email conversations.

Reads a user's conversations, works out what they have actually committed to and by when,
and renders a prioritized dashboard. Slack/email ingestion is faked with seed fixtures;
the reasoning is real.

> Work in progress — see `docs/` and the commit history. Full write-up lands in the final commit.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env          # works as-is with ENGINE=stub
.venv/bin/python scripts/seed.py
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1
```

Open http://127.0.0.1:8000 — runs fully offline with `ENGINE=stub`.
Set `ENGINE=claude` and `ANTHROPIC_API_KEY` for the real pipeline.
