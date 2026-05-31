"""
FastAPI mock server — mirrors the AthenaX production schema.

Tables simulated: products, categories, product_links, product_backers,
                  product_comments, outreach (internal agent workflow)
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

app = FastAPI(title="AthenaX API (Mock)", version="0.3.0")

# ── In-memory stores ──────────────────────────────────────────────────────────
_categories: dict[int, dict] = {
    1:  {"id": 1,  "name": "AI & Agents"},
    2:  {"id": 2,  "name": "Biotech"},
    3:  {"id": 3,  "name": "Crypto"},
    4:  {"id": 4,  "name": "Developer Tools"},
    5:  {"id": 5,  "name": "Infrastructure"},
    6:  {"id": 6,  "name": "Robotics"},
    7:  {"id": 7,  "name": "RWA"},
}
_products: dict[str, dict] = {}
_product_links: dict[str, list] = {}
_product_backers: dict[str, list] = {}
_product_comments: dict[str, list] = {}

# Legacy outreach store (used by Telegram bot flow)
_leads: dict[str, dict] = {}
_outreach: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _check_auth(x_api_key: str | None) -> None:
    expected = os.getenv("ATHENAX_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


# ── Models ────────────────────────────────────────────────────────────────────

class ProductRequest(BaseModel):
    slug: str
    name: str
    short_desc: str
    desc: str | None = None
    status: Literal["Draft", "Published", "Archived"] = "Draft"
    stage: str | None = None
    funding: float | None = None
    founded: int | None = None
    github: str | None = None
    demo: str | None = None
    quality_badge: str | None = None
    category_id: int | None = None
    # Agent metadata (extra fields — may be ignored by real API)
    agent_score: int | None = None
    agent_sector: str | None = None


class ProductLinkRequest(BaseModel):
    link_type: str
    url: str
    label: str | None = None
    is_primary: bool = False


class ProductBackerRequest(BaseModel):
    name: str


class ProductCommentRequest(BaseModel):
    text: str


class OutreachRequest(BaseModel):
    lead_id: str
    channel: str
    subject: str | None = None
    body: str
    status: Literal["pending", "approved", "rejected"] = "pending"
    approved_at: str | None = None
    lead_name: str | None = None
    compatibility_score: int | None = None


class OutreachPatch(BaseModel):
    status: Literal["approved", "rejected"]


class LeadRequest(BaseModel):
    name: str
    url: str
    source: str
    compatibility_score: int
    reason_for_partnership: str
    nounish_traits: list[str] = []
    tech_stack: list[str] = []
    submitted_at: str


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "server": "mock", "version": "0.3.0"}


# ── Categories ────────────────────────────────────────────────────────────────

@app.get("/api/v1/categories")
def list_categories(x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    return list(_categories.values())


@app.get("/api/v1/categories/{category_id}")
def get_category(category_id: int, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    if category_id not in _categories:
        raise HTTPException(status_code=404, detail="Category not found")
    return _categories[category_id]


# ── Products ──────────────────────────────────────────────────────────────────

@app.post("/api/v1/products", status_code=201)
def create_product(body: ProductRequest, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    # Ensure slug is unique
    if any(p["slug"] == body.slug for p in _products.values()):
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists")
    product_id = str(uuid.uuid4())
    product = {
        **body.model_dump(),
        "id": product_id,
        "created_at": _now(),
        "updated_at": _now(),
    }
    if body.category_id and body.category_id in _categories:
        product["category"] = _categories[body.category_id]
    _products[product_id] = product
    _product_links[product_id] = []
    _product_backers[product_id] = []
    _product_comments[product_id] = []
    print(f"[MOCK] Product created: {product_id} — {body.name} (status={body.status})")
    return {"id": product_id, "slug": body.slug}


@app.get("/api/v1/products")
def list_products(
    status: str | None = None,
    x_api_key: str | None = Header(default=None),
):
    _check_auth(x_api_key)
    items = list(_products.values())
    if status:
        items = [p for p in items if p.get("status") == status]
    return items


@app.get("/api/v1/products/{product_id}")
def get_product(product_id: str, x_api_key: str | None = Header(default=None)):
    _check_auth(x_api_key)
    if product_id not in _products:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
        **_products[product_id],
        "links":    _product_links.get(product_id, []),
        "backers":  _product_backers.get(product_id, []),
        "comments": _product_comments.get(product_id, []),
    }


@app.patch("/api/v1/products/{product_id}")
def patch_product(
    product_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
):
    _check_auth(x_api_key)
    if product_id not in _products:
        raise HTTPException(status_code=404, detail="Product not found")
    _products[product_id].update({**body, "updated_at": _now()})
    return _products[product_id]


# ── Product sub-resources ─────────────────────────────────────────────────────

@app.post("/api/v1/products/{product_id}/links", status_code=201)
def add_product_link(
    product_id: str,
    body: ProductLinkRequest,
    x_api_key: str | None = Header(default=None),
):
    _check_auth(x_api_key)
    if product_id not in _products:
        raise HTTPException(status_code=404, detail="Product not found")
    link = {**body.model_dump(), "id": str(uuid.uuid4()), "created_at": _now()}
    _product_links[product_id].append(link)
    return link


@app.post("/api/v1/products/{product_id}/backers", status_code=201)
def add_product_backer(
    product_id: str,
    body: ProductBackerRequest,
    x_api_key: str | None = Header(default=None),
):
    _check_auth(x_api_key)
    if product_id not in _products:
        raise HTTPException(status_code=404, detail="Product not found")
    backer = {**body.model_dump(), "id": str(uuid.uuid4()), "created_at": _now()}
    _product_backers[product_id].append(backer)
    return backer


@app.post("/api/v1/products/{product_id}/comments", status_code=201)
def add_product_comment(
    product_id: str,
    body: ProductCommentRequest,
    x_api_key: str | None = Header(default=None),
):
    _check_auth(x_api_key)
    if product_id not in _products:
        raise HTTPException(status_code=404, detail="Product not found")
    comment = {**body.model_dump(), "id": str(uuid.uuid4()), "created_at": _now()}
    _product_comments[product_id].append(comment)
    return comment


# ── Legacy outreach endpoints (Telegram bot review flow) ─────────────────────

@app.post("/api/v1/leads", status_code=201)
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


@app.post("/api/v1/outreach", status_code=201)
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
    _outreach[outreach_id]["status"] = body.status
    if body.status == "approved":
        _outreach[outreach_id]["approved_at"] = _now()
    return _outreach[outreach_id]


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    import uvicorn
    uvicorn.run("mock_server.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
