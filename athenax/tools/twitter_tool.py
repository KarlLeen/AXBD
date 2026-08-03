"""Twitter / X API v2 tools — social signals + profile lookup."""
import json
import os
import re
import threading
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import httpx

from athenax.tools._retry import api_retry

# Process-wide circuit breaker: X API credits-depleted (402) doesn't recover
# mid-run, so once we see it a couple of times, stop burning agent iterations
# retrying every company — short-circuit immediately instead.
_LOCK = threading.Lock()
_CONSECUTIVE_DEPLETED = 0
_DEPLETED_THRESHOLD = 2


def _circuit_tripped() -> bool:
    return _CONSECUTIVE_DEPLETED >= _DEPLETED_THRESHOLD


def _note_result(depleted: bool) -> None:
    global _CONSECUTIVE_DEPLETED
    with _LOCK:
        _CONSECUTIVE_DEPLETED = _CONSECUTIVE_DEPLETED + 1 if depleted else 0


def _circuit_error() -> str:
    return json.dumps({
        "error": "Twitter/X API credits depleted — do not retry any Twitter tool this run.",
        "hint": "Use web_search/cryptorank_lookup/linkedin tools instead.",
    })


def _bearer() -> str:
    token = os.getenv("TWITTER_BEARER_TOKEN", "")
    if not token:
        raise ValueError("TWITTER_BEARER_TOKEN not set")
    return token


def _normalize_username(username: str) -> str:
    u = (username or "").strip()
    u = re.sub(r"^https?://(www\.)?(twitter|x)\.com/", "", u, flags=re.I)
    u = u.split("/")[0].split("?")[0].lstrip("@")
    return u.strip()


def _search_recent(query: str, max_results: int = 20) -> list[dict]:
    params = {
        "query": query,
        "max_results": max(10, min(max_results, 100)),
        "tweet.fields": "created_at,public_metrics,author_id,text",
        "user.fields": "username,name,public_metrics,description,url",
        "expansions": "author_id",
    }

    @api_retry
    def _call():
        r = httpx.get(
            "https://api.twitter.com/2/tweets/search/recent",
            headers={"Authorization": f"Bearer {_bearer()}"},
            params=params,
            timeout=15,
        )
        r.raise_for_status()
        return r.json()

    try:
        data = _call()
    except httpx.HTTPStatusError as e:
        _note_result(e.response.status_code == 402)
        raise
    _note_result(False)
    users_by_id = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
    results = []
    for tweet in data.get("data", []):
        author = users_by_id.get(tweet["author_id"], {})
        user_metrics = author.get("public_metrics", {})
        tweet_metrics = tweet.get("public_metrics", {})
        handle = author.get("username", "")
        results.append({
            "source": "twitter",
            "twitter_handle": handle,
            "name": author.get("name", ""),
            "description": author.get("description", ""),
            "twitter_followers": user_metrics.get("followers_count", 0),
            "twitter_recent_tweet": tweet["text"],
            "likes": tweet_metrics.get("like_count", 0),
            "retweets": tweet_metrics.get("retweet_count", 0),
            "created_at": tweet.get("created_at", ""),
            "url": f"https://x.com/{handle}/status/{tweet['id']}" if handle else "",
        })
    return results


class TwitterSearchInput(BaseModel):
    hashtags: list[str] = Field(
        default=["#Web3", "#BuildInPublic", "#NFT", "#DAO"],
        description="Hashtags to search (include the #)",
    )
    max_results: int = Field(default=20, ge=10, le=100, description="Number of tweets (10–100)")


class TwitterTool(BaseTool):
    name: str = "twitter_search"
    description: str = (
        "Search Twitter/X for recent tweets matching Web3/DAO hashtags. "
        "Returns tweet text, author handle, follower count, and engagement metrics."
    )
    args_schema: type[BaseModel] = TwitterSearchInput

    def _run(self, hashtags: list[str], max_results: int = 20) -> str:
        if _circuit_tripped():
            return _circuit_error()
        query = " OR ".join(hashtags) + " -is:retweet lang:en"
        return json.dumps(_search_recent(query, max_results), ensure_ascii=False, indent=2)


class TwitterUserLookupInput(BaseModel):
    username: str = Field(
        ...,
        description="Twitter/X username or profile URL (with or without @)",
    )
    max_tweets: int = Field(
        default=10, ge=1, le=20,
        description="How many recent tweets to include from this user",
    )


