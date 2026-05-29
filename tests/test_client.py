"""Unit tests for AthenaXClient — all methods, auth, error paths."""
import json
import pytest
import httpx
from unittest.mock import patch, MagicMock


def _mock_post(status: int, body: dict):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    m.raise_for_status = MagicMock() if status < 400 else MagicMock(
        side_effect=httpx.HTTPStatusError(
            str(status),
            request=httpx.Request("POST", "http://x"),
            response=httpx.Response(status),
        )
    )
    return m


def _mock_get(status: int, body):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    m.raise_for_status = MagicMock() if status < 400 else MagicMock(
        side_effect=httpx.HTTPStatusError(
            str(status),
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(status),
        )
    )
    return m


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ATHENAX_API_URL", "http://mock")
    monkeypatch.setenv("ATHENAX_API_KEY", "")
    # Re-import so env vars take effect
    import importlib, athenax.api.athenax_client as mod
    importlib.reload(mod)
    return mod.AthenaXClient()


LEAD_DATA = {
    "name": "Test Project",
    "url": "https://example.com",
    "source": "github",
    "compatibility_score": 85,
    "reason_for_partnership": "Strong alignment",
    "nounish_traits": '["CC0"]',
    "tech_stack": '["Solidity"]',
}


# ── push_lead ─────────────────────────────────────────────────────────────────

class TestPushLead:
    def test_returns_lead_id(self, client):
        with patch("httpx.post", return_value=_mock_post(201, {"lead_id": "abc-123"})):
            result = client.push_lead(LEAD_DATA)
        assert result == "abc-123"

    def test_payload_structure(self, client):
        with patch("httpx.post") as mock:
            mock.return_value = _mock_post(201, {"lead_id": "x"})
            client.push_lead(LEAD_DATA)
            payload = mock.call_args.kwargs["json"]
        assert payload["name"] == "Test Project"
        assert payload["compatibility_score"] == 85
        assert isinstance(payload["nounish_traits"], list)
        assert "submitted_at" in payload

    def test_raises_on_4xx(self, client):
        with patch("httpx.post", return_value=_mock_post(401, {})):
            with pytest.raises(httpx.HTTPStatusError):
                client.push_lead(LEAD_DATA)


# ── push_draft ────────────────────────────────────────────────────────────────

class TestPushDraft:
    def test_returns_outreach_id(self, client):
        with patch("httpx.post", return_value=_mock_post(201, {"outreach_id": "draft-1"})):
            result = client.push_draft(
                {"channel": "twitter_dm", "body": "Hey!", "lead_name": "X", "compatibility_score": 80},
                "lead-uuid",
            )
        assert result == "draft-1"

    def test_status_is_pending(self, client):
        with patch("httpx.post") as mock:
            mock.return_value = _mock_post(201, {"outreach_id": "x"})
            client.push_draft({"channel": "email", "body": "Hi"}, "lead-id")
            payload = mock.call_args.kwargs["json"]
        assert payload["status"] == "pending"

    def test_lead_id_passed_correctly(self, client):
        with patch("httpx.post") as mock:
            mock.return_value = _mock_post(201, {"outreach_id": "x"})
            client.push_draft({"channel": "twitter_dm", "body": "Hi"}, "my-lead-uuid")
            payload = mock.call_args.kwargs["json"]
        assert payload["lead_id"] == "my-lead-uuid"


# ── push_outreach (approved) ──────────────────────────────────────────────────

class TestPushOutreach:
    def test_returns_outreach_id(self, client):
        with patch("httpx.post", return_value=_mock_post(201, {"outreach_id": "o-1"})):
            result = client.push_outreach(
                {"channel": "email", "subject": "Hello", "body": "Body"},
                "lead-id",
                "2026-01-01T00:00:00Z",
            )
        assert result == "o-1"

    def test_status_is_approved(self, client):
        with patch("httpx.post") as mock:
            mock.return_value = _mock_post(201, {"outreach_id": "x"})
            client.push_outreach({"channel": "email", "body": "B"}, "lid", "2026-01-01Z")
            assert mock.call_args.kwargs["json"]["status"] == "approved"


# ── patch_outreach_status ─────────────────────────────────────────────────────

class TestPatchOutreachStatus:
    def test_approve(self, client):
        updated = {"outreach_id": "x", "status": "approved", "approved_at": "2026-01-01Z"}
        with patch("httpx.patch", return_value=_mock_get(200, updated)):
            result = client.patch_outreach_status("x", "approved")
        assert result["status"] == "approved"

    def test_reject(self, client):
        updated = {"outreach_id": "x", "status": "rejected"}
        with patch("httpx.patch", return_value=_mock_get(200, updated)):
            result = client.patch_outreach_status("x", "rejected")
        assert result["status"] == "rejected"

    def test_raises_on_404(self, client):
        with patch("httpx.patch", return_value=_mock_get(404, {})):
            with pytest.raises(httpx.HTTPStatusError):
                client.patch_outreach_status("bad-id", "approved")


# ── get_pending_outreach ──────────────────────────────────────────────────────

class TestGetPendingOutreach:
    def test_returns_list(self, client):
        pending = [{"outreach_id": "a", "status": "pending"}, {"outreach_id": "b", "status": "pending"}]
        with patch("httpx.get", return_value=_mock_get(200, pending)):
            result = client.get_pending_outreach()
        assert len(result) == 2

    def test_empty_list(self, client):
        with patch("httpx.get", return_value=_mock_get(200, [])):
            result = client.get_pending_outreach()
        assert result == []

    def test_calls_correct_endpoint(self, client):
        with patch("httpx.get") as mock:
            mock.return_value = _mock_get(200, [])
            client.get_pending_outreach()
            url = mock.call_args.args[0]
            params = mock.call_args.kwargs.get("params", {})
        assert "/api/v1/outreach" in url
        assert params.get("status") == "pending"


# ── get_lead ──────────────────────────────────────────────────────────────────

class TestGetLead:
    def test_returns_lead_dict(self, client):
        lead = {"lead_id": "abc", "name": "Test", "url": "https://x.com"}
        with patch("httpx.get", return_value=_mock_get(200, lead)):
            result = client.get_lead("abc")
        assert result["lead_id"] == "abc"

    def test_raises_on_404(self, client):
        with patch("httpx.get", return_value=_mock_get(404, {})):
            with pytest.raises(httpx.HTTPStatusError):
                client.get_lead("bad")
