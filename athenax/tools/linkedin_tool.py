"""ConnectSafely.ai LinkedIn tool — compliant profile & post discovery."""
import json
import os
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


# ── Input schemas ────────────────────────────────────────────────────────────


class LinkedInPeopleSearchInput(BaseModel):
    keywords: str = Field(description="Keywords for name, title, company, or skills")
    count: int = Field(default=10, description="Number of results to return")


class LinkedInCompanySearchInput(BaseModel):
    keywords: str = Field(description="Company name or description keywords")
    count: int = Field(default=10, description="Number of results")


class LinkedInPostSearchInput(BaseModel):
    keywords: str = Field(description="Keywords to search in post content")
    count: int = Field(default=10, description="Number of posts to return")


class LinkedInProfileInput(BaseModel):
    profile_id: str = Field(description="LinkedIn vanity URL slug, e.g. 'vitalik-buterin'")


# ── Tools ────────────────────────────────────────────────────────────────────


class LinkedInPeopleSearchTool(BaseTool):
    name: str = "linkedin_people_search"
    description: str = (
        "Search LinkedIn for people by keywords (name, title, company, skills) "
        "via ConnectSafely.ai. Use to find Web3 founders and DAO builders."
    )
    args_schema: type[BaseModel] = LinkedInPeopleSearchInput

    def _run(self, keywords: str, count: int = 10) -> str:
        @api_retry
        def _call():
            r = httpx.post(f"{_BASE}/search/people/v2", headers=_headers(),
                           json={"keywords": keywords, "count": count}, timeout=30)
            r.raise_for_status()
            return r
        resp = _call()
        data = resp.json()
        people = data.get("people", data.get("results", []))

        results = []
        for p in people:
            results.append({
                "source": "linkedin",
                "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "headline": p.get("headline", ""),
                "linkedin_profile": p.get("profileUrl", ""),
                "location": p.get("location", ""),
                "current_company": p.get("currentCompany", ""),
                "is_premium": p.get("isPremium", False),
            })
        return json.dumps(results, ensure_ascii=False, indent=2)


class LinkedInCompanySearchTool(BaseTool):
    name: str = "linkedin_company_search"
    description: str = (
        "Search LinkedIn for companies by keywords via ConnectSafely.ai. "
        "Use to find Web3 startups, DAO tooling companies, and public goods orgs."
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
        for post in posts:
            author = post.get("author", {})
            results.append({
                "source": "linkedin",
                "name": author.get("name", ""),
                "linkedin_profile": author.get("profileUrl", ""),
                "linkedin_recent_post": post.get("text", ""),
                "post_url": post.get("url", ""),
                "likes": post.get("likes", 0),
                "comments": post.get("comments", 0),
            })
        return json.dumps(results, ensure_ascii=False, indent=2)


class LinkedInProfileTool(BaseTool):
    name: str = "linkedin_profile"
    description: str = (
        "Fetch a LinkedIn profile by vanity URL slug via ConnectSafely.ai. "
        "Returns name, headline, connection count, and follower count."
    )
    args_schema: type[BaseModel] = LinkedInProfileInput

    def _run(self, profile_id: str) -> str:
        resp = httpx.get(
            f"{_BASE}/profile",
            headers=_headers(),
            params={"profileId": profile_id},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        result = {
            "source": "linkedin",
            "linkedin_profile": f"https://linkedin.com/in/{profile_id}",
            "name": f"{data.get('firstName', '')} {data.get('lastName', '')}".strip(),
            "headline": data.get("headline", ""),
            "description": data.get("summary", ""),
            "connection_count": data.get("connectionCount"),
            "follower_count": data.get("followerCount"),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
