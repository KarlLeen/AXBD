"""Unit tests for DB init, migration, and lead upsert logic."""
import json
import uuid
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp file for each test."""
    db_file = tmp_path / "test.db"
    import athenax.db.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    db_mod.init_db()
    return db_mod


def _lead(url="https://example.com", name="Test Project", stars=100):
    return {
        "source": "github",
        "name": name,
        "url": url,
        "description": "A test project",
        "github_stars": stars,
        "github_forks": 10,
        "commits_last_30d": 5,
        "tech_stack": ["Python"],
        "twitter_followers": 500,
    }


class TestInitDb:
    def test_tables_created(self, tmp_db):
        with tmp_db.get_connection() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert {"leads", "evaluations", "outreach_drafts"}.issubset(tables)

    def test_unique_index_on_url(self, tmp_db):
        with tmp_db.get_connection() as conn:
            indexes = [r[1] for r in conn.execute("PRAGMA index_list(leads)").fetchall()]
        assert "idx_leads_url" in indexes

    def test_migration_columns(self, tmp_db):
        with tmp_db.get_connection() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
        assert "remote_lead_id" in cols
        assert "commits_last_30d" in cols
        assert "updated_at" in cols


class TestLeadUpsert:
    def test_new_lead_inserted(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)

        id_map = _save_leads([_lead()])
        assert len(id_map) == 1
        with tmp_db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        assert count == 1

    def test_duplicate_url_updates_not_inserts(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)

        url = "https://github.com/test/repo"
        _save_leads([_lead(url=url, stars=100)])
        _save_leads([_lead(url=url, stars=999)])  # same URL, updated stars

        with tmp_db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            row = conn.execute("SELECT github_stars FROM leads WHERE url=?", (url,)).fetchone()

        assert count == 1          # still only one row
        assert row[0] == 999       # stars updated

    def test_two_different_urls_both_saved(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)

        _save_leads([
            _lead(url="https://a.com", name="A"),
            _lead(url="https://b.com", name="B"),
        ])
        with tmp_db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        assert count == 2
