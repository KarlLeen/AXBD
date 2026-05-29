"""AthenaX API client — wraps both mock and real endpoints identically."""
import json
import os
from datetime import datetime, timezone

import httpx


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class AthenaXClient:
    def __init__(self):
        self.base_url = os.getenv("ATHENAX_API_URL", "http://localhost:8000").rstrip("/")
        api_key = os.getenv("ATHENAX_API_KEY", "")
        self._headers = {"X-API-Key": api_key} if api_key else {}

    # ── Write ────────────────────────────────────────────────────────────────

    def push_lead(self, data: dict) -> str:
        """Push a lead. Returns remote lead UUID."""
        payload = {
            "name": data["name"],
            "url": data["url"],
            "source": data["source"],
            "compatibility_score": data["compatibility_score"],
            "reason_for_partnership": data["reason_for_partnership"],
            "nounish_traits": json.loads(data.get("nounish_traits") or "[]"),
            "tech_stack": json.loads(data.get("tech_stack") or "[]"),
            "submitted_at": _now(),
        }
        resp = httpx.post(
            f"{self.base_url}/api/v1/leads",
            json=payload,
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["lead_id"]

    def push_draft(self, data: dict, remote_lead_id: str) -> str:
        """Push a draft with status=pending (for bot review). Returns remote outreach UUID."""
        payload = {
            "lead_id": remote_lead_id,
            "channel": data["channel"],
            "subject": data.get("subject"),
            "body": data["body"],
            "status": "pending",
            # enrichment so the bot can display context without extra calls
            "lead_name": data.get("lead_name", ""),
            "compatibility_score": data.get("compatibility_score"),
        }
        resp = httpx.post(
            f"{self.base_url}/api/v1/outreach",
            json=payload,
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["outreach_id"]

    def push_outreach(self, data: dict, remote_lead_id: str, approved_at: str) -> str:
        """Push an approved outreach draft. Returns remote outreach UUID."""
        payload = {
            "lead_id": remote_lead_id,
            "channel": data["channel"],
            "subject": data.get("subject"),
            "body": data["body"],
            "status": "approved",
            "approved_at": approved_at,
        }
        resp = httpx.post(
            f"{self.base_url}/api/v1/outreach",
            json=payload,
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["outreach_id"]

    def patch_outreach_status(self, remote_outreach_id: str, status: str) -> dict:
        """Approve or reject an outreach draft via PATCH. Returns updated record."""
        resp = httpx.patch(
            f"{self.base_url}/api/v1/outreach/{remote_outreach_id}",
            json={"status": status},
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_pending_outreach(self) -> list[dict]:
        """Return all outreach drafts with status=pending."""
        resp = httpx.get(
            f"{self.base_url}/api/v1/outreach",
            params={"status": "pending"},
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_lead(self, remote_lead_id: str) -> dict:
        """Fetch a single lead by remote ID."""
        resp = httpx.get(
            f"{self.base_url}/api/v1/leads/{remote_lead_id}",
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
