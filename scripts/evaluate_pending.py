"""
One-shot script: evaluate all leads that have no evaluation yet.

Usage (on VPS):
    cd /opt/athenax && .venv/bin/python scripts/evaluate_pending.py

This is a thin wrapper around athenax.main.run_evaluation() — the decoupled
Evaluate step, which is the single source of truth (also used by the dashboard
"Evaluate" button).
"""
import sys
from pathlib import Path

# Load .env before any athenax imports
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from athenax.main import run_evaluation


if __name__ == "__main__":
    run_evaluation()
