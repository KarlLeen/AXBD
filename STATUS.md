# AthenaX Partnership Agent — Implementation Status

**Project:** AI-Driven Strategic Partnership & Listing Agent (Nouns DAO × AthenaX)  
**Date:** 2026-05-27  
**Prepared by:** Engineering

---

## Executive Summary

Phase 1 of the AthenaX Partnership Agent is **fully implemented and end-to-end verified**. The system autonomously discovers, evaluates, and drafts outreach for partnership candidates using a three-agent AI pipeline. A first live run has already been completed, producing 20 raw leads, 4 scored evaluations, and 4 personalized outreach drafts stored in the local database.

---

## What Is Implemented

### 1. Infrastructure & Project Setup

- **Python 3.12 + `uv`** package manager — fast, reproducible environment
- **SQLite database** (`athenax.db`) with three tables: `leads`, `evaluations`, `outreach_drafts`
- **`.env` configuration** for all API secrets; `.env.example` committed to repo (no secrets in git)
- **`.gitignore`** properly excludes `.env`, the database file, and build artifacts

### 2. Data Sources — All APIs Integrated and Live-Tested

| API | Purpose | Status |
|---|---|---|
| **GitHub REST API** | Trending repo discovery by keyword | ✅ Live |
| **ConnectSafely.ai** | LinkedIn people, company & post search | ✅ Live |
| **Twitter / X API v2** | Hashtag monitoring, builder tweets | ✅ Live |
| **Serper API** | Google Search enrichment (YC, Product Hunt) | ✅ Live |
| **OpenRouter (DeepSeek V4 Pro)** | LLM backbone for all three agents | ✅ Live |

Each tool was individually smoke-tested against real APIs before being wired into the pipeline.

### 3. Three-Agent AI Pipeline (Scout → Evaluator → Writer)

**Agent A — Scout**  
Queries all four data sources in sequence and consolidates raw leads into a unified dataset. On the first live run it returned **20 leads** spanning GitHub, LinkedIn, Twitter, and the web.

**Agent B — Evaluator**  
Scores each lead 0–100 against two rubrics:
- *Nouns DAO fit:* CC0 culture, public goods orientation, on-chain governance, community ethos
- *AthenaX listing fit:* traction, team credibility, market timing

Discards leads below 50. Outputs the **top 5** with full rationale and trait tags.

**Agent C — Writer**  
Drafts one hyper-personalized outreach message per top lead. References specific recent activity (a GitHub commit, a tweet, a LinkedIn post). Chooses the best channel (Twitter DM or email) per lead. Produces a subject line for emails and respects the 280-character limit for DMs.

### 4. Human-in-the-Loop Review CLI

Running `athenax review` opens an interactive terminal loop that presents each draft:

```
─────────────────────────────────────────
Draft 1/4 — Prop House (by Nouns DAO)  (Twitter DM)
Score: 100/100 | "Nouns-funded, CC0-native, on-chain governance tooling"
─────────────────────────────────────────
[message preview]
─────────────────────────────────────────
[a] Approve & push  [e] Edit  [s] Skip
>
```

- **Approve** — pushes the lead and draft to the AthenaX API, stores the remote IDs locally, marks the draft `approved`. Idempotent: if the same lead is approved again later, it is not pushed twice.
- **Edit** — opens the message body in the system editor (`$EDITOR`), then re-displays the updated draft before asking again.
- **Skip** — leaves the draft `pending` for a future review session.

### 5. AthenaX API Integration

- **`AthenaXClient`** wraps `POST /api/v1/leads` and `POST /api/v1/outreach`. Switching from mock to production requires only changing `ATHENAX_API_URL` in `.env` — zero code changes.
- **Mock server** (`mock_server/app.py`) is a local FastAPI app that fully implements both endpoints. It includes API-key authentication and dev-only `GET` endpoints for inspecting stored data.

### 6. Scheduling

Running `athenax schedule` starts a blocking weekly cron. Default: every Monday at 09:00 UTC. Configurable via `--day` and `--time` flags.

```bash
uv run athenax schedule --day monday --time 09:00
```

---

## What Is Not Yet Implemented

### 1. Actual Message Sending

The system **never sends any message automatically.** The Writer agent only produces drafts. All outreach is gated behind the human review step. There is no SMTP, SendGrid, or Twitter DM send integration — this is intentional per the spec.

Implementing actual send capability would require:
- Email: an SMTP / transactional email provider (e.g. SendGrid, Resend)
- Twitter DM: `POST /2/dm_conversations/with/:participant_id/messages` (requires Elevated access tier)

### 2. Phase 2 — Telegram Admin Bot

Per the original spec, a Telegram bot that reads from the AthenaX API and supports bot-side approval flows is scoped to **Phase 2**. The database schema and API layer are already designed to support it (`status` field, `remote_lead_id` foreign key), so no schema changes will be needed when Phase 2 begins.

### 3. Lead Name Disambiguation

On the first live run, one lead ("Hey / Lens Protocol Frontend") was scored by the Evaluator but its draft was not saved because the Evaluator used a slightly different name than the Scout. The current fuzzy matching uses substring comparison. A more robust approach (e.g. embedding-based similarity, or passing lead IDs through the pipeline) would eliminate this edge case. It affected 1 out of 5 leads on the first run.

### 4. Production Hardening

The following are not implemented and would be needed before running in production:

| Item | Notes |
|---|---|
| Rate-limit retry logic | Twitter and GitHub have per-hour caps; need exponential backoff |
| Duplicate lead detection | Re-running the pipeline weekly may surface the same repos/profiles |
| Persistent cron (daemon) | `athenax schedule` is a blocking process; a systemd unit or cron job is needed for unattended weekly runs |
| Logging to file | Currently logs only to stdout |

---

## First Live Run Results

Run completed on 2026-05-27 using **DeepSeek V4 Pro** via OpenRouter.

| Metric | Result |
|---|---|
| Raw leads discovered | 20 |
| Sources covered | GitHub, LinkedIn (people + companies + posts), Twitter/X, Web |
| Leads scored ≥ 50 | 4 (1 lost to name mismatch) |
| Outreach drafts generated | 4 |
| Drafts approved & pushed to mock API | 1 (manual review in progress) |

**Top-scored leads from first run:**

| Lead | Score | Key Traits |
|---|---|---|
| Prop House (Nouns DAO) | 100/100 | Nouns-funded, CC0, on-chain governance tooling |
| ethereum/go-ethereum | 95/100 | Public goods, open source, builder ethos |
| unionlabs/union | 80/100 | zkIBC, trust-minimized bridging, open source |
| pk910/PoWFaucet | 78/100 | Sybil resistance, Gitcoin Passport integration |

---

## How to Run

```bash
# 1. Install dependencies
uv sync

# 2. Copy and fill in secrets
cp .env.example .env

# 3. Run the pipeline once
uv run athenax run

# 4. Review and approve drafts
uv run athenax review

# 5. Start the mock API server (separate terminal, for testing)
uv run athenax-mock
```
