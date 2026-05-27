"""
FastAPI mock server for the AthenaX internal API.
Swap ATHENAX_API_URL in .env to point at the real backend — no code changes needed.
"""
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

app = FastAPI(title="AthenaX API (Mock)", version="0.1.0")

# In-memory store (sufficient for dev/testing)
_leads: dict[str, dict] = {}
_outreach: dict[str, dict] = {}


# ── Request / Response models ────────────────────────────────────────────────


class LeadRequest(BaseModel):
    name: str
    url: str
    source: str
    compatibility_score: int
    reason_for_partnership: str
    nounish_traits: list[str] = []
    tech_stack: list[str] = []
    submitted_at: str


class LeadResponse(BaseModel):
    lead_id: str


class OutreachRequest(BaseModel):
    lead_id: str
    channel: str
    subject: str | None = None
    body: str
    approved_at: str


class OutreachResponse(BaseModel):
    outreach_id: str


# ── Auth helper ──────────────────────────────────────────────────────────────


def _check_auth(x_api_key: str | None) -> None:
    import os
    expected = os.getenv("ATHENAX_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Endpoints ────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {"status": "ok", "server": "mock"}


@app.post("/api/v1/leads", response_model=LeadResponse, status_code=201)
def create_lead(body: LeadRequest, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    lead_id = str(uuid.uuid4())
    _leads[lead_id] = {**body.model_dump(), "lead_id": lead_id}
    print(f"[MOCK] Lead created: {lead_id} — {body.name}")
    return {"lead_id": lead_id}


@app.post("/api/v1/outreach", response_model=OutreachResponse, status_code=201)
def create_outreach(body: OutreachRequest, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    if body.lead_id not in _leads:
        raise HTTPException(status_code=404, detail=f"lead_id {body.lead_id!r} not found")
    outreach_id = str(uuid.uuid4())
    _outreach[outreach_id] = {**body.model_dump(), "outreach_id": outreach_id}
    print(f"[MOCK] Outreach created: {outreach_id} for lead {body.lead_id}")
    return {"outreach_id": outreach_id}


# ── Dev read endpoints (not in real spec, handy for inspection) ───────────────


@app.get("/api/v1/leads")
def list_leads():
    return list(_leads.values())


@app.get("/api/v1/outreach")
def list_outreach():
    return list(_outreach.values())


# ── Entry point ───────────────────────────────────────────────────────────────


def run():
    import uvicorn
    uvicorn.run("mock_server.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
