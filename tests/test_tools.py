"""Unit tests for all tool response parsers — no real API calls."""
import json
import pytest
from unittest.mock import patch, MagicMock


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_resp(status: int, data):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = data
    if status >= 400:
        import httpx
        m.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status), request=httpx.Request("GET", "http://x"), response=httpx.Response(status)
        )
    else:
        m.raise_for_status = MagicMock()
    return m


# ── GitHub ────────────────────────────────────────────────────────────────────

class TestGitHubTool:
    def _repo(self, name="test/repo", stars=500, lang="Python"):
        return {
            "full_name": name, "html_url": f"https://github.com/{name}",
            "description": "Test", "stargazers_count": stars,
            "forks_count": 50, "language": lang,
            "topics": ["web3"], "homepage": "", "pushed_at": "2026-05-01T00:00:00Z",
        }

    def test_parses_basic_fields(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        from athenax.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch("httpx.get", return_value=_mock_resp(200, {"items": [self._repo()]})):
            with patch.object(tool, "_commits_last_30d", return_value=25):
                result = json.loads(tool._run(["DAO"], 50, 1))
        assert result[0]["github_stars"] == 500
        assert result[0]["source"] == "github"
        assert result[0]["commits_last_30d"] == 25

    def test_empty_search_returns_empty_list(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        from athenax.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch("httpx.get", return_value=_mock_resp(200, {"items": []})):
            result = json.loads(tool._run(["DAO"], 50, 1))
        assert result == []

    def test_tech_stack_from_language(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        from athenax.tools.github_tool import GitHubTool
        tool = GitHubTool()
        with patch("httpx.get", return_value=_mock_resp(200, {"items": [self._repo(lang="Rust")]})):
            with patch.object(tool, "_commits_last_30d", return_value=0):
                result = json.loads(tool._run(["test"], 0, 1))
        assert result[0]["tech_stack"] == ["Rust"]

    def test_commits_last_30d_counts_correctly(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        from athenax.tools.github_tool import GitHubTool
        tool = GitHubTool()
        fake_commits = [{"sha": f"abc{i}"} for i in range(37)]
        with patch("httpx.get", return_value=_mock_resp(200, fake_commits)):
            count = tool._commits_last_30d("owner/repo", {})
        assert count == 37

    def test_commits_empty_repo_returns_zero(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        from athenax.tools.github_tool import GitHubTool
        tool = GitHubTool()
        m = MagicMock()
        m.status_code = 409
        m.raise_for_status = MagicMock()
        with patch("httpx.get", return_value=m):
            count = tool._commits_last_30d("owner/repo", {})
        assert count == 0

    def test_commits_api_failure_returns_none(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        from athenax.tools.github_tool import GitHubTool
        import httpx
        tool = GitHubTool()
        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            count = tool._commits_last_30d("owner/repo", {})
        assert count is None


# ── Serper ────────────────────────────────────────────────────────────────────

class TestSerperTool:
    def test_parses_organic_results(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "fake")
        from athenax.tools.serper_tool import SerperTool
        tool = SerperTool()
        fake = {"organic": [
            {"title": "Test", "link": "https://test.com", "snippet": "Snippet", "position": 1}
        ]}
        with patch("httpx.post", return_value=_mock_resp(200, fake)):
            result = json.loads(tool._run("DAO tooling", 1))
        assert result[0]["title"] == "Test"
        assert result[0]["url"] == "https://test.com"

    def test_includes_knowledge_graph(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "fake")
        from athenax.tools.serper_tool import SerperTool
        tool = SerperTool()
        fake = {
            "organic": [],
            "knowledgeGraph": {"title": "Ethereum", "description": "A blockchain", "website": "https://ethereum.org"},
        }
        with patch("httpx.post", return_value=_mock_resp(200, fake)):
            result = json.loads(tool._run("Ethereum", 1))
        assert result[0]["type"] == "knowledge_graph"
        assert result[0]["title"] == "Ethereum"

    def test_empty_results(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "fake")
        from athenax.tools.serper_tool import SerperTool
        with patch("httpx.post", return_value=_mock_resp(200, {"organic": []})):
            result = json.loads(SerperTool()._run("xyz"))
        assert result == []


# ── Twitter ───────────────────────────────────────────────────────────────────

class TestTwitterTool:
    def _fake_response(self):
        return {
            "data": [{
                "id": "123", "text": "Building a DAO #Web3",
                "author_id": "u1", "created_at": "2026-05-01T10:00:00Z",
                "public_metrics": {"like_count": 5, "retweet_count": 2},
            }],
            "includes": {"users": [{
                "id": "u1", "username": "builder_xyz", "name": "Builder XYZ",
                "description": "Building in public",
                "public_metrics": {"followers_count": 3200},
            }]},
        }

    def test_parses_tweet_and_author(self, monkeypatch):
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "fake")
        from athenax.tools.twitter_tool import TwitterTool
        with patch("httpx.get", return_value=_mock_resp(200, self._fake_response())):
            result = json.loads(TwitterTool()._run(["#DAO"], 10))
        assert result[0]["twitter_handle"] == "builder_xyz"
        assert result[0]["twitter_followers"] == 3200
        assert result[0]["source"] == "twitter"
        assert "#Web3" in result[0]["twitter_recent_tweet"]

    def test_empty_response(self, monkeypatch):
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "fake")
        from athenax.tools.twitter_tool import TwitterTool
        with patch("httpx.get", return_value=_mock_resp(200, {"data": [], "includes": {}})):
            result = json.loads(TwitterTool()._run(["#DAO"], 10))
        assert result == []

    def test_missing_bearer_raises(self, monkeypatch):
        monkeypatch.setenv("TWITTER_BEARER_TOKEN", "")
        from athenax.tools.twitter_tool import TwitterTool
        with pytest.raises(ValueError, match="TWITTER_BEARER_TOKEN"):
            TwitterTool()._run(["#DAO"], 10)


# ── LinkedIn ──────────────────────────────────────────────────────────────────

class TestLinkedInTools:
    def test_people_search_parses_correctly(self, monkeypatch):
        monkeypatch.setenv("CONNECTSAFELY_API_KEY", "fake")
        from athenax.tools.linkedin_tool import LinkedInPeopleSearchTool
        fake = {"people": [{"firstName": "Alice", "lastName": "DAO",
                             "headline": "Web3 builder", "profileUrl": "https://linkedin.com/in/alice",
                             "location": "SF", "currentCompany": "DAOlab"}]}
        with patch("httpx.post", return_value=_mock_resp(200, fake)):
            result = json.loads(LinkedInPeopleSearchTool()._run("DAO founder"))
        assert result[0]["name"] == "Alice DAO"
        assert result[0]["source"] == "linkedin"

    def test_company_search_parses_correctly(self, monkeypatch):
        monkeypatch.setenv("CONNECTSAFELY_API_KEY", "fake")
        from athenax.tools.linkedin_tool import LinkedInCompanySearchTool
        fake = {"companies": [{"name": "DAO Labs", "universalName": "daolabs",
                                "description": "Building DAO tooling"}]}
        with patch("httpx.post", return_value=_mock_resp(200, fake)):
            result = json.loads(LinkedInCompanySearchTool()._run("DAO tooling"))
        assert result[0]["name"] == "DAO Labs"
        assert "daolabs" in result[0]["linkedin_profile"]

    def test_post_search_parses_author(self, monkeypatch):
        monkeypatch.setenv("CONNECTSAFELY_API_KEY", "fake")
        from athenax.tools.linkedin_tool import LinkedInPostSearchTool
        fake = {"posts": [{"text": "DAO is the future", "url": "https://linkedin.com/post/1",
                            "author": {"name": "Bob Builder", "profileUrl": "https://linkedin.com/in/bob"},
                            "likes": 42, "comments": 3}]}
        with patch("httpx.post", return_value=_mock_resp(200, fake)):
            result = json.loads(LinkedInPostSearchTool()._run("DAO"))
        assert result[0]["name"] == "Bob Builder"
        assert result[0]["linkedin_recent_post"] == "DAO is the future"
        assert result[0]["likes"] == 42

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.setenv("CONNECTSAFELY_API_KEY", "")
        from athenax.tools.linkedin_tool import LinkedInPostSearchTool, _headers
        with pytest.raises(ValueError, match="CONNECTSAFELY_API_KEY"):
            _headers()


# ── CoinGecko ─────────────────────────────────────────────────────────────────

class TestCoinGeckoTool:
    def _fake_search(self):
        return {"coins": [{"id": "ethereum", "name": "Ethereum", "symbol": "eth"}]}

    def _fake_coin(self):
        return {
            "market_cap_rank": 2,
            "market_data": {
                "current_price": {"usd": 3500.0},
                "price_change_percentage_24h": 1.5,
            },
        }

    def test_found_coin_returns_listed_true(self, monkeypatch):
        monkeypatch.setenv("COINGECKO_API_KEY", "fake")
        from athenax.tools.coingecko_tool import CoinGeckoTool
        tool = CoinGeckoTool()
        with patch("httpx.get") as mock:
            mock.side_effect = [
                _mock_resp(200, self._fake_search()),
                _mock_resp(200, self._fake_coin()),
            ]
            result = json.loads(tool._run("ethereum"))
        assert result[0]["listed"] is True
        assert result[0]["name"] == "Ethereum"
        assert result[0]["market_cap_rank"] == 2

    def test_not_found_returns_listed_false(self, monkeypatch):
        monkeypatch.setenv("COINGECKO_API_KEY", "fake")
        from athenax.tools.coingecko_tool import CoinGeckoTool
        tool = CoinGeckoTool()
        with patch("httpx.get", return_value=_mock_resp(200, {"coins": []})):
            result = json.loads(tool._run("unknownxyz"))
        assert result["listed"] is False

    def test_market_data_failure_still_returns_coin(self, monkeypatch):
        monkeypatch.setenv("COINGECKO_API_KEY", "fake")
        from athenax.tools.coingecko_tool import CoinGeckoTool
        import httpx
        tool = CoinGeckoTool()
        with patch("httpx.get") as mock:
            mock.side_effect = [
                _mock_resp(200, self._fake_search()),
                httpx.TimeoutException("timeout"),
            ]
            result = json.loads(tool._run("ethereum"))
        assert result[0]["listed"] is True
        assert result[0]["market_cap_rank"] is None


# ── Retry logic ───────────────────────────────────────────────────────────────

class TestRetryLogic:
    @pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
    def test_retryable_status_codes(self, code):
        from athenax.tools._retry import _is_retryable
        import httpx
        exc = httpx.HTTPStatusError(
            str(code), request=httpx.Request("GET", "http://x"), response=httpx.Response(code)
        )
        assert _is_retryable(exc)

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_non_retryable_4xx(self, code):
        from athenax.tools._retry import _is_retryable
        import httpx
        exc = httpx.HTTPStatusError(
            str(code), request=httpx.Request("GET", "http://x"), response=httpx.Response(code)
        )
        assert not _is_retryable(exc)

    def test_timeout_is_retryable(self):
        from athenax.tools._retry import _is_retryable
        import httpx
        assert _is_retryable(httpx.TimeoutException("t/o"))

    def test_connect_error_is_retryable(self):
        from athenax.tools._retry import _is_retryable
        import httpx
        assert _is_retryable(httpx.ConnectError("refused"))

    def test_value_error_is_not_retryable(self):
        from athenax.tools._retry import _is_retryable
        assert not _is_retryable(ValueError("bad input"))
