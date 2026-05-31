"""AthenaX API client — mapped to AthenaX products/categories schema."""
import json
import os
import re
from datetime import datetime, timezone

import httpx


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_slug(name: str) -> str:
    """Convert a project name to a URL slug. e.g. 'unionlabs/union' → 'unionlabs-union'"""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:150]


class AthenaXClient:
    def __init__(self):
        self.base_url = os.getenv("ATHENAX_API_URL", "http://localhost:8000").rstrip("/")
        api_key = os.getenv("ATHENAX_API_KEY", "")
        self._headers = {"X-API-Key": api_key} if api_key else {}

    # ── Categories ────────────────────────────────────────────────────────────

    def get_categories(self) -> list[dict]:
        """Fetch available product categories from AthenaX."""
        resp = httpx.get(
            f"{self.base_url}/api/v1/categories",
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def match_category(self, sector: str, categories: list[dict]) -> int | None:
        """Find the best-matching category_id for a given sector string."""
        if not categories or not sector:
            return None
        sector_lower = sector.lower()
        # Exact match first
        for cat in categories:
            if cat["name"].lower() == sector_lower:
                return cat["id"]
        # Partial match
        for cat in categories:
            if cat["name"].lower() in sector_lower or sector_lower in cat["name"].lower():
                return cat["id"]
        return None

    # ── Products ──────────────────────────────────────────────────────────────

    def push_product(self, lead: dict, evaluation: dict, category_id: int | None = None) -> str:
        """
        Push a discovered project as a Draft product to AthenaX.
        Maps agent lead + evaluation data → AthenaX products schema.
        Returns the remote product id.
        """
        name = lead.get("name", "")
        desc = lead.get("description", "") or ""
        short_desc = (desc[:147] + "...") if len(desc) > 150 else desc
        if not short_desc:
            short_desc = evaluation.get("reason_for_partnership", "")[:150]

        payload = {
            "slug": _to_slug(name),
            "name": name,
            "short_desc": short_desc,
            "desc": _build_desc(desc, evaluation),
            "status": "Draft",
            "stage": lead.get("funding_stage"),
            "github": _extract_github_url(lead),
            "category_id": category_id,
            # Agent metadata stored as extra fields (AthenaX may ignore unknowns)
            "agent_score": evaluation.get("compatibility_score"),
            "agent_sector": lead.get("sector"),
        }

        resp = httpx.post(
            f"{self.base_url}/api/v1/products",
            json=payload,
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data.get("id") or data.get("product_id", ""))

    def push_product_links(self, product_id: str, lead: dict) -> None:
        """Push website, GitHub, and Twitter links for a product."""
        links = _build_links(lead)
        for link in links:
            try:
                httpx.post(
                    f"{self.base_url}/api/v1/products/{product_id}/links",
                    json=link,
                    headers=self._headers,
                    timeout=10,
                )
            except Exception:
                pass  # links are enrichment — don't fail the whole push

    def push_product_backers(self, product_id: str, lead: dict) -> None:
        """Push known VC backers for a product."""
        vc = lead.get("vc_backing", "")
        if not vc:
            return
        try:
            httpx.post(
                f"{self.base_url}/api/v1/products/{product_id}/backers",
                json={"name": vc},
                headers=self._headers,
                timeout=10,
            )
        except Exception:
            pass

    def push_outreach_draft(self, product_id: str, draft: dict, evaluation: dict) -> None:
        """
        Push the outreach draft as a product comment (internal review note).
        Uses product_comments table.
        """
        channel = "Twitter DM" if draft.get("channel") == "twitter_dm" else "Email"
        subject = f"Subject: {draft['subject']}\n\n" if draft.get("subject") else ""
        text = (
            f"[Outreach Draft — {channel}]\n"
            f"Score: {evaluation.get('compatibility_score', '?')}/100\n"
            f"Reason: {evaluation.get('reason_for_partnership', '')}\n\n"
            f"{subject}{draft.get('body', '')}"
        )
        try:
            httpx.post(
                f"{self.base_url}/api/v1/products/{product_id}/comments",
                json={"text": text},
                headers=self._headers,
                timeout=10,
            )
        except Exception:
            pass

    # ── Legacy outreach endpoints (kept for backward compat with mock dev flow) ──

    def push_draft(self, data: dict, remote_lead_id: str) -> str:
        """Push a pending outreach draft. Returns remote outreach UUID."""
        payload = {
            "lead_id": remote_lead_id,
            "channel": data["channel"],
            "subject": data.get("subject"),
            "body": data["body"],
            "status": "pending",
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
        resp = httpx.patch(
            f"{self.base_url}/api/v1/outreach/{remote_outreach_id}",
            json={"status": status},
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_pending_outreach(self) -> list[dict]:
        resp = httpx.get(
            f"{self.base_url}/api/v1/outreach",
            params={"status": "pending"},
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    def get_lead(self, remote_lead_id: str) -> dict:
        resp = httpx.get(
            f"{self.base_url}/api/v1/leads/{remote_lead_id}",
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # Legacy push_lead — kept for CLI review backward compat
    def push_lead(self, data: dict) -> str:
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_github_url(lead: dict) -> str | None:
    if lead.get("source") == "github":
        return lead.get("url")
    tech = lead.get("tech_stack", "")
    url = lead.get("url", "")
    if "github.com" in url:
        return url
    return None


def _build_links(lead: dict) -> list[dict]:
    links = []
    source = lead.get("source", "")
    url = lead.get("url", "")

    if source == "github" and url:
        links.append({"link_type": "github", "url": url, "is_primary": True})
    elif url:
        links.append({"link_type": "website", "url": url, "is_primary": True})

    if lead.get("twitter_handle"):
        links.append({
            "link_type": "twitter",
            "url": f"https://twitter.com/{lead['twitter_handle']}",
            "is_primary": False,
        })
    if lead.get("linkedin_profile"):
        links.append({
            "link_type": "website",
            "url": lead["linkedin_profile"],
            "label": "LinkedIn",
            "is_primary": False,
        })
    return links


def _build_desc(raw_desc: str, evaluation: dict) -> str:
    parts = []
    if raw_desc:
        parts.append(raw_desc)
    reason = evaluation.get("reason_for_partnership", "")
    if reason:
        parts.append(f"\n**Why AthenaX:** {reason}")
    notes = evaluation.get("listing_fit_notes", "")
    if notes:
        parts.append(f"\n**Listing fit:** {notes}")
    traits = evaluation.get("nounish_traits")
    if traits:
        if isinstance(traits, str):
            import json as _json
            try:
                traits = _json.loads(traits)
            except Exception:
                traits = []
        if traits:
            parts.append(f"\n**Tags:** {', '.join(traits)}")
    return "\n".join(parts)
