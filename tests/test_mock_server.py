"""Integration tests for the FastAPI mock server endpoints."""
import pytest
from fastapi.testclient import TestClient
from mock_server.app import app, _leads, _outreach

client = TestClient(app)

LEAD_PAYLOAD = {
    "name": "Test Project",
    "url": "https://example.com",
    "source": "github",
    "compatibility_score": 85,
    "reason_for_partnership": "Strong CC0 alignment",
    "nounish_traits": ["CC0", "public goods"],
    "tech_stack": ["Solidity"],
    "submitted_at": "2026-01-01T00:00:00Z",
}


@pytest.fixture(autouse=True)
def clear_store():
    _leads.clear()
    _outreach.clear()
    yield
    _leads.clear()
    _outreach.clear()


# ── Health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_ok(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ── Leads ─────────────────────────────────────────────────────────────────────

class TestLeads:
    def test_create_returns_201_and_uuid(self):
        r = client.post("/api/v1/leads", json=LEAD_PAYLOAD)
        assert r.status_code == 201
        assert "lead_id" in r.json()

    def test_created_lead_appears_in_list(self):
        client.post("/api/v1/leads", json=LEAD_PAYLOAD)
        r = client.get("/api/v1/leads")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["name"] == "Test Project"

    def test_get_lead_by_id(self):
        lead_id = client.post("/api/v1/leads", json=LEAD_PAYLOAD).json()["lead_id"]
        r = client.get(f"/api/v1/leads/{lead_id}")
        assert r.status_code == 200
        assert r.json()["lead_id"] == lead_id

    def test_get_nonexistent_lead_returns_404(self):
        r = client.get("/api/v1/leads/does-not-exist")
        assert r.status_code == 404

    def test_two_leads_get_different_ids(self):
        id1 = client.post("/api/v1/leads", json=LEAD_PAYLOAD).json()["lead_id"]
        id2 = client.post("/api/v1/leads", json={**LEAD_PAYLOAD, "url": "https://other.com"}).json()["lead_id"]
        assert id1 != id2


# ── Outreach ──────────────────────────────────────────────────────────────────

class TestOutreach:
    def _setup_lead(self):
        return client.post("/api/v1/leads", json=LEAD_PAYLOAD).json()["lead_id"]

    def _outreach_payload(self, lead_id, status="pending"):
        return {
            "lead_id": lead_id,
            "channel": "twitter_dm",
            "body": "Hey, love what you built!",
            "status": status,
            "lead_name": "Test Project",
            "compatibility_score": 85,
        }

    def test_create_pending_draft(self):
        lead_id = self._setup_lead()
        r = client.post("/api/v1/outreach", json=self._outreach_payload(lead_id))
        assert r.status_code == 201
        assert "outreach_id" in r.json()

    def test_unknown_lead_returns_404(self):
        r = client.post("/api/v1/outreach", json=self._outreach_payload("bad-id"))
        assert r.status_code == 404

    def test_list_all_outreach(self):
        lead_id = self._setup_lead()
        client.post("/api/v1/outreach", json=self._outreach_payload(lead_id))
        r = client.get("/api/v1/outreach")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_filter_by_status_pending(self):
        lead_id = self._setup_lead()
        client.post("/api/v1/outreach", json=self._outreach_payload(lead_id, "pending"))
        client.post("/api/v1/outreach", json=self._outreach_payload(lead_id, "approved"))
        r = client.get("/api/v1/outreach", params={"status": "pending"})
        assert len(r.json()) == 1
        assert r.json()[0]["status"] == "pending"

    def test_filter_by_status_approved(self):
        lead_id = self._setup_lead()
        client.post("/api/v1/outreach", json=self._outreach_payload(lead_id, "approved"))
        r = client.get("/api/v1/outreach", params={"status": "approved"})
        assert len(r.json()) == 1

    def test_patch_approve(self):
        lead_id = self._setup_lead()
        oid = client.post("/api/v1/outreach", json=self._outreach_payload(lead_id)).json()["outreach_id"]
        r = client.patch(f"/api/v1/outreach/{oid}", json={"status": "approved"})
        assert r.status_code == 200
        assert r.json()["status"] == "approved"
        assert r.json()["approved_at"] is not None

    def test_patch_reject(self):
        lead_id = self._setup_lead()
        oid = client.post("/api/v1/outreach", json=self._outreach_payload(lead_id)).json()["outreach_id"]
        r = client.patch(f"/api/v1/outreach/{oid}", json={"status": "rejected"})
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"

    def test_patch_nonexistent_returns_404(self):
        r = client.patch("/api/v1/outreach/bad-id", json={"status": "approved"})
        assert r.status_code == 404

    def test_approved_removed_from_pending_list(self):
        lead_id = self._setup_lead()
        oid = client.post("/api/v1/outreach", json=self._outreach_payload(lead_id)).json()["outreach_id"]
        client.patch(f"/api/v1/outreach/{oid}", json={"status": "approved"})
        pending = client.get("/api/v1/outreach", params={"status": "pending"}).json()
        assert len(pending) == 0

    def test_get_single_outreach(self):
        lead_id = self._setup_lead()
        oid = client.post("/api/v1/outreach", json=self._outreach_payload(lead_id)).json()["outreach_id"]
        r = client.get(f"/api/v1/outreach/{oid}")
        assert r.status_code == 200
        assert r.json()["outreach_id"] == oid
