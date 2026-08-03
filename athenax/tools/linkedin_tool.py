"""ConnectSafely.ai LinkedIn tool — compliant profile & post discovery."""
import json
import os
import re
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import httpx

from athenax.tools._retry import api_retry

_BASE = "https://api.connectsafely.ai/linkedin"


def _headers() -> dict:
    key = os.getenv("CONNECTSAFELY_API_KEY", "")
    if not key:
        raise ValueError("CONNECTSAFELY_API_KEY not set")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _person_slug(profile_id: str) -> str | None:
    """Accept a vanity slug or full /in/ URL; reject company URLs."""
    s = (profile_id or "").strip()
    if not s:
        return None
    if "linkedin.com/company/" in s.lower():
        return None
    m = re.search(r"linkedin\.com/in/([^/?#]+)", s, flags=re.I)
    if m:
        return m.group(1).strip("/")
    s = s.strip("/").split("/")[-1]
    if not s or s.lower() in {"in", "company", "linkedin.com"}:
        return None
    return s


# ── Input schemas ────────────────────────────────────────────────────────────


class LinkedInPeopleSearchInput(BaseModel):
    keywords: str = Field(
        description=(
            'People search keywords. Prefer exact company + role, e.g. '
            '"XMTP" founder OR "XMTP" "co-founder". Vague queries return noise.'
        ),
    )
    count: int = Field(default=10, description="Number of results to return")


class LinkedInCompanySearchInput(BaseModel):
    keywords: str = Field(description="Company name or description keywords")
    count: int = Field(default=10, description="Number of results")


class LinkedInPostSearchInput(BaseModel):
    keywords: str = Field(description="Keywords to search in post content")
    count: int = Field(default=10, description="Number of posts to return")


class LinkedInProfileInput(BaseModel):
    profile_id: str = Field(
        description=(
            "PERSON vanity slug or full https://www.linkedin.com/in/... URL. "
            "Never pass a /company/ URL — use linkedin_company_search for companies."
        ),
    )


# ── Tools ────────────────────────────────────────────────────────────────────


class LinkedInPeopleSearchTool(BaseTool):
    name: str = "linkedin_people_search"
    description: str = (
        "Search LinkedIn for people by keywords via ConnectSafely.ai. "
        "Results are noisy — ONLY trust a hit if the headline/current_company clearly "
        "mentions the target company. Use keywords like '\"CompanyName\" founder'."
    )
    args_schema: type[BaseModel] = LinkedInPeopleSearchInput

    def _run(self, keywords: str, count: int = 10) -> str:
        if isinstance(keywords, dict):
            keywords = keywords.get("keywords") or ""
        keywords = str(keywords or "").strip()
        if not keywords:
            return json.dumps({"error": "empty keywords"})

        @api_retry
        def _call():
            # Prefer V1 — V2 RSC often returns [] depending on account/region rollout.
            r = httpx.post(
                f"{_BASE}/search/people",
                headers=_headers(),
                json={"keywords": keywords, "limit": count},
                timeout=45,
            )
            r.raise_for_status()
            return r
        resp = _call()
        data = resp.json()
        people = data.get("people", data.get("results", []))

        results = []
        for p in people:
            url = (p.get("profileUrl") or "").strip()
            if not url:
                pid = (p.get("profileId") or p.get("publicIdentifier") or "").strip()
                if pid and "/" not in pid:
                    url = f"https://www.linkedin.com/in/{pid}"
            results.append({
                "source": "linkedin",
                "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "headline": p.get("headline", ""),
                "linkedin_profile": url,
                "location": p.get("location", ""),
                "current_company": p.get("currentCompany") or p.get("currentPosition") or "",
                "is_premium": p.get("isPremium", False),
            })
        return json.dumps({
            "results": results,
            "hint": (
                "Discard anyone whose headline/current_company does not clearly "
                "reference the target company. Company pages are NOT team members."
            ),
        }, ensure_ascii=False, indent=2)


