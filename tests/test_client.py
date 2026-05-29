"""Unit tests for AthenaXClient using httpx mock transport."""
import json
import pytest
import httpx
from unittest.mock import patch


def _mock_transport(status: int, body: dict):
    def handler(request):
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ATHENAX_API_URL", "http://mock")
    monkeypatch.setenv("ATHENAX_API_KEY", "")
    from athenax.api.athenax_client import AthenaXClient
    return AthenaXClient()


class TestPushLead:
    def test_returns_lead_id(self, client, monkeypatch):
        transport = _mock_transport(201, {"lead_id": "abc-123"})
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: httpx.Client(transport=transport).post(*a, **kw))

        from athenax.api.athenax_client import AthenaXClient
        import httpx as _httpx

        with _httpx.Client(transport=transport) as c:
            resp = c.post("http://mock/api/v1/leads", json={})
            assert resp.json()["lead_id"] == "abc-123"

    def test_raises_on_404(self, client):
        def handler(request):
            return httpx.Response(404, json={"detail": "not found"})

        with patch("httpx.post", side_effect=lambda *a, **kw: (_ for _ in ()).throw(
            httpx.HTTPStatusError("404", request=httpx.Request("POST", "http://x"),
                                  response=httpx.Response(404))
        )):
            with pytest.raises(httpx.HTTPStatusError):
                client.push_lead({
                    "name": "x", "url": "http://x.com", "source": "github",
                    "compatibility_score": 80, "reason_for_partnership": "y",
                })


class TestGetPendingOutreach:
    def test_filters_by_status(self, monkeypatch):
        monkeypatch.setenv("ATHENAX_API_URL", "http://mock")
        monkeypatch.setenv("ATHENAX_API_KEY", "")

        pending = [{"outreach_id": "x", "status": "pending"}]
        transport = _mock_transport(200, pending)

        with httpx.Client(transport=transport) as c:
            resp = c.get("http://mock/api/v1/outreach", params={"status": "pending"})
            assert resp.json() == pending
