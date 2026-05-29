"""GitHub REST API tool — repository discovery + velocity signals."""
import json
import os
from datetime import datetime, timedelta, timezone
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import httpx

from athenax.tools._retry import api_retry


class GitHubSearchInput(BaseModel):
    keywords: list[str] = Field(
        default=["Web3 Infrastructure", "DAO tooling", "public goods", "CC0"],
        description="Search keywords to combine into a GitHub query",
    )
    min_stars: int = Field(default=50, description="Minimum stars filter")
    max_results: int = Field(default=20, description="Max repositories to return")


class GitHubTool(BaseTool):
    name: str = "github_search"
    description: str = (
        "Search GitHub for trending repositories matching Web3/DAO keywords. "
        "Returns repo name, URL, description, stars, forks, language, topics, "
        "and commits_last_30d for velocity scoring."
    )
    args_schema: type[BaseModel] = GitHubSearchInput

    def _run(self, keywords: list[str], min_stars: int = 50, max_results: int = 20) -> str:
        token = os.getenv("GITHUB_TOKEN", "")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        query = " OR ".join(f'"{kw}"' for kw in keywords) + f" stars:>{min_stars}"
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": min(max_results, 30),
        }

        @api_retry
        def _search():
            resp = httpx.get(
                "https://api.github.com/search/repositories",
                headers=headers,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            return resp.json()

        data = _search()
        results = []
        for repo in data.get("items", []):
            commits = self._commits_last_30d(repo["full_name"], headers)
            results.append({
                "source": "github",
                "name": repo["full_name"],
                "url": repo["html_url"],
                "description": repo.get("description", ""),
                "github_stars": repo["stargazers_count"],
                "github_forks": repo["forks_count"],
                "commits_last_30d": commits,
                "tech_stack": [repo["language"]] if repo.get("language") else [],
                "topics": repo.get("topics", []),
                "homepage": repo.get("homepage", ""),
                "pushed_at": repo.get("pushed_at", ""),
            })
        return json.dumps(results, ensure_ascii=False, indent=2)

    def _commits_last_30d(self, full_name: str, headers: dict) -> int | None:
        """Return commit count in the last 30 days. Returns None on failure."""
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        try:
            @api_retry
            def _fetch():
                return httpx.get(
                    f"https://api.github.com/repos/{full_name}/commits",
                    headers=headers,
                    params={"since": since, "per_page": 100},
                    timeout=10,
                )

            resp = _fetch()
            if resp.status_code == 409:  # empty repo
                return 0
            resp.raise_for_status()
            return len(resp.json())
        except Exception:
            return None
