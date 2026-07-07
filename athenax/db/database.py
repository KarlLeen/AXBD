import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "athenax.db"

_CREATE_LEADS = """
CREATE TABLE IF NOT EXISTS leads (
    id                    TEXT PRIMARY KEY,
    source                TEXT NOT NULL,
    name                  TEXT NOT NULL,
    url                   TEXT NOT NULL UNIQUE,
    short_description     TEXT,
    description           TEXT,
    sector                TEXT,
    subcategory           TEXT,
    stage                 TEXT,
    founded               TEXT,
    website               TEXT,
    github_url            TEXT,
    twitter_url           TEXT,
    discord_url           TEXT,
    docs_url              TEXT,
    other_links           TEXT,
    backers               TEXT,
    grants                TEXT,
    team                  TEXT,
    voices                TEXT,
    bounties              TEXT,
    github_stars          INTEGER,
    github_forks          INTEGER,
    github_contributors   INTEGER,
    commits_last_30d      INTEGER,
    commits_last_90d      INTEGER,
    tech_stack            TEXT,
    linkedin_profile      TEXT,
    linkedin_recent_post  TEXT,
    twitter_handle        TEXT,
    twitter_followers     INTEGER,
    twitter_recent_tweet  TEXT,
    bd_twitter_handles    TEXT,
    contact_email         TEXT,
    velocity_notes        TEXT,
    conference_origin     TEXT,
    remote_lead_id        TEXT,
    certainty             TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
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
    details_json            TEXT,
    created_at              TEXT NOT NULL,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);
"""

_CREATE_OUTREACH_DRAFTS = """
CREATE TABLE IF NOT EXISTS outreach_drafts (
    id                  TEXT PRIMARY KEY,
    lead_id             TEXT NOT NULL,
    evaluation_id       TEXT NOT NULL,
    channel             TEXT NOT NULL,
    subject             TEXT,
    body                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    approved_at         TEXT,
    remote_outreach_id  TEXT,
    recipient_email     TEXT,
    target_handle       TEXT,
    created_at          TEXT NOT NULL,
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


# New columns added in this schema version
_NEW_LEAD_COLS = [
    ("short_description",  "TEXT"),
    ("subcategory",        "TEXT"),
    ("stage",              "TEXT"),
    ("founded",            "TEXT"),
    ("website",            "TEXT"),
    ("github_url",         "TEXT"),
    ("twitter_url",        "TEXT"),
    ("discord_url",        "TEXT"),
    ("docs_url",           "TEXT"),
    ("other_links",        "TEXT"),
    ("backers",            "TEXT"),
    ("grants",             "TEXT"),
    ("team",               "TEXT"),
    ("voices",             "TEXT"),
    ("bounties",           "TEXT"),
    ("commits_last_90d",   "INTEGER"),
    ("velocity_notes",     "TEXT"),
    ("conference_origin",  "TEXT"),
    ("remote_lead_id",     "TEXT"),
    ("certainty",          "TEXT"),
    ("commits_last_30d",   "INTEGER"),
    ("updated_at",         "TEXT"),
    ("bd_twitter_handles", "TEXT"),
    ("contact_email",      "TEXT"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    """Non-destructive migrations applied on every startup."""
    lead_cols = {row[1] for row in conn.execute("PRAGMA table_info(leads)").fetchall()}
    for col, definition in _NEW_LEAD_COLS:
        if col not in lead_cols:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {col} {definition}")

    od_cols = {row[1] for row in conn.execute("PRAGMA table_info(outreach_drafts)").fetchall()}
    for col in ("remote_outreach_id", "recipient_email", "target_handle"):
        if col not in od_cols:
            conn.execute(f"ALTER TABLE outreach_drafts ADD COLUMN {col} TEXT")

    # Dedup: keep oldest record per URL
    conn.execute("""
        DELETE FROM leads WHERE id NOT IN (
            SELECT MIN(id) FROM leads GROUP BY url
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leads_url ON leads(url)")
    conn.execute("UPDATE leads SET updated_at = created_at WHERE updated_at IS NULL")


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
