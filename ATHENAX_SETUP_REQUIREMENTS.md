# AthenaX Partnership Agent — Setup Requirements

**To:** AthenaX Engineering / Operations  
**Re:** What AthenaX needs to prepare to run the Partnership Agent

---

## Overview

The AthenaX Partnership Agent is an AI system that runs weekly to automatically discover, score, and draft outreach for partnership and listing candidates. It currently runs on a local development machine. This document lists everything AthenaX needs to provide or set up for the agent to run in production.

---

## 1. API Keys & Accounts to Procure

The agent pulls data from five external platforms. AthenaX needs accounts and API keys for each.

| Service | Purpose|
|---|---|---|---|
| **GitHub** | Scan trending repos for Web3/DAO projects | 
| **ConnectSafely.ai** | LinkedIn people, company & post search (compliant) |
| **Twitter / X API** | Monitor Web3 hashtags and builder activity | 
| **OpenRouter** | LLM backbone (currently using DeepSeek V4 Pro) |
| **Serper** | Google Search for YC batches, VC announcements, conference winners |
| **CoinGecko** | Verify crypto project listing status | 

Once accounts are created, the credentials go into a `.env` file on whatever server runs the agent.

---

## 2. Internal API to Build

The agent pushes its results (leads and outreach drafts) into AthenaX's backend for admin review. AthenaX engineering needs to build five API endpoints.

| Endpoint | What it does |
|---|---|
| `POST /api/v1/leads` | Receive a scored lead from the agent |
| `POST /api/v1/outreach` | Receive a pending outreach draft |
| `GET /api/v1/outreach?status=pending` | List drafts awaiting review |
| `PATCH /api/v1/outreach/{id}` | Approve or reject a draft |
| `GET /health` | Health check |

> **Note:** A fully working mock server that implements all five endpoints is already in the codebase (`mock_server/app.py`). AthenaX engineering can use it as a reference — it includes interactive Swagger docs at `/docs`.

Once the real API is live, AthenaX provides two values:
- `ATHENAX_API_URL` — the production base URL
- `ATHENAX_API_KEY` — an auth key for the agent

That's the only change needed on the agent side to switch from mock to production.

---

## 3. A Server to Host the Agent

The agent currently runs on a local laptop. For production use, AthenaX needs a server to host it so it can run automatically every week without anyone's laptop being open.

### Minimum server spec

| Requirement | Value |
|---|---|
| OS | Ubuntu 22.04+ (or any Linux) |
| CPU | 1 vCPU |
| RAM | 2 GB |
| Storage | 10 GB |
| Estimated cost | ~$6–12/month (DigitalOcean, Hetzner, AWS t3.small, etc.) |

### What gets installed on the server

```bash
# 1. Python 3.12 + uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone the agent repo
git clone https://github.com/KarlLeen/AXBD.git
cd AXBD
uv sync

# 3. Fill in all API keys
cp .env.example .env
nano .env

# 4. Schedule weekly run (every Monday 09:00 UTC)
crontab -e
# Add: 0 9 * * 1 cd /path/to/AXBD && uv run athenax run >> /var/log/athenax.log 2>&1
```

### Alternative: keep it on a team member's machine

If AthenaX doesn't want to set up a server right away, the agent can continue running on a dedicated team member's laptop/desktop. The weekly run is triggered manually with one command:

```bash
uv run athenax run
```

---

## 4. Telegram Bot Setup (Optional)

The agent includes a Telegram bot that notifies an admin when new outreach drafts are ready and lets them approve or reject with a button tap — no CLI access needed.

To enable it, AthenaX needs to:

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram → get `TELEGRAM_BOT_TOKEN`
2. Get the admin's Telegram user ID via [@userinfobot](https://t.me/userinfobot) → `TELEGRAM_ADMIN_CHAT_ID`
3. Add both to `.env`
4. Start the bot on the server: `uv run athenax bot`

---

## 5. Summary Checklist

### AthenaX must provide:
- [ ] `ATHENAX_API_URL` + `ATHENAX_API_KEY` (once their internal API is built)

### AthenaX engineering must build:
- [ ] 5 internal API endpoints (see Section 2 above)

### AthenaX ops must set up:
- [ ] A Linux server (or designate a team machine) to run the agent
- [ ] Weekly cron job or manual run schedule
- [ ] (Optional) Telegram bot for mobile review

---

## 6. What's Already Done

Everything on the agent side is built and ready:

| Component | Status |
|---|---|
| Three-agent AI pipeline (Scout → Evaluator → Writer) | ✅ Complete |
| All external API integrations (GitHub, LinkedIn, Twitter, Serper, CoinGecko) | ✅ Live-tested |
| AthenaX Selection Criteria scoring (7 sectors, YC/VC signals, velocity) | ✅ Encoded |
| Human review — CLI loop (approve / edit / reject) | ✅ Complete |
| Human review — Telegram bot (inline buttons) | ✅ Complete |
| AthenaX API client (switches mock → real with one env var change) | ✅ Complete |
| Mock server for development & testing | ✅ Complete |
| 103 automated tests | ✅ Passing |

The agent just needs the keys, the API, and a place to run.

---

*Agent codebase: https://github.com/KarlLeen/AXBD*
