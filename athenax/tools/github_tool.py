"""GitHub REST API tool — repository discovery for Web3 / DAO leads."""
import json
import os
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import httpx


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
        "Returns repo name, URL, description, stars, forks, language, and topics."
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

        resp = httpx.get(
            "https://api.github.com/search/repositories",
            headers=headers,
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for repo in data.get("items", []):
            results.append({
                "source": "github",
                "name": repo["full_name"],
                "url": repo["html_url"],
                "description": repo.get("description", ""),
                "github_stars": repo["stargazers_count"],
                "github_forks": repo["forks_count"],
                "tech_stack": [repo["language"]] if repo.get("language") else [],
                "topics": repo.get("topics", []),
                "homepage": repo.get("homepage", ""),
                "created_at": repo["created_at"],
                "updated_at": repo["updated_at"],
            })

        return json.dumps(results, ensure_ascii=False, indent=2)
