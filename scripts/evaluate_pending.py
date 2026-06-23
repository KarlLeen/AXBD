"""
One-shot script: evaluate all leads that have no evaluation yet.

Usage (on VPS):
    cd /opt/athenax && .venv/bin/python scripts/evaluate_pending.py
"""
import json
import os
import sys
from pathlib import Path

# Load .env before any athenax imports
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from crewai import Crew, Task

from athenax.db.database import get_connection, init_db
from athenax.agents.evaluator import build_evaluator
from athenax.tools.coingecko_tool import CoinGeckoTool
from athenax.crew import (
    build_llm,
    SECTORS, DISQUALIFIERS, NEW_PROJECT_CRITERIA,
    ESTABLISHED_PROJECT_CRITERIA, PIPELINE_MIX,
)
from athenax.main import _extract_json, _save_evaluations


def _fetch_pending_leads() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT l.*
            FROM leads l
            WHERE l.id NOT IN (SELECT lead_id FROM evaluations)
            ORDER BY l.created_at
        """).fetchall()
    leads = []
    for row in rows:
        d = dict(row)
        # Parse JSON fields
        for field in ("tech_stack", "bd_twitter_handles"):
            if isinstance(d.get(field), str):
                try:
                    d[field] = json.loads(d[field])
                except Exception:
                    pass
        leads.append(d)
    return leads


def run_evaluate_pending() -> None:
    init_db()
    leads = _fetch_pending_leads()
    if not leads:
        print("No pending leads to evaluate.")
        return

    print(f"Found {len(leads)} unevaluated leads — running Evaluator...\n")

    leads_json = json.dumps(leads, ensure_ascii=False, indent=2)

    llm = build_llm()
    evaluator = build_evaluator(llm=llm, tools=[CoinGeckoTool()])

    eval_task = Task(
        description=f"""
You have received raw leads from the Scout. Apply the AthenaX selection criteria rigorously.

━━━ LEADS TO EVALUATE ━━━
{leads_json}

━━━ STEP 1 — HARD DISQUALIFIERS (check first, reject immediately if any apply) ━━━
{DISQUALIFIERS}

━━━ STEP 2 — CLASSIFY each surviving lead ━━━
• "new"         → pre-PMF, early GTM, or actively fundraising (70% bucket)
• "established" → recognized market leader or Tier 1/2 player (30% bucket)

━━━ STEP 3 — SCORE 0–100 ━━━

For NEW projects:
{NEW_PROJECT_CRITERIA}

Base score starts at 40 if all minimum requirements are met.
Add signal booster points as listed above.
Apply velocity multiplier: if growth rate is exceptional, multiply total by up to 1.3×.
For GitHub repos: use commits_last_30d as velocity signal (>50 commits/month = strong).
Cap at 100.

For ESTABLISHED crypto projects: use the coingecko_search tool to verify they are
actually listed. A Tier 1 project must have a CoinGecko market_cap_rank ≤ 50.

For ESTABLISHED projects:
{ESTABLISHED_PROJECT_CRITERIA}

Score based on tier (Tier 1 = 85–100, Tier 2 = 70–84), sector leadership, and active development.

━━━ STEP 4 — EVALUATE ALL LEADS ━━━
{PIPELINE_MIX}
Evaluate EVERY lead that passes the disqualifier check. Do NOT limit to a subset.
Discard only leads that score below 55 — include everything else in your output.

━━━ STEP 5 — PRODUCE DETAILED EVALUATION ━━━
For EVERY surviving lead, produce a full criteria breakdown so the reviewer can
see exactly why it scored the way it did. If the Scout did not provide a field
(e.g. github_stars is null) and you need it to evaluate, call the github_search
or coingecko_search tool to fetch it. Do not leave a criterion unevaluated.

For each criterion record:
• met: true / false / null (null = data unavailable after attempting to fetch)
• note: short factual note (the actual data or why it's missing)

Return your results as a JSON array.
""",
        expected_output=(
            "A JSON array of ALL evaluated leads that scored ≥ 55 (no upper limit on count), each with: "
            "lead_name, lead_url, sector (one of the 7 sectors), "
            "project_type ('new' or 'established'), "
            "compatibility_score (int 0–100), "
            "disqualifiers_checked (bool — true means passed all checks), "
            "minimum_requirements_met (bool, new projects only), "
            "signal_boosters (string array — e.g. ['YC W25', 'a16z portfolio']), "
            "velocity_assessment (1 sentence on growth trajectory), "
            "nounish_traits (string array — keep for Nouns DAO context), "
            "reason_for_partnership (1–2 sentences — why AthenaX incubation/distribution fits this project), "
            "listing_fit_notes (1 sentence — which AthenaX value prop is most relevant: capital alignment, distribution, narrative, or ecosystem access), "
            "score_breakdown (object): { "
            "  base_score (int — 40 for new if minimums met, or tier-based for established), "
            "  booster_points (int — sum of signal booster points awarded), "
            "  velocity_multiplier (float — 1.0–1.3), "
            "  boosters_detail (array of {signal, points, note}) "
            "}, "
            "criteria_detail (object with per-criterion result): { "
            "  working_product: {met, note}, "
            "  website: {met, note}, "
            "  github: {met, stars, commits_last_30d, note}, "
            "  twitter: {met, followers, note}, "
            "  team: {met, note}, "
            "  sector_fit: {met, note}, "
            "  active_development: {met, note}, "
            "  market_presence: {met, note} "
            "}."
        ),
        agent=evaluator,
    )

    crew = Crew(agents=[evaluator], tasks=[eval_task], verbose=True)
    result = crew.kickoff()

    raw = result.tasks_output[0].raw if result.tasks_output else ""
    evals = _extract_json(raw)

    if not evals:
        print("\n[ERROR] No evaluations parsed from output. Raw output snippet:")
        print(raw[:500])
        sys.exit(1)

    # Build lead_id_map from DB for matching
    with get_connection() as conn:
        rows = conn.execute("SELECT name, id FROM leads").fetchall()
    lead_id_map = {row[0]: row[1] for row in rows}

    _save_evaluations(evals, lead_id_map)
    print(f"\n✅  Saved {len(evals)} new evaluations to athenax.db")


if __name__ == "__main__":
    run_evaluate_pending()
