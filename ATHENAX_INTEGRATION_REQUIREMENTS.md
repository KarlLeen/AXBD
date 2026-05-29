# AthenaX Partnership Agent — Integration Requirements

**To:** AthenaX Engineering  
**From:** Partnership Agent Team  
**Re:** Backend API requirements for the AI Partnership Agent

---

## Context

We have built an AI-driven pipeline that automatically discovers, evaluates, and drafts outreach for partnership and listing candidates. The pipeline runs weekly and pushes its results into the AthenaX backend for admin review.

The agent also powers a **Telegram Admin Bot** that lets you approve or reject outreach drafts directly from Telegram — no CLI access needed.

We have a fully working **mock server** that implements everything described below. All you need to do is build the real endpoints to the same spec, then we change one environment variable (`ATHENAX_API_URL`) and the agent points at production. Zero code changes on our side.

---

## 1. Authentication

Every request from the agent includes an API key in the header:

```
X-API-Key: <ATHENAX_API_KEY>
```

Please provide us with:
- The **production API base URL** (`ATHENAX_API_URL`)
- An **API key** for the agent (`ATHENAX_API_KEY`)

If no API key is set, the agent skips auth validation (useful for local dev).

---

## 2. Required Endpoints

### 2.1 `POST /api/v1/leads`
Push a high-scoring lead discovered by the agent.

**Request body:**
```json
{
  "name": "unionlabs/union",
  "url": "https://github.com/unionlabs/union",
  "source": "github",
  "compatibility_score": 80,
  "reason_for_partnership": "Trust-minimized zkIBC bridging aligns with Nouns DAO cross-chain ambitions.",
  "nounish_traits": ["open source", "public goods", "decentralized architecture"],
  "tech_stack": ["Rust", "CosmWasm", "ZK"],
  "submitted_at": "2026-05-27T11:00:00Z"
}
```

**Response `201 Created`:**
```json
{ "lead_id": "550e8400-e29b-41d4-a716-446655440000" }
```

`lead_id` must be a UUID. We store it locally and reference it in all subsequent outreach calls.

---

### 2.2 `POST /api/v1/outreach`
Push an outreach draft. Called immediately after the pipeline finishes (status = `pending`), and again if approved via CLI (status = `approved`).

**Request body:**
```json
{
  "lead_id": "550e8400-e29b-41d4-a716-446655440000",
  "channel": "twitter_dm",
  "subject": null,
  "body": "That latest zkIBC testnet stat is wild. Union's bridging is a perfect complement to Nouns' cross-chain ambitions. We're building AthenaX — want to include Union as a crown jewel. Cool to DM?",
  "status": "pending",
  "approved_at": null,
  "lead_name": "unionlabs/union",
  "compatibility_score": 80
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `lead_id` | UUID string | ✅ | Must match a previously pushed lead |
| `channel` | `"twitter_dm"` or `"email"` | ✅ | |
| `subject` | string or null | — | Required for email, null for DMs |
| `body` | string | ✅ | The outreach message text |
| `status` | `"pending"` / `"approved"` / `"rejected"` | ✅ | Default `"pending"` |
| `approved_at` | ISO 8601 string or null | — | Set when status is `"approved"` |
| `lead_name` | string | — | Display name for the Telegram bot |
| `compatibility_score` | int 0–100 | — | For display in Telegram bot |

**Response `201 Created`:**
```json
{ "outreach_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8" }
```

---

### 2.3 `GET /api/v1/outreach`
Return outreach drafts, optionally filtered by status. Used by the Telegram bot to poll for items needing review.

**Query parameters:**

| Param | Type | Example |
|---|---|---|
| `status` | string (optional) | `?status=pending` |

**Response `200 OK`:**
```json
[
  {
    "outreach_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    "lead_id": "550e8400-e29b-41d4-a716-446655440000",
    "lead_name": "unionlabs/union",
    "channel": "twitter_dm",
    "subject": null,
    "body": "That latest zkIBC testnet stat is wild...",
    "status": "pending",
    "compatibility_score": 80,
    "approved_at": null
  }
]
```

---

### 2.4 `PATCH /api/v1/outreach/{outreach_id}`
Update the status of a draft. Called by the Telegram bot when the admin taps ✅ Approve or ❌ Reject.

**Request body:**
```json
{ "status": "approved" }
```

`status` must be either `"approved"` or `"rejected"`.

**Response `200 OK`:** Return the updated outreach object (same shape as GET response).

When status becomes `"approved"`, please set `approved_at` to the current UTC timestamp on your end.

---

### 2.5 `GET /api/v1/leads` *(optional but useful)*
List all pushed leads. Not strictly required for the agent to function, but useful for admin dashboards and debugging.

**Response `200 OK`:** Array of lead objects.

---

### 2.6 `GET /health`
Health check endpoint. The agent checks this on startup.

**Response `200 OK`:**
```json
{ "status": "ok" }
```

---

## 3. Environment Variables to Share With Us

Once your API is live, please send us:

| Variable | Description | Example |
|---|---|---|
| `ATHENAX_API_URL` | Production base URL | `https://api.athenax.xyz` |
| `ATHENAX_API_KEY` | Auth key for the agent | `axk_live_abc123...` |

That's it. We update our `.env` file and the agent points at production immediately.

---

## 4. Telegram Bot Flow (for your reference)

The Telegram admin bot runs alongside the agent and does the following:

```
Every 60 seconds:
  GET /api/v1/outreach?status=pending
    → finds new drafts
    → sends Telegram message to admin with [✅ Approve] [❌ Reject] buttons

Admin taps a button:
  PATCH /api/v1/outreach/{outreach_id}  { "status": "approved" }
    → bot confirms in Telegram
    → message updated to show ✅ Approved
```

The bot needs `PATCH /api/v1/outreach/{id}` and `GET /api/v1/outreach?status=pending` to work. The other endpoints (`POST /leads`, `POST /outreach`) are called by the pipeline, not the bot.

---

## 5. Quick Checklist

- [ ] `POST /api/v1/leads` — accepts lead payload, returns `{ "lead_id": "uuid" }`
- [ ] `POST /api/v1/outreach` — accepts draft with `status` field, returns `{ "outreach_id": "uuid" }`
- [ ] `GET /api/v1/outreach?status=pending` — returns filtered list for Telegram bot
- [ ] `PATCH /api/v1/outreach/{id}` — updates status, sets `approved_at` on approval
- [ ] `GET /health` — returns `{ "status": "ok" }`
- [ ] `X-API-Key` header authentication on all endpoints
- [ ] Share `ATHENAX_API_URL` + `ATHENAX_API_KEY` with us

---

## 6. Reference Implementation

A fully working mock server (`mock_server/app.py`) is available in the repository at  
**https://github.com/KarlLeen/AXBD**

It implements every endpoint above using FastAPI. You can run it locally with:

```bash
uv run athenax-mock
# → http://localhost:8000
# → http://localhost:8000/docs  (interactive Swagger UI)
```

The Swagger UI at `/docs` shows the exact request/response schema for every endpoint and lets you test them live.

---

*Questions? The agent codebase is at https://github.com/KarlLeen/AXBD*
