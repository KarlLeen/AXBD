import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "athenax.db"

_CREATE_LEADS = """
CREATE TABLE IF NOT EXISTS leads (
    id                    TEXT PRIMARY KEY,
    source                TEXT NOT NULL,
    name                  TEXT NOT NULL,
    url                   TEXT NOT NULL,
    description           TEXT,
    github_stars          INTEGER,
    github_forks          INTEGER,
    github_contributors   INTEGER,
    tech_stack            TEXT,
    linkedin_profile      TEXT,
    linkedin_recent_post  TEXT,
    twitter_handle        TEXT,
    twitter_followers     INTEGER,
    twitter_recent_tweet  TEXT,
    created_at            TEXT NOT NULL
);
"""

_CREATE_EVALUATIONS = """
CREATE TABLE IF NOT EXISTS evaluations (
    id                      TEXT PRIMARY KEY,
    lead_id                 TEXT NOT NULL,
    compatibility_score     INTEGER NOT NULL,
    nounish_traits          TEXT,
    reason_for_partnership  TEXT NOT NULL,
    listing_fit_notes       TEXT,
    created_at              TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);
"""

_CREATE_OUTREACH_DRAFTS = """
CREATE TABLE IF NOT EXISTS outreach_drafts (
    id              TEXT PRIMARY KEY,
    lead_id         TEXT NOT NULL,
    evaluation_id   TEXT NOT NULL,
    channel         TEXT NOT NULL,
    subject         TEXT,
    body            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    approved_at     TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(id),
    FOREIGN KEY (evaluation_id) REFERENCES evaluations(id)
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(_CREATE_LEADS)
        conn.execute(_CREATE_EVALUATIONS)
        conn.execute(_CREATE_OUTREACH_DRAFTS)
        _migrate(conn)
        conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    lead_cols = {row[1] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    if "remote_lead_id" not in lead_cols:
        conn.execute("ALTER TABLE leads ADD COLUMN remote_lead_id TEXT")

    od_cols = {row[1] for row in conn.execute("PRAGMA table_info(outreach_drafts)").fetchall()}
    if "remote_outreach_id" not in od_cols:
        conn.execute("ALTER TABLE outreach_drafts ADD COLUMN remote_outreach_id TEXT")


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
