"""Unit tests for DB init, migration, upsert, evaluations, and draft saving."""
import json
import uuid
import pytest
from unittest.mock import patch


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    import athenax.db.database as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    db_mod.init_db()
    return db_mod


def _lead(url="https://example.com", name="Test Project", stars=100):
    return {
        "source": "github", "name": name, "url": url,
        "description": "A test project",
        "github_stars": stars, "github_forks": 10,
        "commits_last_30d": 5, "tech_stack": ["Python"],
        "twitter_followers": 500,
    }


def _eval(lead_name="Test Project", score=80):
    return {
        "lead_name": lead_name,
        "lead_url": "https://example.com",
        "compatibility_score": score,
        "nounish_traits": ["CC0"],
        "reason_for_partnership": "Strong fit",
        "listing_fit_notes": "Good match",
    }


# ── Schema & migration ────────────────────────────────────────────────────────

class TestInitDb:
    def test_all_tables_created(self, tmp_db):
        with tmp_db.get_connection() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
        assert {"leads", "evaluations", "outreach_drafts"}.issubset(tables)

    def test_unique_index_on_leads_url(self, tmp_db):
        with tmp_db.get_connection() as conn:
            indexes = [r[1] for r in conn.execute("PRAGMA index_list(leads)").fetchall()]
        assert "idx_leads_url" in indexes

    def test_migration_adds_remote_lead_id(self, tmp_db):
        with tmp_db.get_connection() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
        assert "remote_lead_id" in cols

    def test_migration_adds_commits_last_30d(self, tmp_db):
        with tmp_db.get_connection() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
        assert "commits_last_30d" in cols

    def test_migration_adds_updated_at(self, tmp_db):
        with tmp_db.get_connection() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(leads)").fetchall()}
        assert "updated_at" in cols

    def test_migration_adds_remote_outreach_id(self, tmp_db):
        with tmp_db.get_connection() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(outreach_drafts)").fetchall()}
        assert "remote_outreach_id" in cols

    def test_migration_is_idempotent(self, tmp_db):
        """Running init_db twice should not raise."""
        tmp_db.init_db()
        tmp_db.init_db()


# ── Lead upsert ───────────────────────────────────────────────────────────────

class TestLeadUpsert:
    def test_new_lead_inserted(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        id_map = _save_leads([_lead()])
        assert len(id_map) == 1
        with tmp_db.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1

    def test_duplicate_url_updates_stars(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        url = "https://github.com/test/repo"
        _save_leads([_lead(url=url, stars=100)])
        _save_leads([_lead(url=url, stars=999)])
        with tmp_db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            stars = conn.execute("SELECT github_stars FROM leads WHERE url=?", (url,)).fetchone()[0]
        assert count == 1
        assert stars == 999

    def test_duplicate_preserves_original_id(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        url = "https://github.com/test/repo"
        id_map1 = _save_leads([_lead(url=url, name="Repo")])
        id_map2 = _save_leads([_lead(url=url, name="Repo")])
        assert id_map1.get("Repo") == id_map2.get("Repo")

    def test_different_urls_both_saved(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        _save_leads([_lead(url="https://a.com", name="A"), _lead(url="https://b.com", name="B")])
        with tmp_db.get_connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 2

    def test_commits_last_30d_saved(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        lead = {**_lead(), "commits_last_30d": 42}
        _save_leads([lead])
        with tmp_db.get_connection() as conn:
            row = conn.execute("SELECT commits_last_30d FROM leads").fetchone()
        assert row[0] == 42


# ── Evaluations ───────────────────────────────────────────────────────────────

class TestSaveEvaluations:
    def _insert_lead(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        return _save_leads([_lead()])

    def test_saves_evaluation(self, tmp_db, monkeypatch):
        from athenax.main import _save_evaluations
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        id_map = self._insert_lead(tmp_db, monkeypatch)
        _save_evaluations([_eval()], id_map)
        with tmp_db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
        assert count == 1

    def test_saves_score(self, tmp_db, monkeypatch):
        from athenax.main import _save_evaluations
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        id_map = self._insert_lead(tmp_db, monkeypatch)
        _save_evaluations([_eval(score=92)], id_map)
        with tmp_db.get_connection() as conn:
            score = conn.execute("SELECT compatibility_score FROM evaluations").fetchone()[0]
        assert score == 92

    def test_fuzzy_match_by_substring(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads, _save_evaluations
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        id_map = _save_leads([_lead(name="unionlabs/union")])
        # Evaluator uses a shorter name
        eval_id_map = _save_evaluations([{**_eval(lead_name="union"), "lead_url": ""}], id_map)
        assert len(eval_id_map) == 1

    def test_skips_unknown_lead(self, tmp_db, monkeypatch):
        from athenax.main import _save_evaluations
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        eval_id_map = _save_evaluations([_eval(lead_name="Ghost Project")], {})
        assert len(eval_id_map) == 0


# ── Outreach drafts ───────────────────────────────────────────────────────────

class TestSaveDrafts:
    def _setup(self, tmp_db, monkeypatch):
        from athenax.main import _save_leads, _save_evaluations
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        id_map = _save_leads([_lead()])
        eval_map = _save_evaluations([_eval()], id_map)
        return id_map, eval_map

    def test_saves_draft(self, tmp_db, monkeypatch):
        from athenax.main import _save_drafts
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        id_map, eval_map = self._setup(tmp_db, monkeypatch)
        _save_drafts([{"lead_name": "Test Project", "channel": "twitter_dm",
                       "subject": None, "body": "Hello!"}], id_map, eval_map)
        with tmp_db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM outreach_drafts").fetchone()[0]
        assert count == 1

    def test_draft_starts_pending(self, tmp_db, monkeypatch):
        from athenax.main import _save_drafts
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        id_map, eval_map = self._setup(tmp_db, monkeypatch)
        _save_drafts([{"lead_name": "Test Project", "channel": "email",
                       "subject": "Hi", "body": "Body"}], id_map, eval_map)
        with tmp_db.get_connection() as conn:
            status = conn.execute("SELECT status FROM outreach_drafts").fetchone()[0]
        assert status == "pending"

    def test_skips_draft_when_no_ids(self, tmp_db, monkeypatch):
        from athenax.main import _save_drafts
        monkeypatch.setattr("athenax.db.database.DB_PATH", tmp_db.DB_PATH)
        _save_drafts([{"lead_name": "Ghost", "channel": "email", "body": "x"}], {}, {})
        with tmp_db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM outreach_drafts").fetchone()[0]
        assert count == 0
