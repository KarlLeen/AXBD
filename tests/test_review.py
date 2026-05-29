"""Unit tests for CLI review loop helpers."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    import athenax.db.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    db_mod.init_db()
    return db_mod


def _insert_lead_and_draft(tmp_db):
    """Insert a lead + eval + draft, return draft row as dict."""
    import uuid
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    lead_id = str(uuid.uuid4())
    eval_id = str(uuid.uuid4())
    draft_id = str(uuid.uuid4())
    unique_url = f"https://example.com/{lead_id}"  # unique per call to avoid UNIQUE constraint

    with tmp_db.get_connection() as conn:
        conn.execute("""INSERT INTO leads
            (id, source, name, url, description, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?)""",
            (lead_id, "github", "Test Lead", unique_url, "desc", now, now))
        conn.execute("""INSERT INTO evaluations
            (id, lead_id, compatibility_score, reason_for_partnership, created_at)
            VALUES (?,?,?,?,?)""",
            (eval_id, lead_id, 85, "Great fit", now))
        conn.execute("""INSERT INTO outreach_drafts
            (id, lead_id, evaluation_id, channel, body, status, created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (draft_id, lead_id, eval_id, "twitter_dm", "Hey!", "pending", now))
        conn.commit()

    return {
        "id": draft_id, "lead_id": lead_id, "evaluation_id": eval_id,
        "channel": "twitter_dm", "subject": None, "body": "Hey!",
        "lead_name": "Test Lead", "lead_url": unique_url,
        "lead_source": "github", "tech_stack": None,
        "twitter_handle": "builder_xyz", "remote_lead_id": None,
        "compatibility_score": 85, "nounish_traits": '["CC0"]',
        "reason_for_partnership": "Great fit", "listing_fit_notes": "",
    }


# ── _reject ───────────────────────────────────────────────────────────────────

class TestReject:
    def test_reject_sets_status_rejected(self, tmp_db, monkeypatch):
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        from athenax.cli.review import _reject
        draft = _insert_lead_and_draft(tmp_db)
        _reject(draft["id"])
        with tmp_db.get_connection() as conn:
            status = conn.execute(
                "SELECT status FROM outreach_drafts WHERE id=?", (draft["id"],)
            ).fetchone()[0]
        assert status == "rejected"

    def test_reject_does_not_affect_other_drafts(self, tmp_db, monkeypatch):
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        from athenax.cli.review import _reject
        d1 = _insert_lead_and_draft(tmp_db)
        d2 = _insert_lead_and_draft(tmp_db)
        _reject(d1["id"])
        with tmp_db.get_connection() as conn:
            status2 = conn.execute(
                "SELECT status FROM outreach_drafts WHERE id=?", (d2["id"],)
            ).fetchone()[0]
        assert status2 == "pending"


# ── _approve ──────────────────────────────────────────────────────────────────

class TestApprove:
    def test_approve_marks_approved_in_db(self, tmp_db, monkeypatch):
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        from athenax.cli.review import _approve
        from athenax.api.athenax_client import AthenaXClient

        draft = _insert_lead_and_draft(tmp_db)
        mock_client = MagicMock(spec=AthenaXClient)
        mock_client.push_lead.return_value = "remote-lead-id"
        mock_client.push_outreach.return_value = "remote-outreach-id"

        _approve(draft, mock_client)

        with tmp_db.get_connection() as conn:
            row = conn.execute(
                "SELECT status, approved_at FROM outreach_drafts WHERE id=?",
                (draft["id"],)
            ).fetchone()
        assert row[0] == "approved"
        assert row[1] is not None

    def test_approve_stores_remote_lead_id(self, tmp_db, monkeypatch):
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        from athenax.cli.review import _approve
        from athenax.api.athenax_client import AthenaXClient

        draft = _insert_lead_and_draft(tmp_db)
        mock_client = MagicMock(spec=AthenaXClient)
        mock_client.push_lead.return_value = "remote-lead-xyz"
        mock_client.push_outreach.return_value = "remote-outreach-xyz"

        _approve(draft, mock_client)

        with tmp_db.get_connection() as conn:
            remote_id = conn.execute(
                "SELECT remote_lead_id FROM leads WHERE id=?", (draft["lead_id"],)
            ).fetchone()[0]
        assert remote_id == "remote-lead-xyz"

    def test_approve_is_idempotent_for_lead_push(self, tmp_db, monkeypatch):
        """If remote_lead_id already set, push_lead should NOT be called again."""
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        from athenax.cli.review import _approve
        from athenax.api.athenax_client import AthenaXClient

        draft = _insert_lead_and_draft(tmp_db)
        # Pre-set the remote_lead_id
        draft["remote_lead_id"] = "already-pushed"
        with tmp_db.get_connection() as conn:
            conn.execute("UPDATE leads SET remote_lead_id=? WHERE id=?",
                         ("already-pushed", draft["lead_id"]))
            conn.commit()

        mock_client = MagicMock(spec=AthenaXClient)
        mock_client.push_outreach.return_value = "new-outreach-id"

        _approve(draft, mock_client)

        mock_client.push_lead.assert_not_called()
        mock_client.push_outreach.assert_called_once()


# ── _fetch_pending ────────────────────────────────────────────────────────────

class TestFetchPending:
    def test_returns_pending_drafts(self, tmp_db, monkeypatch):
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        from athenax.cli.review import _fetch_pending
        _insert_lead_and_draft(tmp_db)
        drafts = _fetch_pending()
        assert len(drafts) == 1
        assert drafts[0]["status"] == "pending"

    def test_does_not_return_approved(self, tmp_db, monkeypatch):
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        from athenax.cli.review import _fetch_pending, _reject
        draft = _insert_lead_and_draft(tmp_db)
        _reject(draft["id"])
        assert _fetch_pending() == []

    def test_ordered_by_score_desc(self, tmp_db, monkeypatch):
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        from athenax.cli.review import _fetch_pending
        # Insert two drafts with different scores
        _insert_lead_and_draft(tmp_db)  # score 85
        import uuid
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        lead_id = str(uuid.uuid4())
        eval_id = str(uuid.uuid4())
        draft_id = str(uuid.uuid4())
        with tmp_db.get_connection() as conn:
            conn.execute("INSERT INTO leads (id,source,name,url,description,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                         (lead_id,"github","High Score","https://hi.com","",now,now))
            conn.execute("INSERT INTO evaluations (id,lead_id,compatibility_score,reason_for_partnership,created_at) VALUES (?,?,?,?,?)",
                         (eval_id,lead_id,99,"Top pick",now))
            conn.execute("INSERT INTO outreach_drafts (id,lead_id,evaluation_id,channel,body,status,created_at) VALUES (?,?,?,?,?,?,?)",
                         (draft_id,lead_id,eval_id,"email","Hi","pending",now))
            conn.commit()
        drafts = _fetch_pending()
        assert drafts[0]["compatibility_score"] >= drafts[-1]["compatibility_score"]
