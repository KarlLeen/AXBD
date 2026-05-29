"""CoinGecko API tool — verify crypto project listing status."""
import json
import os
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
import httpx

from athenax.tools._retry import api_retry

_BASE = "https://api.coingecko.com/api/v3"


def _headers() -> dict:
    key = os.getenv("COINGECKO_API_KEY", "")
    return {"x-cg-demo-api-key": key} if key else {}


class CoinGeckoSearchInput(BaseModel):
    query: str = Field(description="Project or token name to search on CoinGecko")


class CoinGeckoTool(BaseTool):
    name: str = "coingecko_search"
    description: str = (
        "Check whether a crypto project is listed on CoinGecko. "
        "Returns market cap rank, current price, and 24h change if found. "
        "Use this to verify 'established' crypto projects before scoring them."
    )
    args_schema: type[BaseModel] = CoinGeckoSearchInput

    def _run(self, query: str) -> str:
        @api_retry
        def _search():
            r = httpx.get(
                f"{_BASE}/search",
                headers=_headers(),
                params={"query": query},
                timeout=15,
            )
            r.raise_for_status()
            return r.json()

        data = _search()
        coins = data.get("coins", [])[:3]

        if not coins:
            return json.dumps({"listed": False, "query": query})

        results = []
        for coin in coins:
            market_data = self._get_market_data(coin["id"])
            results.append({
                "listed": True,
                "id": coin["id"],
                "name": coin["name"],
                "symbol": coin["symbol"].upper(),
                "market_cap_rank": market_data.get("market_cap_rank"),
                "current_price_usd": market_data.get("current_price", {}).get("usd"),
                "price_change_24h_pct": market_data.get("price_change_percentage_24h"),
                "coingecko_url": f"https://www.coingecko.com/en/coins/{coin['id']}",
            })

        return json.dumps(results, ensure_ascii=False, indent=2)

    def _get_market_data(self, coin_id: str) -> dict:
        try:
            @api_retry
            def _fetch():
                r = httpx.get(
                    f"{_BASE}/coins/{coin_id}",
                    headers=_headers(),
                    params={"localization": "false", "tickers": "false",
                            "community_data": "false", "developer_data": "false"},
                    timeout=15,
                )
                r.raise_for_status()
                return r.json()

            data = _fetch()
            return {
                "market_cap_rank": data.get("market_cap_rank"),
                "current_price": data.get("market_data", {}).get("current_price", {}),
                "price_change_percentage_24h": data.get("market_data", {})
                    .get("price_change_percentage_24h"),
            }
        except Exception:
            return {}