class TwitterUserTool(BaseTool):
    name: str = "twitter_user_lookup"
    description: str = (
        "Look up a Twitter/X user by username/URL. Returns profile bio, website URL, "
        "follower count, location, and their recent tweets — useful for finding team "
        "mentions, Discord/docs links in the bio, founding year, and funding announcements."
    )
    args_schema: type[BaseModel] = TwitterUserLookupInput

    def _run(self, username: str, max_tweets: int = 10) -> str:
        if _circuit_tripped():
            return _circuit_error()
        handle = _normalize_username(username)
        if not handle:
            return json.dumps({"error": "empty username"})

        @api_retry
        def _user():
            r = httpx.get(
                f"https://api.twitter.com/2/users/by/username/{handle}",
                headers={"Authorization": f"Bearer {_bearer()}"},
                params={
                    "user.fields": (
                        "created_at,description,location,name,public_metrics,"
                        "url,verified,verified_type,entities"
                    ),
                },
                timeout=15,
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json().get("data")

        try:
            user = _user()
        except httpx.HTTPStatusError as e:
            _note_result(e.response.status_code == 402)
            raise
        _note_result(False)
        if not user:
            return json.dumps({"error": f"user @{handle} not found"})

        metrics = user.get("public_metrics") or {}
        profile = {
            "username": user.get("username", handle),
            "name": user.get("name", ""),
            "description": user.get("description", ""),
            "url": user.get("url", ""),
            "location": user.get("location", ""),
            "created_at": user.get("created_at", ""),
            "verified": user.get("verified", False),
            "followers": metrics.get("followers_count", 0),
            "following": metrics.get("following_count", 0),
            "tweet_count": metrics.get("tweet_count", 0),
            "profile_url": f"https://x.com/{user.get('username', handle)}",
        }

        # Expanded URLs from bio entities (Discord/docs often live here)
        urls = []
        for u in (user.get("entities") or {}).get("url", {}).get("urls", []) or []:
            if u.get("expanded_url"):
                urls.append(u["expanded_url"])
        for u in (user.get("entities") or {}).get("description", {}).get("urls", []) or []:
            if u.get("expanded_url"):
                urls.append(u["expanded_url"])
        profile["expanded_urls"] = urls

        tweets = []
        uid = user.get("id")
        if uid:
            @api_retry
            def _tweets():
                r = httpx.get(
                    f"https://api.twitter.com/2/users/{uid}/tweets",
                    headers={"Authorization": f"Bearer {_bearer()}"},
                    params={
                        "max_results": max(5, min(max_tweets, 20)),
                        "exclude": "retweets,replies",
                        "tweet.fields": "created_at,public_metrics,text",
                    },
                    timeout=15,
                )
                if r.status_code in (404, 401):
                    return []
                r.raise_for_status()
                return r.json().get("data") or []

            try:
                for t in _tweets():
                    m = t.get("public_metrics") or {}
                    tweets.append({
                        "text": t.get("text", ""),
                        "created_at": t.get("created_at", ""),
                        "likes": m.get("like_count", 0),
                        "retweets": m.get("retweet_count", 0),
                        "url": f"https://x.com/{profile['username']}/status/{t['id']}",
                    })
            except Exception as e:
                tweets = [{"error": str(e)}]

        return json.dumps({"profile": profile, "recent_tweets": tweets},
                          ensure_ascii=False, indent=2)


class TwitterQueryInput(BaseModel):
    query: str = Field(
        ...,
        description=(
            "Twitter recent-search query. Examples: "
            "'from:xmtp_ (funding OR raised OR founder)', "
            "'\"Compass Labs\" (seed OR series OR backed)'"
        ),
    )
    max_results: int = Field(default=20, ge=10, le=100)


class TwitterQueryTool(BaseTool):
    name: str = "twitter_query"
    description: str = (
        "Run a free-form Twitter/X recent-search query (last ~7 days). "
        "Use to find funding announcements, founder intros, Discord invites, "
        "or team shout-outs related to a company."
    )
    args_schema: type[BaseModel] = TwitterQueryInput

    def _run(self, query: str, max_results: int = 20) -> str:
        if _circuit_tripped():
            return _circuit_error()
        q = (query or "").strip()
        if " -is:retweet" not in q:
            q = f"{q} -is:retweet"
        return json.dumps(_search_recent(q, max_results), ensure_ascii=False, indent=2)