class LinkedInCompanySearchTool(BaseTool):
    name: str = "linkedin_company_search"
    description: str = (
        "Search LinkedIn for companies by keywords via ConnectSafely.ai. "
        "Returns COMPANY pages only — not founders. For team, use linkedin_people_search."
    )
    args_schema: type[BaseModel] = LinkedInCompanySearchInput

    def _run(self, keywords: str, count: int = 10) -> str:
        @api_retry
        def _call():
            r = httpx.post(f"{_BASE}/search/companies", headers=_headers(),
                           json={"keywords": keywords, "count": count}, timeout=30)
            r.raise_for_status()
            return r
        resp = _call()
        data = resp.json()
        companies = data.get("companies", data.get("results", []))

        results = []
        for c in companies:
            results.append({
                "source": "linkedin",
                "name": c.get("name", ""),
                "url": f"https://linkedin.com/company/{c.get('universalName', c.get('companyId', ''))}",
                "description": c.get("description", c.get("headline", "")),
                "linkedin_profile": f"https://linkedin.com/company/{c.get('universalName', '')}",
            })
        return json.dumps(results, ensure_ascii=False, indent=2)


class LinkedInPostSearchTool(BaseTool):
    name: str = "linkedin_post_search"
    description: str = (
        "Search recent LinkedIn posts by keywords via ConnectSafely.ai. "
        "Use to surface builders posting about Web3, DAO, CC0, or public goods."
    )
    args_schema: type[BaseModel] = LinkedInPostSearchInput

    def _run(self, keywords: str, count: int = 10) -> str:
        @api_retry
        def _call():
            r = httpx.post(f"{_BASE}/posts/search", headers=_headers(),
                           json={"keywords": keywords, "count": count}, timeout=30)
            r.raise_for_status()
            return r
        resp = _call()
        data = resp.json()
        posts = data.get("posts", data.get("results", []))

        results = []
        for p in posts:
            author = p.get("author", {}) if isinstance(p.get("author"), dict) else {}
            results.append({
                "source": "linkedin",
                "text": p.get("text", p.get("commentary", "")),
                "url": p.get("url", p.get("postUrl", "")),
                "author": author.get("name", ""),
                "author_headline": author.get("headline", ""),
            })
        return json.dumps(results, ensure_ascii=False, indent=2)


class LinkedInProfileTool(BaseTool):
    name: str = "linkedin_profile"
    description: str = (
        "Fetch a LinkedIn PERSON profile by vanity slug or /in/ URL via ConnectSafely.ai. "
        "Do NOT pass company universal names (e.g. junction-exchange) — that 404s."
    )
    args_schema: type[BaseModel] = LinkedInProfileInput

    def _run(self, profile_id: str) -> str:
        slug = _person_slug(profile_id)
        if not slug:
            return json.dumps({
                "error": (
                    "linkedin_profile expects a person /in/ slug or URL, not a company page. "
                    f"Got: {profile_id!r}"
                ),
            })
        resp = httpx.get(
            f"{_BASE}/profile",
            headers=_headers(),
            params={"profileId": slug},
            timeout=15,
        )
        if resp.status_code == 404:
            return json.dumps({
                "error": f"person profile not found for slug={slug!r}",
                "hint": "Use a person vanity from linkedin_people_search profileUrl",
            })
        resp.raise_for_status()
        data = resp.json()
        # ConnectSafely nests person fields under `profile`
        profile = data.get("profile") if isinstance(data.get("profile"), dict) else data
        result = {
            "source": "linkedin",
            "linkedin_profile": f"https://linkedin.com/in/{slug}",
            "name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
            "headline": profile.get("headline", ""),
            "description": profile.get("summary", profile.get("about", "")),
            "connection_count": profile.get("connectionCount"),
            "follower_count": profile.get("followerCount"),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
