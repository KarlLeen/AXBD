"""Twitter / X API v2 tool — real-time social signals."""
import json
import os
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import httpx

from athenax.tools._retry import api_retry


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
        bearer = os.getenv("TWITTER_BEARER_TOKEN", "")
        if not bearer:
            raise ValueError("TWITTER_BEARER_TOKEN not set")

        query = " OR ".join(hashtags) + " -is:retweet lang:en"
        params = {
            "query": query,
            "max_results": max_results,
            "tweet.fields": "created_at,public_metrics,author_id,text",
            "user.fields": "username,name,public_metrics,description,url",
            "expansions": "author_id",
        }

        @api_retry
        def _call():
            r = httpx.get(
                "https://api.twitter.com/2/tweets/search/recent",
                headers={"Authorization": f"Bearer {bearer}"},
                params=params,
                timeout=15,
            )
            r.raise_for_status()
            return r.json()

        data = _call()

        users_by_id = {
            u["id"]: u for u in data.get("includes", {}).get("users", [])
        }

        results = []
        for tweet in data.get("data", []):
            author = users_by_id.get(tweet["author_id"], {})
            user_metrics = author.get("public_metrics", {})
            tweet_metrics = tweet.get("public_metrics", {})
            results.append({
                "source": "twitter",
                "twitter_handle": author.get("username", ""),
                "name": author.get("name", ""),
                "description": author.get("description", ""),
                "twitter_followers": user_metrics.get("followers_count", 0),
                "twitter_recent_tweet": tweet["text"],
                "likes": tweet_metrics.get("like_count", 0),
                "retweets": tweet_metrics.get("retweet_count", 0),
                "created_at": tweet.get("created_at", ""),
                "url": f"https://twitter.com/{author.get('username', '')}/status/{tweet['id']}",
            })

        return json.dumps(results, ensure_ascii=False, indent=2)
