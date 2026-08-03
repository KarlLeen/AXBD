"""Serper API tool — web discovery via Google Search."""
import json
import os
import threading
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import httpx

from athenax.tools._retry import api_retry

# Process-wide budget so one enrich batch cannot burn the whole Serper balance.
_LOCK = threading.Lock()
_CALLS = 0


def _budget() -> int:
    raw = os.getenv("ENRICH_MAX_SERPER_CALLS", "600")
    try:
        return max(0, int(raw))
    except ValueError:
        return 600


def serper_calls_used() -> int:
    return _CALLS


class SerperSearchInput(BaseModel):
    query: str = Field(description="Search query (e.g. 'DAO tooling startup YCombinator 2024')")
    num: int = Field(default=8, description="Number of results (max 20)")


class SerperTool(BaseTool):
    name: str = "web_search"
    description: str = (
        "Google Search via Serper. Credits are LIMITED — use at most 1–2 focused queries "
        "per company (combine founder/funding/year into one query when possible). "
        "Always pass a non-empty string query."
    )
    args_schema: type[BaseModel] = SerperSearchInput

    def _run(self, query: str, num: int = 8) -> str:
        global _CALLS
        api_key = os.getenv("SERPER_API_KEY", "")
        if not api_key:
            return json.dumps({"error": "SERPER_API_KEY not set"})

        if isinstance(query, dict):
            query = query.get("query") or query.get("q") or ""
        if not isinstance(query, str):
            query = str(query or "")
        query = query.strip()
        if not query:
            return json.dumps({"error": "empty query — pass a non-empty search string"})

        budget = _budget()
        with _LOCK:
            if _CALLS >= budget:
                return json.dumps({
                    "error": f"serper budget exhausted ({_CALLS}/{budget})",
                    "hint": "Use Cryptorank/Twitter/LinkedIn/GitHub instead; do not retry web_search.",
                })
            _CALLS += 1
            used = _CALLS

        try:
            num = int(num or 8)
        except (TypeError, ValueError):
            num = 8
        num = max(1, min(num, 10))

        @api_retry
        def _call():
            r = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": query, "num": num},
                timeout=15,
            )
            if r.status_code >= 400:
                return {"_http_error": r.status_code, "_body": r.text[:500]}
            return r.json()

        data = _call()
        if isinstance(data, dict) and data.get("_http_error"):
            return json.dumps({
                "error": f"serper HTTP {data['_http_error']}",
                "detail": data.get("_body", ""),
                "query": query,
                "serper_calls_used": used,
            })

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

        payload = {
            "results": results,
            "serper_calls_used": used,
            "serper_budget": budget,
            "credits_reported": data.get("credits"),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
