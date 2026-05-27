# AthenaX Partnership Agent

> AI-driven strategic partnership discovery and outreach automation for **Nouns DAO × AthenaX**, built on [CrewAI](https://github.com/crewaiinc/crewai).

---

## Overview

A three-agent Multi-Agent System (MAS) that autonomously:

1. **Scouts** GitHub, LinkedIn, Twitter/X, and the web for Web3 / DAO partnership candidates
2. **Evaluates** each lead against Nouns DAO cultural fit and AthenaX listing criteria
3. **Drafts** hyper-personalized outreach messages — never a generic template

All results are stored in a local SQLite database. No message is ever sent without explicit human approval via a CLI review loop.

```
Scout (Agent A) → Evaluator (Agent B) → Writer (Agent C)
                                                  ↓
                                           SQLite (athenax.db)
                                                  ↓
                                        athenax review (CLI)
                                                  ↓
                                   [a]pprove → AthenaX API push
```

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Package manager | `uv` |
| Agent framework | CrewAI |
| LLM | DeepSeek V4 Pro via OpenRouter (LiteLLM) |
| Storage | SQLite (`athenax.db`) |
| Mock API server | FastAPI |

**Data sources:** GitHub REST API · ConnectSafely.ai (LinkedIn) · Twitter/X API v2 · Serper API

---

## Project Structure

```
athenax-partnership-agent/
├── .env.example              # Secret template — copy to .env and fill in
├── pyproject.toml            # uv-managed dependencies
├── STATUS.md                 # Implementation status report
├── athenax/
│   ├── main.py               # CLI entrypoint (run / review / schedule)
│   ├── crew.py               # CrewAI Crew wiring
│   ├── agents/
│   │   ├── scout.py          # Agent A — Multi-Platform Scout
│   │   ├── evaluator.py      # Agent B — Strategic Evaluator
│   │   └── writer.py         # Agent C — Outreach Architect
│   ├── tools/
│   │   ├── github_tool.py    # GitHub repo search
│   │   ├── linkedin_tool.py  # ConnectSafely.ai people / company / post search
│   │   ├── twitter_tool.py   # Twitter/X hashtag monitoring
│   │   └── serper_tool.py    # Google Search via Serper
│   ├── db/
│   │   ├── database.py       # SQLite init + migration
│   │   └── models.py         # Lead / Evaluation / OutreachDraft dataclasses
│   ├── api/
│   │   └── athenax_client.py # AthenaX API wrapper (mock-swappable)
│   └── cli/
│       └── review.py         # Human-in-the-loop approval loop
└── mock_server/
    └── app.py                # FastAPI mock for AthenaX internal API
```

---

## Quickstart

### 1. Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`

### 2. Install

```bash
git clone https://github.com/KarlLeen/AXBD.git
cd AXBD
uv sync
```

### 3. Configure secrets

```bash
cp .env.example .env
# Edit .env and fill in all API keys
```

Required keys:

| Variable | Where to get it |
|---|---|
| `GITHUB_TOKEN` | [github.com/settings/tokens](https://github.com/settings/tokens) |
| `CONNECTSAFELY_API_KEY` | [connectsafely.ai](https://connectsafely.ai) dashboard |
| `TWITTER_BEARER_TOKEN` | [developer.twitter.com](https://developer.twitter.com) |
| `TWITTER_API_KEY` | Same Twitter developer project |
| `TWITTER_API_SECRET` | Same Twitter developer project |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `SERPER_API_KEY` | [serper.dev](https://serper.dev) |
| `ATHENAX_API_URL` | Set to `http://localhost:8000` for local dev |

### 4. Run

```bash
# Run the full pipeline once (Scout → Evaluator → Writer → SQLite)
uv run athenax run

# Review and approve outreach drafts
uv run athenax review

# Run the mock AthenaX API server (separate terminal)
uv run athenax-mock

# Schedule automatic weekly runs (blocks — use a process manager for production)
uv run athenax schedule --day monday --time 09:00
```

---

## CLI Review Loop

After `athenax run` completes, use `athenax review` to inspect each draft:

```
─────────────────────────────────────────────
Draft 1/4 — Prop House (by Nouns DAO)  (Twitter DM)
Score: 100/100 | "Nouns-funded, CC0-native, on-chain governance tooling"
─────────────────────────────────────────────
Saw your tweet about the retro funding round with Gitcoin – epic extension
of the cc0 spirit. As builders of AthenaX (a Nouns community curation hub),
we'd love to feature Prop House front and center. Can I send you a quick blurb?
─────────────────────────────────────────────
[a] Approve & push  [e] Edit  [s] Skip
>
```

- **`a` — Approve & push**: pushes the lead and draft to `POST /api/v1/leads` and `POST /api/v1/outreach`, marks the record `approved` in SQLite. Idempotent — re-approving the same lead does not create duplicates.
- **`e` — Edit**: opens the message body in `$EDITOR`, then re-displays before asking again.
- **`s` — Skip**: leaves the draft `pending` for a future session.

---

## Database Schema

Three tables in `athenax.db`:

| Table | Purpose |
|---|---|
| `leads` | Raw output from Agent A — one row per discovered project |
| `evaluations` | Scored output from Agent B — one row per evaluated lead |
| `outreach_drafts` | Draft messages from Agent C — `status`: `pending` → `approved` / `rejected` |

The schema is initialized automatically on first run. Migrations (e.g. adding `remote_lead_id`) are applied non-destructively on every startup.

---

## AthenaX API

The mock server (`mock_server/app.py`) implements the same interface as the real AthenaX backend.
To switch to production, change only `ATHENAX_API_URL` in `.env` — no code changes needed.

| Endpoint | Description |
|---|---|
| `POST /api/v1/leads` | Push a high-scoring lead for admin review |
| `POST /api/v1/outreach` | Push an approved outreach draft |
| `GET /health` | Health check |

---

## Roadmap

| Phase | Status |
|---|---|
| Phase 1 — Core pipeline (Scout + Evaluator + Writer + CLI review + mock API) | ✅ Complete |
| Phase 2 — Telegram Admin Bot (reads via AthenaX API, bot-side approval flow) | Planned |
| Production hardening (rate-limit retries, duplicate detection, file logging) | Planned |

---

## Safety & Compliance

- **No automatic sending** — every outreach message requires explicit human approval
- **ConnectSafely.ai** protects the LinkedIn account from scraping flags
- **Twitter/X** integration uses official OAuth tokens and read-only search endpoints only
- **GitHub** uses authenticated REST API (5,000 req/hr)
- Secrets are loaded from `.env` and never committed to the repository
