"""AthenaX Internal Service API client."""
import json
import os
import re
from datetime import datetime, timezone

import httpx


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:150]


class AthenaXClient:
    def __init__(self):
        self.base_url = os.getenv("ATHENAX_API_URL", "http://localhost:8000").rstrip("/")
        internal_key = os.getenv("INTERNAL_API_KEY", "")
        self._headers = {
            "X-Internal-Key": internal_key,
            "Content-Type": "application/json",
        }

    # ── Categories ────────────────────────────────────────────────────────────

    def get_category_by_name(self, name: str) -> dict | None:
        """GET /internal/categories/by-name — exact match, case-insensitive.
        Returns None on 404 (admin must create the category first)."""
        try:
            resp = httpx.get(
                f"{self.base_url}/api/v1/internal/categories/by-name",
                params={"name": name},
                headers=self._headers,
                timeout=15,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            return None

    def get_subcategory_by_name(self, name: str) -> dict | None:
        """GET /internal/subcategories/by-name — exact match, case-insensitive."""
        try:
            resp = httpx.get(
                f"{self.base_url}/api/v1/internal/subcategories/by-name",
                params={"name": name},
                headers=self._headers,
                timeout=15,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            return None

    def resolve_category_id(self, sector: str) -> int | None:
        """Map an agent sector string to an AthenaX category ID.
        Tries the sector name directly; falls back to known aliases."""
        _ALIASES = {
            "ai & agents": "AI & Agents",
            "ai":          "AI & Agents",
            "developer tools": "Developer Tools",
            "dev tools":   "Developer Tools",
            "infrastructure": "Infrastructure",
            "infra":       "Infrastructure",
            "crypto":      "Crypto",
            "biotech":     "Biotech",
            "robotics":    "Robotics",
            "rwa":         "RWA",
        }
        name = _ALIASES.get(sector.lower(), sector)
        cat = self.get_category_by_name(name)
        return cat["id"] if cat else None

    # ── Products ──────────────────────────────────────────────────────────────

    def get_product_by_name(self, name: str) -> dict | None:
        """GET /internal/products/by-name — returns any status including PENDING.
        Returns None on 404."""
        try:
            resp = httpx.get(
                f"{self.base_url}/api/v1/internal/products/by-name",
                params={"name": name},
                headers=self._headers,
                timeout=15,
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except httpx.ConnectError:
            return None

    def push_product(self, lead: dict, evaluation: dict, category_id: int | None = None) -> str:
        """POST /internal/products — creates a PENDING product.
        Returns the remote product id string. Raises on failure."""
        name = lead.get("name", "")
        desc = lead.get("description", "") or ""
        short_desc = (desc[:147] + "...") if len(desc) > 150 else desc
        if not short_desc:
            short_desc = evaluation.get("reason_for_partnership", "")[:150]

        payload: dict = {
            "name": name,
            "short_desc": short_desc,
            "desc": _build_desc(desc, evaluation),
        }
        if category_id is not None:
            payload["categoryIds"] = [category_id]

        resp = httpx.post(
            f"{self.base_url}/api/v1/internal/products",
            json=payload,
            headers=self._headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data.get("id") or data.get("product_id", ""))

    # ── Legacy methods kept for CLI review / Telegram bot backward compat ─────

    def get_categories(self) -> list[dict]:
        """Legacy: fetch all categories. Kept for backward compat — prefer resolve_category_id."""
        try:
            resp = httpx.get(
                f"{self.base_url}/api/v1/internal/categories/by-name",
                params={"name": ""},
                headers=self._headers,
                timeout=15,
            )
            if resp.status_code in (404, 422):
                return []
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else [data]
        except Exception:
            return []

    def match_category(self, sector: str, _categories: list[dict]) -> int | None:
        """Legacy wrapper — delegates to resolve_category_id."""
        return self.resolve_category_id(sector)

    def push_product_links(self, product_id: str, lead: dict) -> None:
        """Not part of internal API spec — no-op."""
        pass

    def push_product_backers(self, product_id: str, lead: dict) -> None:
        """Not part of internal API spec — no-op."""
        pass

    def push_outreach_draft(self, product_id: str, draft: dict, evaluation: dict) -> None:
        """Not part of internal API spec — no-op."""
        pass

    def push_draft(self, data: dict, remote_lead_id: str) -> str:
        raise NotImplementedError("Legacy outreach endpoint not available in internal API")

    def push_outreach(self, data: dict, remote_lead_id: str, approved_at: str) -> str:
        raise NotImplementedError("Legacy outreach endpoint not available in internal API")

    def patch_outreach_status(self, remote_outreach_id: str, status: str) -> dict:
        raise NotImplementedError("Legacy outreach endpoint not available in internal API")

    def get_pending_outreach(self) -> list[dict]:
        raise NotImplementedError("Legacy outreach endpoint not available in internal API")

    def get_lead(self, remote_lead_id: str) -> dict:
        raise NotImplementedError("Legacy lead endpoint not available in internal API")

    def push_lead(self, data: dict) -> str:
        raise NotImplementedError("Legacy lead endpoint not available in internal API")


# ── Helpers ───────────────────────────────────────────────────────────────────

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
            try:
                traits = json.loads(traits)
            except Exception:
                traits = []
        if traits:
            parts.append(f"\n**Tags:** {', '.join(traits)}")
    return "\n".join(parts)
