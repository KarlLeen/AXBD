"""Entrypoint — manual trigger and cron scheduling."""
import json
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from athenax.db.database import get_connection, init_db
from athenax.crew import build_crew


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_json(text: str) -> list:
    """Pull the first JSON array out of a potentially markdown-wrapped LLM response."""
    import re
    # Strip markdown code fences
    text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    # Find the outermost [ ... ]
    start = text.find("[")
    if start == -1:
        return []
    depth, end = 0, -1
    for i, ch in enumerate(text[start:], start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        return []
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []


def _save_leads(leads: list) -> dict[str, str]:
    """Upsert lead rows (dedup by URL); return {name → id} map."""
    id_map: dict[str, str] = {}
    now = _now()
    with get_connection() as conn:
        for lead in leads:
            url = lead.get("url", "")
            tech = lead.get("tech_stack")
            tech_json = json.dumps(tech) if isinstance(tech, list) else tech

            existing = conn.execute(
                "SELECT id FROM leads WHERE url = ?", (url,)
            ).fetchone()

            if existing:
                # URL already in DB — update numeric fields only
                lead_id = existing[0]
                conn.execute(
                    """UPDATE leads SET
                        github_stars       = COALESCE(?, github_stars),
                        github_forks       = COALESCE(?, github_forks),
                        commits_last_30d   = COALESCE(?, commits_last_30d),
                        twitter_followers  = COALESCE(?, twitter_followers),
                        twitter_recent_tweet = COALESCE(?, twitter_recent_tweet),
                        linkedin_recent_post = COALESCE(?, linkedin_recent_post),
                        updated_at         = ?
                    WHERE id = ?""",
                    (
                        lead.get("github_stars"),
                        lead.get("github_forks"),
                        lead.get("commits_last_30d"),
                        lead.get("twitter_followers"),
                        lead.get("twitter_recent_tweet"),
                        lead.get("linkedin_recent_post"),
                        now,
                        lead_id,
                    ),
                )
            else:
                # New URL — insert fresh row
                lead_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO leads
                       (id, source, name, url, description, sector,
                        github_stars, github_forks, github_contributors,
                        commits_last_30d, tech_stack,
                        linkedin_profile, linkedin_recent_post,
                        twitter_handle, twitter_followers, twitter_recent_tweet,
                        created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        lead_id,
                        lead.get("source", "unknown"),
                        lead.get("name", ""),
                        url,
                        lead.get("description", ""),
                        lead.get("sector"),
                        lead.get("github_stars"),
                        lead.get("github_forks"),
                        lead.get("github_contributors"),
                        lead.get("commits_last_30d"),
                        tech_json,
                        lead.get("linkedin_profile"),
                        lead.get("linkedin_recent_post"),
                        lead.get("twitter_handle"),
                        lead.get("twitter_followers"),
                        lead.get("twitter_recent_tweet"),
                        now,
                        now,
                    ),
                )
            id_map[lead.get("name", "")] = lead_id
        conn.commit()
    return id_map


