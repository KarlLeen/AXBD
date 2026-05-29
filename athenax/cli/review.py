"""Human-in-the-Loop CLI review loop."""
from datetime import datetime, timezone

from athenax.api.athenax_client import AthenaXClient
from athenax.db.database import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fetch_pending() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                od.id              AS id,
                od.lead_id         AS lead_id,
                od.evaluation_id   AS evaluation_id,
                od.channel         AS channel,
                od.subject         AS subject,
                od.body            AS body,
                od.status          AS status,
                l.name             AS lead_name,
                l.url              AS lead_url,
                l.source           AS lead_source,
                l.tech_stack       AS tech_stack,
                l.twitter_handle   AS twitter_handle,
                l.remote_lead_id   AS remote_lead_id,
                e.compatibility_score     AS compatibility_score,
                e.nounish_traits          AS nounish_traits,
                e.reason_for_partnership  AS reason_for_partnership,
                e.listing_fit_notes       AS listing_fit_notes
            FROM outreach_drafts od
            JOIN leads       l ON od.lead_id       = l.id
            JOIN evaluations e ON od.evaluation_id = e.id
            WHERE od.status = 'pending'
            ORDER BY e.compatibility_score DESC
        """).fetchall()
    return [dict(r) for r in rows]


def _render_draft(i: int, total: int, draft: dict) -> None:
    sep = "─" * 45
    handle = f"@{draft['twitter_handle']}" if draft.get("twitter_handle") else draft["lead_name"]
    channel_label = "Twitter DM" if draft["channel"] == "twitter_dm" else "Email"
    print(f"\n{sep}")
    print(f"Draft {i}/{total} — {handle} ({channel_label})")
    print(f"Score: {draft['compatibility_score']}/100 | \"{draft['reason_for_partnership']}\"")
    print(sep)
    if draft.get("subject"):
        print(f"Subject: {draft['subject']}")
        print()
    print(draft["body"])
    print(sep)


def _approve(draft: dict, client: AthenaXClient) -> None:
    approved_at = _now()

    # 1. Push lead if not already pushed (idempotent via remote_lead_id)
    remote_lead_id = draft.get("remote_lead_id")
    if not remote_lead_id:
        remote_lead_id = client.push_lead({
            "name": draft["lead_name"],
            "url": draft["lead_url"],
            "source": draft["lead_source"],
            "tech_stack": draft.get("tech_stack"),
            "compatibility_score": draft["compatibility_score"],
            "reason_for_partnership": draft["reason_for_partnership"],
            "nounish_traits": draft.get("nounish_traits"),
        })
        with get_connection() as conn:
            conn.execute(
                "UPDATE leads SET remote_lead_id = ? WHERE id = ?",
                (remote_lead_id, draft["lead_id"]),
            )
            conn.commit()

    # 2. Push outreach draft
    remote_outreach_id = client.push_outreach(
        {
            "channel": draft["channel"],
            "subject": draft.get("subject"),
            "body": draft["body"],
        },
        remote_lead_id,
        approved_at,
    )

    # 3. Mark as approved locally
    with get_connection() as conn:
        conn.execute(
            "UPDATE outreach_drafts SET status = 'approved', approved_at = ? WHERE id = ?",
            (approved_at, draft["id"]),
        )
        conn.commit()

    print(f"✓ Pushed — remote lead={remote_lead_id[:8]}… outreach={remote_outreach_id[:8]}…")


def _reject(draft_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE outreach_drafts SET status = 'rejected' WHERE id = ?",
            (draft_id,),
        )
        conn.commit()


def _edit_body(draft: dict) -> str:
    import os
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(draft["body"])
        path = f.name
    editor = os.getenv("EDITOR", "nano")
    subprocess.call([editor, path])
    with open(path) as f:
        new_body = f.read()
    os.unlink(path)
    return new_body


def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    client = AthenaXClient()
    drafts = _fetch_pending()

    if not drafts:
        print("No pending drafts to review.")
        return

    total = len(drafts)
    for i, draft in enumerate(drafts, 1):
        _render_draft(i, total, draft)
        while True:
            choice = input("[a] Approve & push  [e] Edit  [r] Reject  [s] Skip\n> ").strip().lower()
            if choice == "a":
                try:
                    _approve(draft, client)
                except Exception as exc:
                    print(f"✗ Push failed: {exc}")
                break
            elif choice == "e":
                new_body = _edit_body(draft)
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE outreach_drafts SET body = ? WHERE id = ?",
                        (new_body, draft["id"]),
                    )
                    conn.commit()
                draft["body"] = new_body
                _render_draft(i, total, draft)
            elif choice == "r":
                _reject(draft["id"])
                print("✗ Rejected.")
                break
            elif choice == "s":
                print("Skipped.")
                break
            else:
                print("Invalid choice — enter a, e, r, or s.")


if __name__ == "__main__":
    main()
