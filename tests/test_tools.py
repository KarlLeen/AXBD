"""Unit tests for tool response parsing (no real API calls)."""
import json
import pytest
from unittest.mock import patch, MagicMock


class TestGitHubToolParsing:
    def _make_repo(self, name="test/repo", stars=500, language="Python"):
        return {
            "full_name": name,
            "html_url": f"https://github.com/{name}",
            "description": "A test repo",
            "stargazers_count": stars,
            "forks_count": 50,
            "language": language,
            "topics": ["web3", "dao"],
            "homepage": "",
            "pushed_at": "2026-05-01T00:00:00Z",
        }

    def test_parses_repo_fields(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        from athenax.tools.github_tool import GitHubTool

        tool = GitHubTool()
        fake_response = {"items": [self._make_repo()]}

        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: fake_response,
                raise_for_status=lambda: None,
            )
            with patch.object(tool, "_commits_last_30d", return_value=42):
                result = json.loads(tool._run(["DAO"], 50, 1))

        assert len(result) == 1
        assert result[0]["github_stars"] == 500
        assert result[0]["commits_last_30d"] == 42
        assert result[0]["source"] == "github"

    def test_empty_results(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake")
        from athenax.tools.github_tool import GitHubTool

        tool = GitHubTool()
        with patch("httpx.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200,
                json=lambda: {"items": []},
                raise_for_status=lambda: None,
            )
            result = json.loads(tool._run(["DAO"], 50, 1))
        assert result == []


class TestSerperToolParsing:
    def test_parses_organic_results(self, monkeypatch):
        monkeypatch.setenv("SERPER_API_KEY", "fake")
        from athenax.tools.serper_tool import SerperTool

        tool = SerperTool()
        fake = {
            "organic": [
                {"title": "Test", "link": "https://test.com",
                 "snippet": "A snippet", "position": 1}
            ]
        }
        with patch("httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: fake,
                raise_for_status=lambda: None,
            )
            result = json.loads(tool._run("DAO tooling", 1))

        assert result[0]["title"] == "Test"
        assert result[0]["url"] == "https://test.com"


class TestRetryLogic:
    def test_retryable_status_codes(self):
        from athenax.tools._retry import _is_retryable
        import httpx

        for code in [429, 500, 502, 503, 504]:
            exc = httpx.HTTPStatusError(
                str(code),
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(code),
            )
            assert _is_retryable(exc), f"{code} should be retryable"

    def test_non_retryable_400(self):
        from athenax.tools._retry import _is_retryable
        import httpx

        exc = httpx.HTTPStatusError(
            "400",
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(400),
        )
        assert not _is_retryable(exc)

    def test_timeout_is_retryable(self):
        from athenax.tools._retry import _is_retryable
        import httpx

        assert _is_retryable(httpx.TimeoutException("timeout"))