def _save_evaluations(evals: list, lead_id_map: dict[str, str]) -> dict[str, str]:
    """Insert evaluation rows; return {lead_name → eval_id}."""
    eval_id_map: dict[str, str] = {}
    with get_connection() as conn:
        for ev in evals:
            lead_name = ev.get("lead_name", "")
            lead_id = lead_id_map.get(lead_name)
            if not lead_id:
                # fuzzy match by substring
                for k, v in lead_id_map.items():
                    if lead_name.lower() in k.lower() or k.lower() in lead_name.lower():
                        lead_id = v
                        break
            if not lead_id:
                print(f"  [WARN] No lead_id for evaluation of '{lead_name}' — skipping")
                continue
            eval_id = str(uuid.uuid4())
            traits = ev.get("nounish_traits", [])
            conn.execute(
                """INSERT INTO evaluations
                   (id, lead_id, compatibility_score, nounish_traits,
                    reason_for_partnership, listing_fit_notes, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    eval_id,
                    lead_id,
                    ev.get("compatibility_score", 0),
                    json.dumps(traits) if isinstance(traits, list) else traits,
                    ev.get("reason_for_partnership", ""),
                    ev.get("listing_fit_notes", ""),
                    _now(),
                ),
            )
            eval_id_map[lead_name] = eval_id
        conn.commit()
    return eval_id_map


def _save_drafts(drafts: list, lead_id_map: dict[str, str], eval_id_map: dict[str, str]) -> None:
    with get_connection() as conn:
        for draft in drafts:
            lead_name = draft.get("lead_name", "")
            lead_id = lead_id_map.get(lead_name)
            eval_id = eval_id_map.get(lead_name)
            if not lead_id:
                for k, v in lead_id_map.items():
                    if lead_name.lower() in k.lower() or k.lower() in lead_name.lower():
                        lead_id = v
                        break
            if not eval_id:
                for k, v in eval_id_map.items():
                    if lead_name.lower() in k.lower() or k.lower() in lead_name.lower():
                        eval_id = v
                        break
            if not lead_id or not eval_id:
                print(f"  [WARN] Missing lead_id/eval_id for draft '{lead_name}' — skipping")
                continue
            conn.execute(
                """INSERT INTO outreach_drafts
                   (id, lead_id, evaluation_id, channel, subject, body, status, created_at)
                   VALUES (?,?,?,?,?,?,'pending',?)""",
                (
                    str(uuid.uuid4()),
                    lead_id,
                    eval_id,
                    draft.get("channel", "email"),
                    draft.get("subject"),
                    draft.get("body", ""),
                    _now(),
                ),
            )
        conn.commit()


def _push_pipeline_results(lead_id_map: dict, eval_id_map: dict) -> None:
    """
    Push evaluated leads to AthenaX via Internal Service API.

    Workflow per lead (mirrors the documented typical workflow):
      1. GET /internal/categories/by-name?name=<sector>  → resolve category_id
      2. GET /internal/products/by-name?name=<name>      → skip if already exists
      3. POST /internal/products                          → create PENDING product
    """
    from athenax.api.athenax_client import AthenaXClient
    client = AthenaXClient()

    with get_connection() as conn:
        eval_rows = {
            row["lead_id"]: dict(row)
            for row in conn.execute("SELECT * FROM evaluations").fetchall()
        }

    pushed = 0
    skipped = 0
    failed = 0

    for local_lead_id, eval_row in eval_rows.items():
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM leads WHERE id=?", (local_lead_id,)).fetchone()
        if not row:
            continue
        lead = dict(row)
        name = lead.get("name", "")

        # Already pushed in a previous run
        if lead.get("remote_lead_id"):
            pushed += 1
            continue

        try:
            # Step 1 — resolve category
            category_id = client.resolve_category_id(lead.get("sector", ""))
            if category_id is None:
                print(f"  [WARN] Category not found for sector '{lead.get('sector')}' "
                      f"({name}) — product will be created without category")

            # Step 2 — check for existing product
            existing = client.get_product_by_name(name)
            if existing:
                remote_id = str(existing.get("id", ""))
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE leads SET remote_lead_id=? WHERE id=?",
                        (remote_id, local_lead_id),
                    )
                    conn.commit()
                print(f"  ↩ Already exists: {name} (id={remote_id[:8]}…, status={existing.get('status')})")
                skipped += 1
                continue

            # Step 3 — create product
            product_id = client.push_product(lead, eval_row, category_id)
            with get_connection() as conn:
                conn.execute(
                    "UPDATE leads SET remote_lead_id=? WHERE id=?",
                    (product_id, local_lead_id),
                )
                conn.commit()
            print(f"  ✓ Created (PENDING): {name} → id={product_id[:8]}…")
            pushed += 1

        except Exception as exc:
            print(f"  [WARN] push failed for '{name}': {exc}")
            failed += 1

    print(f"    AthenaX sync: {pushed} pushed, {skipped} already existed, {failed} failed")


def run_pipeline() -> None:
    init_db()
    print("\n🚀  Starting AthenaX Partnership Agent pipeline...\n")

    crew = build_crew()
    result = crew.kickoff()

    tasks_output = getattr(result, "tasks_output", [])
    raw_leads_text  = tasks_output[0].raw if len(tasks_output) > 0 else ""
    raw_evals_text  = tasks_output[1].raw if len(tasks_output) > 1 else ""
    raw_drafts_text = tasks_output[2].raw if len(tasks_output) > 2 else ""

    leads  = _extract_json(raw_leads_text)
    evals  = _extract_json(raw_evals_text)
    drafts = _extract_json(raw_drafts_text)

    # Filter out Nouns DAO's own / affiliated projects
    from athenax.filters import filter_leads, is_excluded
    leads, excluded = filter_leads(leads)
    if excluded:
        print(f"\n🚫  Excluded {len(excluded)} Nouns-affiliated lead(s):")
        for e in excluded:
            print(f"     - {e.get('name','?')} — {e['_exclusion_reason']}")

    # Drop evals/drafts whose lead was excluded (match by name)
    excluded_names = {(e.get("name") or "").lower() for e in excluded}
    def _is_excluded_name(item_name: str) -> bool:
        n = (item_name or "").lower()
        if n in excluded_names:
            return True
        # also re-check the name against keyword rules directly
        return is_excluded({"name": item_name})[0]

    evals  = [e for e in evals  if not _is_excluded_name(e.get("lead_name", ""))]
    drafts = [d for d in drafts if not _is_excluded_name(d.get("lead_name", ""))]

    print(f"\n📦  Scout found    : {len(leads)} leads (after exclusions)")
    print(f"📊  Evaluator kept : {len(evals)} top leads")
    print(f"✉️   Writer drafted : {len(drafts)} messages")

    lead_id_map = _save_leads(leads)
    eval_id_map = _save_evaluations(evals, lead_id_map)
    _save_drafts(drafts, lead_id_map, eval_id_map)

    print("\n✅  Saved to athenax.db — pushing to AthenaX API...")
    _push_pipeline_results(lead_id_map, eval_id_map)
    print("    Run `athenax review` (CLI) or `athenax bot` (Telegram) to review drafts.\n")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AthenaX Partnership Agent")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Run the pipeline once now")
    sub.add_parser("review", help="Open the CLI review loop")
    sub.add_parser("dashboard", help="Open the web admin dashboard")
    sub.add_parser("bot", help="Start the Telegram admin bot")

    cron_p = sub.add_parser("schedule", help="Run on a weekly cron (blocks)")
    cron_p.add_argument("--day", default="monday")
    cron_p.add_argument("--time", default="09:00")

    args = parser.parse_args()

    if args.command == "run":
        run_pipeline()
    elif args.command == "review":
        from athenax.cli.review import main as review_main
        review_main()
    elif args.command == "dashboard":
        from dashboard.app import run as run_dashboard
        run_dashboard()
    elif args.command == "bot":
        from telegram_bot.bot import run_bot
        run_bot()
    elif args.command == "schedule":
        import schedule as sched
        import time

        getattr(sched.every(), args.day).at(args.time).do(run_pipeline)
        print(f"Scheduled: every {args.day} at {args.time} UTC")
        while True:
            sched.run_pending()
            time.sleep(60)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
