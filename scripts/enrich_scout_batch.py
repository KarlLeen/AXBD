"""Phase B — Enrich a Phase-A scout batch workbook (no admin push).

Wraps the existing enrich + team-refill scripts against a scout_listing_batch
output. Stops at an enriched .xlsx for human review — does NOT call
push_listing_to_athenax.py / api.athenax.co.

Pipeline:
  1. scripts/enrich_listing.py   — category, subcategory, short_desc, description,
                                   stage, founded, Discord, GitHub, Docs, team, backers
  2. scripts/refill_team_serper.py — Serper-assisted LinkedIn fill for team cells
                                   (optional; skip with --skip-team-refill)

Usage:
    # Full enrich of a 200-row scout sheet (requires API keys in .env)
    uv run python scripts/enrich_scout_batch.py \\
        --input data/scout_batch_200.xlsx \\
        --output data/scout_batch_200_enriched.xlsx

    # Smoke / partial: first 3 rows only
    uv run python scripts/enrich_scout_batch.py \\
        --input data/scout_batch_200.xlsx \\
        --output data/scout_batch_200_enriched.xlsx \\
        --limit 3

    # After human review, push is a SEPARATE deliberate step (not run here):
    #   uv run python scripts/push_listing_to_athenax.py \\
    #       --input data/scout_batch_200_enriched.xlsx --sheet "Scout Batch"
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from athenax.listing_scout import DEFAULT_SHEET


def _run(cmd: list[str]) -> None:
    print("+ " + " ".join(cmd), file=sys.stderr, flush=True)
    subprocess.run(cmd, check=True, cwd=str(_ROOT))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Phase B: enrich scout batch xlsx → human-review workbook (no push)",
    )
    ap.add_argument("--input", required=True, help="Phase A scout .xlsx")
    ap.add_argument(
        "--output",
        default="",
        help="Enriched output path (default: <input_stem>_enriched.xlsx)",
    )
    ap.add_argument(
        "--sheet",
        default=DEFAULT_SHEET,
        help=f"Sheet name (default: {DEFAULT_SHEET})",
    )
    ap.add_argument("--start", type=int, default=0, help="0-indexed data row start")
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Rows to enrich (0 = all remaining from --start)",
    )
    ap.add_argument(
        "--skip-team-refill",
        action="store_true",
        help="Only run enrich_listing.py (skip Serper team LinkedIn refill)",
    )
    ap.add_argument(
        "--team-limit",
        type=int,
        default=0,
        help="Limit for refill_team_serper (0 = same as --limit / all)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Pass --force to enrich_listing.py (re-enrich filled rows)",
    )
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        sys.exit(f"Input not found: {in_path}")

    out_path = Path(args.output) if args.output else in_path.with_name(
        in_path.stem + "_enriched.xlsx"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    enrich_cmd = [
        sys.executable,
        str(_ROOT / "scripts" / "enrich_listing.py"),
        "--input",
        str(in_path),
        "--sheet",
        args.sheet,
        "--start",
        str(args.start),
        "--limit",
        str(args.limit),
        "--output",
        str(out_path),
    ]
    if args.force:
        enrich_cmd.append("--force")
    _run(enrich_cmd)

    if args.skip_team_refill:
        print(
            f"\nSkipped team refill. Enriched workbook: {out_path}\n"
            "Human review next — do NOT auto-push.",
            file=sys.stderr,
        )
        return

    team_limit = args.team_limit if args.team_limit > 0 else args.limit
    refill_cmd = [
        sys.executable,
        str(_ROOT / "scripts" / "refill_team_serper.py"),
        "--input",
        str(out_path),
        "--sheet",
        args.sheet,
        "--output",
        str(out_path),
        "--start",
        str(args.start),
        "--limit",
        str(team_limit),
        "--fill-empty-teams",
    ]
    _run(refill_cmd)

    print(
        f"\nPhase B complete → {out_path}\n"
        "Stop here for human review. Do not run push_listing_to_athenax.py "
        "until a human has checked the sheet.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
