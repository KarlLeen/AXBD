"""
FastAPI mock server for the AthenaX internal API.
Swap ATHENAX_API_URL in .env to point at the real backend — no code changes needed.
"""
import uuid
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

app = FastAPI(title="AthenaX API (Mock)", version="0.2.0")

# In-memory store
_leads: dict[str, dict] = {}
_outreach: dict[str, dict] = {}


# ── Models ───────────────────────────────────────────────────────────────────


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
    # status defaults to pending so pipeline can push drafts before review
    status: Literal["pending", "approved", "rejected"] = "pending"
    approved_at: str | None = None
    # enrichment fields so the bot can display context without extra calls
    lead_name: str | None = None
    compatibility_score: int | None = None


class OutreachResponse(BaseModel):
    outreach_id: str


class OutreachPatch(BaseModel):
    status: Literal["approved", "rejected"]


# ── Auth ─────────────────────────────────────────────────────────────────────


def _check_auth(x_api_key: str | None) -> None:
    expected = os.getenv("ATHENAX_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Leads ─────────────────────────────────────────────────────────────────────


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


@app.get("/api/v1/leads")
def list_leads(x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    return list(_leads.values())


@app.get("/api/v1/leads/{lead_id}")
def get_lead(lead_id: str, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    if lead_id not in _leads:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _leads[lead_id]


# ── Outreach ──────────────────────────────────────────────────────────────────


@app.post("/api/v1/outreach", response_model=OutreachResponse, status_code=201)
def create_outreach(body: OutreachRequest, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    if body.lead_id not in _leads:
        raise HTTPException(status_code=404, detail=f"lead_id {body.lead_id!r} not found")
    outreach_id = str(uuid.uuid4())
    _outreach[outreach_id] = {**body.model_dump(), "outreach_id": outreach_id}
    print(f"[MOCK] Outreach {body.status}: {outreach_id} for lead {body.lead_id}")
    return {"outreach_id": outreach_id}


@app.get("/api/v1/outreach")
def list_outreach(
    status: str | None = None,
    x_api_key: str | None = Header(default=None),
):
    _check_auth(x_api_key)
    items = list(_outreach.values())
    if status:
        items = [o for o in items if o.get("status") == status]
    return items


@app.get("/api/v1/outreach/{outreach_id}")
def get_outreach(outreach_id: str, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    if outreach_id not in _outreach:
        raise HTTPException(status_code=404, detail="Outreach not found")
    return _outreach[outreach_id]


@app.patch("/api/v1/outreach/{outreach_id}")
def patch_outreach(
    outreach_id: str,
    body: OutreachPatch,
    x_api_key: str | None = Header(default=None),
):
    _check_auth(x_api_key)
    if outreach_id not in _outreach:
        raise HTTPException(status_code=404, detail="Outreach not found")
    from datetime import datetime, timezone
    _outreach[outreach_id]["status"] = body.status
    if body.status == "approved":
        _outreach[outreach_id]["approved_at"] = (
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
    print(f"[MOCK] Outreach {outreach_id} → {body.status}")
    return _outreach[outreach_id]


# ── Entry point ───────────────────────────────────────────────────────────────


def run():
    import uvicorn
    uvicorn.run("mock_server.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
