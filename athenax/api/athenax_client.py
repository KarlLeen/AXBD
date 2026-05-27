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

    def push_lead(self, data: dict) -> str:
        """Push a lead to AthenaX. Returns the remote lead UUID."""
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

    def push_outreach(self, data: dict, remote_lead_id: str, approved_at: str) -> str:
        """Push an approved outreach draft to AthenaX. Returns the remote outreach UUID."""
        payload = {
            "lead_id": remote_lead_id,
            "channel": data["channel"],
            "subject": data.get("subject"),
            "body": data["body"],
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
