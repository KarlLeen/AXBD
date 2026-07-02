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

        # shortDesc: use dedicated field first, fall back to truncated description
        short_desc = lead.get("short_description") or ""
        if not short_desc:
            short_desc = (desc[:147] + "...") if len(desc) > 150 else desc
        if not short_desc:
            short_desc = evaluation.get("reason_for_partnership", "")[:150]
        if short_desc and len(short_desc) > 150:
            short_desc = short_desc[:147] + "..."

        payload: dict = {
            "name": name,
            "shortDesc": short_desc or None,
            "description": _build_desc(desc, evaluation, lead),
            "imported": True,
        }

        # Subcategory — send as free-text suggestion (admin resolves to ID)
        subcategory = lead.get("subcategory") or ""
        if subcategory and subcategory not in ("not found", "Not Found"):
            payload["otherSubcategoryName"] = subcategory[:100]

        # Primary URL
        url = lead.get("url") or lead.get("homepage") or lead.get("website")
        if url:
            payload["url"] = url[:500]

        # Funding stage — DB column is "stage"
        stage = _map_stage(lead.get("stage") or lead.get("funding_stage"))
        if stage:
            payload["stage"] = stage

        # Founded year — DB column is "founded" (TEXT), cast to int
        founded = lead.get("founded")
        if founded:
            try:
                payload["founded"] = int(str(founded).strip())
            except (TypeError, ValueError):
                pass

        # Total funding raised (USD number)
        funding = lead.get("funding_amount") or lead.get("funding")
        if isinstance(funding, (int, float)) and funding > 0:
            payload["funding"] = funding

        # Contact email
        email = lead.get("contact_email") or lead.get("email")
        if email:
            payload["email"] = str(email)[:200]

        # Category
        if category_id is not None:
            payload["categoryIds"] = [category_id]

        # Backers — DB stores as JSON list in "backers" column
        backers = lead.get("backers")
        if isinstance(backers, str):
            try:
                backers = json.loads(backers)
            except Exception:
                backers = [b.strip() for b in backers.split(",") if b.strip()]
        if not backers:
            vc = lead.get("vc_backing")
            if vc:
                backers = [b.strip() for b in str(vc).split(",") if b.strip()]
        if backers and isinstance(backers, list):
            payload["backers"] = [str(b) for b in backers if b]

        # Team members
        team = lead.get("team")
        if isinstance(team, str):
            try:
                team = json.loads(team)
            except Exception:
                team = []
        if team and isinstance(team, list):
            payload["team"] = [
                {
                    "name": m.get("name", ""),
                    "roleLabel": m.get("title") or m.get("roleLabel") or None,
                    "bioNote": m.get("bio") or m.get("bioNote") or None,
                    "linkedinUrl": m.get("linkedin") or m.get("linkedinUrl") or None,
                    "twitterUrl": m.get("twitter") or m.get("twitterUrl") or None,
                    "githubUrl": m.get("github") or m.get("githubUrl") or None,
                    "otherUrl": m.get("other_url") or m.get("otherUrl") or None,
                }
                for m in team
                if isinstance(m, dict) and m.get("name") and m.get("name") not in ("not found", "")
            ]

        # Links — github, twitter, discord, docs, linkedin
        payload["links"] = _build_links(lead)

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

# Stage enum allowed by the API (case-sensitive)
_STAGE_MAP = {
    "pre-seed":           "Pre-Seed",
    "pre seed":           "Pre-Seed",
    "seed":               "Seed",
    "series a":           "Series A",
    "series b":           "Series B",
    "series c":           "Series B",   # API has no Series C — map to Series B
    "beta":               "Beta",
    "launched":           "Launched",
    "active":             "Active",
    "active development": "Active Development",
    "acquired":           "Acquired / Operating",
    "acquired / operating": "Acquired / Operating",
}

def _map_stage(raw: str | None) -> str | None:
    if not raw:
        return None
    return _STAGE_MAP.get(raw.strip().lower())


def _build_links(lead: dict) -> list[dict]:
    """Build the links array for the API payload.

    NOTE: Do NOT include linkType "website" here — the backend creates that
    automatically from the top-level `url` field. Sending both causes a
    UniqueViolationError on uq_product_links_product_link_type.
    """
    links = []
    source = lead.get("source", "")
    url = lead.get("url", "") or ""

    # GitHub — prefer dedicated field, fall back to url
    github_url = lead.get("github_url")
    if not github_url:
        if source == "github" and url:
            github_url = url
        elif "github.com" in url:
            github_url = url
    if github_url:
        links.append({"linkType": "github", "url": github_url[:500]})

    # Twitter/X — prefer dedicated URL, fall back to handle
    twitter_url = lead.get("twitter_url")
    if twitter_url:
        links.append({"linkType": "twitter", "url": twitter_url[:500]})
    else:
        handle = lead.get("twitter_handle")
        if handle:
            links.append({"linkType": "twitter", "url": f"https://twitter.com/{handle.lstrip('@')}"})

    # Discord
    discord_url = lead.get("discord_url")
    if discord_url:
        links.append({"linkType": "discord", "url": discord_url[:500]})

    # Docs
    docs_url = lead.get("docs_url")
    if docs_url:
        links.append({"linkType": "docs", "url": docs_url[:500]})

    # LinkedIn (as "other" — no linkedin linkType in the API)
    linkedin = lead.get("linkedin_profile")
    if linkedin:
        links.append({"linkType": "other", "url": linkedin[:500], "label": "LinkedIn"})

    return links


def _build_desc(raw_desc: str, evaluation: dict, lead: dict | None = None) -> str:
    """Build full markdown description, capped at 800 chars.
    GitHub stars are embedded here since there's no dedicated field in the API.
    """
    parts = []
    if raw_desc:
        # Cap the base description at 800 chars
        parts.append(raw_desc[:800])

    # AthenaX evaluation notes
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
