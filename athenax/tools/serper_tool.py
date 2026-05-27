"""Serper API tool — web discovery via Google Search."""
import json
import os
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import httpx


class SerperSearchInput(BaseModel):
    query: str = Field(description="Search query (e.g. 'DAO tooling startup YCombinator 2024')")
    num: int = Field(default=10, description="Number of results (max 100)")


class SerperTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "Perform Google Search via Serper API to discover and enrich leads from "
        "YCombinator, Product Hunt, and general web results. "
        "Use for finding company websites, news, and funding rounds."
    )
    args_schema: type[BaseModel] = SerperSearchInput

    def _run(self, query: str, num: int = 10) -> str:
        api_key = os.getenv("SERPER_API_KEY", "")
        if not api_key:
            raise ValueError("SERPER_API_KEY not set")

        resp = httpx.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json={"q": query, "num": num},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "position": item.get("position"),
            })

        if data.get("knowledgeGraph"):
            kg = data["knowledgeGraph"]
            results.insert(0, {
                "type": "knowledge_graph",
                "title": kg.get("title", ""),
                "description": kg.get("description", ""),
                "url": kg.get("website", ""),
            })

        return json.dumps(results, ensure_ascii=False, indent=2)
