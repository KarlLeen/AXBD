"""Cryptorank Public API v3 (Sandbox) — project profile + social/docs links.

Free/Sandbox can return currency profile `links` (web/github/twitter/discord/gitbook…).
Team member socials and funding-round investors require Business/Pro and are NOT
exposed here — those stay with Serper/LinkedIn/Twitter tools.
"""
from __future__ import annotations

import json
import os
import re
import time
from difflib import SequenceMatcher

import httpx
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from athenax.tools._retry import api_retry

_BASE = "https://api.cryptorank.io/v3"
_MAP_CACHE: list[dict] | None = None
_MAP_CACHED_AT = 0.0
_MAP_TTL_SEC = 6 * 3600


def _headers() -> dict:
    key = os.getenv("CRYPTORANK_API_KEY", "").strip()
    if not key:
        raise ValueError("CRYPTORANK_API_KEY not set")
    return {"X-Api-Key": key}


def _norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _score(query: str, item: dict) -> float:
    q = _norm(query)
    if not q:
        return 0.0
    name = _norm(item.get("name") or "")
    slug = _norm((item.get("slug") or "").replace("-", " "))
    symbol = _norm(item.get("symbol") or "")
    if q == name or q == slug:
        return 1.0
    if symbol and q == symbol:
        return 0.95
    if name.startswith(q) or q.startswith(name):
        return 0.9
    if q in name or name in q:
        return 0.8
    return max(
        SequenceMatcher(None, q, name).ratio(),
        SequenceMatcher(None, q, slug).ratio(),
    )


def _load_map(force: bool = False) -> list[dict]:
    global _MAP_CACHE, _MAP_CACHED_AT
    now = time.time()
    if (
        not force
        and _MAP_CACHE is not None
        and (now - _MAP_CACHED_AT) < _MAP_TTL_SEC
    ):
        return _MAP_CACHE

    @api_retry
    def _call():
        r = httpx.get(f"{_BASE}/currencies/map", headers=_headers(), timeout=60)
        r.raise_for_status()
        return r.json()

    data = _call().get("data") or []
    _MAP_CACHE = data if isinstance(data, list) else []
    _MAP_CACHED_AT = now
    return _MAP_CACHE


def _pick_links(links: list) -> dict:
    """Collapse Cryptorank link array into the fields our enricher expects."""
    by_type: dict[str, list[str]] = {}
    for item in links or []:
        if not isinstance(item, dict):
            continue
        t = (item.get("type") or "").lower().strip()
        url = (item.get("url") or item.get("value") or "").strip()
        if not t or not url:
            continue
        by_type.setdefault(t, []).append(url)

    def first(*types: str) -> str | None:
        for t in types:
            if by_type.get(t):
                return by_type[t][0]
        return None

    docs = first("gitbook", "whitepaper")
    if not docs:
        for t, urls in by_type.items():
            if "doc" in t or "gitbook" in t:
                docs = urls[0]
                break

    return {
        "website": first("web"),
        "github_url": first("github", "gitlab"),
        "twitter_url": first("twitter"),
        "discord_url": first("discord"),
        "docs_url": docs,
        "telegram_url": first("telegram"),
        "medium_url": first("medium"),
        "all_links": [
            {"type": t, "url": u} for t, urls in by_type.items() for u in urls
        ],
    }


class CryptorankLookupInput(BaseModel):
    query: str = Field(
        description="Company / project name (or ticker) to look up on Cryptorank",
    )


class CryptorankTool(BaseTool):
    name: str = "cryptorank_lookup"
    description: str = (
        "Look up a crypto/Web3 project on Cryptorank (Sandbox). Returns description, "
        "lifecycle, and verified links: website, github, twitter, discord, docs/gitbook. "
        "Does NOT return team members or fundraising investors on the free plan — use "
        "web_search / LinkedIn / Twitter for those. Prefer this early for Discord/GitHub/Docs."
    )
    args_schema: type[BaseModel] = CryptorankLookupInput

    def _run(self, query: str) -> str:
        q = (query or "").strip()
        if not q:
            return json.dumps({"found": False, "error": "empty query"})

        try:
            currency_map = _load_map()
        except Exception as e:
            return json.dumps({"found": False, "error": f"map failed: {e}"})

        ranked = sorted(
            (( _score(q, item), item) for item in currency_map),
            key=lambda x: x[0],
            reverse=True,
        )
        best_score, best = ranked[0] if ranked else (0.0, None)
        if not best or best_score < 0.72:
            return json.dumps({
                "found": False,
                "query": q,
                "hint": "No close Cryptorank match — fall back to web_search",
                "candidates": [
                    {
                        "name": i.get("name"),
                        "slug": i.get("slug"),
                        "symbol": i.get("symbol"),
                        "score": round(s, 3),
                    }
                    for s, i in ranked[:5] if s >= 0.5
                ],
            }, ensure_ascii=False)

        cid = best.get("id")

        @api_retry
        def _profile():
            r = httpx.get(
                f"{_BASE}/currencies/{cid}",
                headers=_headers(),
                timeout=30,
            )
            r.raise_for_status()
            return r.json()

        try:
            profile = (_profile().get("data") or {})
        except Exception as e:
            return json.dumps({
                "found": True,
                "id": cid,
                "name": best.get("name"),
                "slug": best.get("slug"),
                "match_score": round(best_score, 3),
                "error": f"profile failed: {e}",
            }, ensure_ascii=False)

        links = _pick_links(profile.get("links") or [])
        out = {
            "found": True,
            "id": profile.get("id", cid),
            "name": profile.get("name") or best.get("name"),
            "slug": profile.get("slug") or best.get("slug"),
            "symbol": profile.get("symbol"),
            "match_score": round(best_score, 3),
            "lifecycle": profile.get("lifecycle"),
            "category": (profile.get("category") or {}).get("name")
            if isinstance(profile.get("category"), dict) else None,
            "tags": [
                t.get("name") for t in (profile.get("tags") or [])
                if isinstance(t, dict) and t.get("name")
            ],
            "description": profile.get("description"),
            "listing_date": profile.get("listingDate"),
            "cryptorank_url": f"https://cryptorank.io/price/{profile.get('slug') or best.get('slug')}",
            **{k: v for k, v in links.items() if k != "all_links"},
            "all_links": links["all_links"],
            "note": (
                "Sandbox plan: links + description only. "
                "Team socials / funding investors are NOT in this response."
            ),
        }
        return json.dumps(out, ensure_ascii=False, indent=2)
