"""AthenaX Partnership Agent — Admin Dashboard."""
import json
import os
import threading
from datetime import datetime, timezone

from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response

load_dotenv(Path(__file__).parent.parent / ".env")

app = FastAPI(title="AthenaX Dashboard", docs_url=None, redoc_url=None)

# Ensure DB schema is always up-to-date when the dashboard starts
from athenax.db.database import init_db as _init_db
_init_db()

_pipeline_state = {"running": False, "step": None, "last_run": None,
                   "last_status": None, "last_error": None, "last_step": None,
                   "last_added": None, "last_total": None}
_pipeline_lock = threading.Lock()


def _count(table: str) -> int:
    try:
        with _db() as conn:
            if table == "leads_submitted":
                return conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE remote_lead_id IS NOT NULL"
                ).fetchone()[0]
            if table == "leads_verified":
                return conn.execute(
                    "SELECT COUNT(*) FROM leads WHERE certainty IS NOT NULL"
                ).fetchone()[0]
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except Exception:
        return 0


# step -> (callable name in athenax.main, table whose row count we report)
_STEPS = {
    "scout":    ("run_scout",      "leads"),
    "verify":   ("run_verify",     "leads_verified"),
    "evaluate": ("run_evaluation", "evaluations"),
    "submit":   ("run_submit",     "leads_submitted"),
    "pipeline": ("run_pipeline",   "leads"),
}


def _run_step_bg(step: str):
    import athenax.main as _main
    fn_name, table = _STEPS[step]
    fn = getattr(_main, fn_name)
    before = _count(table)
    with _pipeline_lock:
        _pipeline_state.update(running=True, step=step, last_error=None)
    try:
        fn()
        after = _count(table)
        with _pipeline_lock:
            _pipeline_state.update(last_status="ok", last_step=step,
                                   last_added=after - before, last_total=after)
    except Exception as exc:
        with _pipeline_lock:
            _pipeline_state.update(last_status="error", last_step=step, last_error=str(exc))
    finally:
        with _pipeline_lock:
            _pipeline_state.update(running=False, step=None,
                                   last_run=datetime.now(timezone.utc).isoformat())


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _db():
    from athenax.db.database import get_connection
    return get_connection()


_JSON_FIELDS = ("tech_stack", "bd_twitter_handles", "other_links",
                "backers", "team", "voices", "bounties")


@app.get("/api/stats")
def stats():
    with _db() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        evaled   = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
        high     = conn.execute("SELECT COUNT(*) FROM evaluations WHERE compatibility_score >= 80").fetchone()[0]
        verified = conn.execute("SELECT COUNT(*) FROM leads WHERE certainty IS NOT NULL").fetchone()[0]
    return {"total_leads": total, "evaluations": evaled, "high_score": high, "verified": verified}


@app.get("/api/leads")
def leads():
    """All leads with evaluation data merged, evaluated first sorted by score."""
    with _db() as conn:
        rows = conn.execute("""
            SELECT
                l.id, l.source, l.name, l.url,
                l.short_description, l.description,
                l.sector, l.subcategory, l.stage, l.founded,
                l.website, l.github_url, l.twitter_url, l.discord_url, l.docs_url,
                l.other_links, l.backers, l.team, l.voices, l.bounties,
                l.github_stars, l.github_forks, l.commits_last_30d, l.commits_last_90d,
                l.tech_stack, l.linkedin_profile, l.linkedin_recent_post,
                l.twitter_handle, l.twitter_followers, l.twitter_recent_tweet,
                l.bd_twitter_handles, l.contact_email,
                l.velocity_notes, l.conference_origin,
                l.certainty, l.certainty_score, l.certainty_note, l.created_at,
                e.id         AS eval_id,
                e.compatibility_score,
                e.reason_for_partnership,
                e.listing_fit_notes,
                e.nounish_traits,
                e.details_json
            FROM leads l
            LEFT JOIN evaluations e ON e.lead_id = l.id
            ORDER BY
                CASE WHEN e.compatibility_score IS NULL THEN 1 ELSE 0 END,
                e.compatibility_score DESC
        """).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        for f in _JSON_FIELDS:
            if isinstance(d.get(f), str):
                try: d[f] = json.loads(d[f])
                except: d[f] = []
        if d.get("nounish_traits"):
            try: d["nounish_traits"] = json.loads(d["nounish_traits"])
            except: d["nounish_traits"] = []
        if d.get("details_json"):
            try: d["details"] = json.loads(d["details_json"])
            except: d["details"] = {}
        else:
            d["details"] = {}
        d.pop("details_json", None)
        result.append(d)
    return result


@app.get("/api/pipeline/status")
def pipeline_status():
    with _pipeline_lock:
        return dict(_pipeline_state)


def _start_step(step: str):
    with _pipeline_lock:
        if _pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="A run is already in progress")
    threading.Thread(target=_run_step_bg, args=(step,), daemon=True).start()
    return {"started": True, "step": step}


@app.post("/api/scout/run")
def trigger_scout():
    return _start_step("scout")


@app.post("/api/verify/run")
def trigger_verify():
    return _start_step("verify")


@app.post("/api/evaluate/run")
def trigger_evaluate():
    return _start_step("evaluate")


@app.post("/api/submit/run")
def trigger_submit():
    return _start_step("submit")


@app.post("/api/pipeline/run")
def trigger_run():
    return _start_step("pipeline")


@app.post("/api/leads/clear")
def clear_leads():
    """Wipe all leads + evaluations + drafts (admin reset for a clean re-scout)."""
    with _pipeline_lock:
        if _pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="A run is in progress — wait for it to finish")
    with _db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        conn.execute("DELETE FROM outreach_drafts")
        conn.execute("DELETE FROM evaluations")
        conn.execute("DELETE FROM leads")
        conn.commit()
    return {"cleared": n}


@app.get("/api/export/xlsx")
def export_xlsx():
    """Download every lead (the accumulated list) as an .xlsx in the AthenaX
    project-list format — ready to import into Google Sheets."""
    from datetime import date
    from athenax.export import build_xlsx
    with _db() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY created_at").fetchall()
    data = build_xlsx([dict(r) for r in rows])
    fname = f"athenax_leads_{date.today().isoformat()}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>AthenaX Partnership Agent</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/@alpinejs/collapse@3.x.x/dist/cdn.min.js"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
  <style>
    body { font-family: 'Inter', sans-serif; }
    [x-cloak] { display: none !important; }
    .fade { animation: fadeIn .2s ease; }
    @keyframes fadeIn { from{opacity:0;transform:translateY(3px)} to{opacity:1;transform:translateY(0)} }
    .src-github   { background:#f0fdf4; color:#15803d; }
    .src-twitter  { background:#eff6ff; color:#1d4ed8; }
    .src-linkedin { background:#f0f9ff; color:#0369a1; }
    .src-web      { background:#faf5ff; color:#7e22ce; }
    .badge-new    { background:#fef9c3; color:#854d0e; }
    .badge-est    { background:#dbeafe; color:#1d4ed8; }
    .stage-active { background:#dcfce7; color:#15803d; }
    .stage-beta   { background:#fef9c3; color:#854d0e; }
    .stage-fund   { background:#ede9fe; color:#6d28d9; }
    .stage-other  { background:#f1f5f9; color:#475569; }
  </style>
</head>
<body class="bg-slate-50 min-h-screen" x-data="app()" x-init="init()">

<!-- Header -->
<header class="bg-white border-b border-slate-200 sticky top-0 z-20 shadow-sm">
  <div class="max-w-4xl mx-auto px-6 h-14 flex items-center justify-between">
    <div class="flex items-center gap-2.5">
      <div class="w-7 h-7 bg-indigo-600 rounded-md flex items-center justify-center">
        <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
        </svg>
      </div>
      <span class="font-bold text-slate-800 text-sm">AthenaX Partnership Agent</span>
    </div>
    <div class="flex items-center gap-3">
      <span class="text-xs text-slate-400" x-text="lastRefresh"></span>
      <!-- Scout: discover + save leads only -->
      <button @click="runScout()" :disabled="pipelineRunning" title="Discover and save new leads (no scoring)"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
        :class="pipelineRunning ? 'bg-indigo-50 border border-indigo-200 text-indigo-400 cursor-not-allowed' : 'bg-indigo-600 hover:bg-indigo-700 text-white'">
        <svg x-show="runningStep !== 'scout'" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
        </svg>
        <svg x-show="runningStep === 'scout'" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span x-text="runningStep === 'scout' ? 'Scouting…' : 'Scout'"></span>
      </button>
      <!-- Evaluate: score all unevaluated leads -->
      <button @click="runEvaluate()" :disabled="pipelineRunning" title="Score every lead that has no evaluation yet"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
        :class="pipelineRunning ? 'bg-green-50 border border-green-200 text-green-400 cursor-not-allowed' : 'bg-green-600 hover:bg-green-700 text-white'">
        <svg x-show="runningStep !== 'evaluate'" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
        </svg>
        <svg x-show="runningStep === 'evaluate'" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span x-text="runningStep === 'evaluate' ? 'Evaluating…' : 'Evaluate'"></span>
      </button>
      <!-- Verify: check URLs, assign certainty -->
      <button @click="runVerify()" :disabled="pipelineRunning" title="Verify team/project URLs and assign certainty scores"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
        :class="pipelineRunning ? 'bg-orange-50 border border-orange-200 text-orange-400 cursor-not-allowed' : 'bg-orange-500 hover:bg-orange-600 text-white'">
        <svg x-show="runningStep !== 'verify'" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
        </svg>
        <svg x-show="runningStep === 'verify'" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span x-text="runningStep === 'verify' ? 'Verifying…' : 'Verify'"></span>
      </button>
      <!-- Submit: push evaluated leads to athenax.co via Internal API -->
      <button @click="runSubmit()" :disabled="pipelineRunning" title="Push evaluated leads to athenax.co (skips already-submitted)"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
        :class="pipelineRunning ? 'bg-violet-50 border border-violet-200 text-violet-400 cursor-not-allowed' : 'bg-violet-600 hover:bg-violet-700 text-white'">
        <svg x-show="runningStep !== 'submit'" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
        </svg>
        <svg x-show="runningStep === 'submit'" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span x-text="runningStep === 'submit' ? 'Submitting…' : 'Submit'"></span>
      </button>
      <!-- Export: download the full accumulated lead list as .xlsx (import into Google Sheets) -->
      <a href="/api/export/xlsx"
        title="Download all leads as .xlsx — import into Google Sheets"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"/>
        </svg>
        Export
      </a>
      <button @click="refresh()"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors">
        <svg class="w-3.5 h-3.5" :class="loading && 'animate-spin'" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
        Refresh
      </button>
      <!-- Clear: wipe all leads + evaluations for a clean re-scout -->
      <button @click="clearLeads()" :disabled="pipelineRunning" title="Delete ALL leads and evaluations from the database"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-red-200 text-red-500 hover:bg-red-50 transition-colors">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
        </svg>
        Clear
      </button>
    </div>
  </div>
</header>

<!-- Stats + summary -->
<div class="max-w-4xl mx-auto px-6 mt-5">
  <div class="grid grid-cols-4 gap-3 mb-4">
    <div class="bg-white rounded-xl border border-slate-200 px-4 py-3">
      <p class="text-xs text-slate-500 font-medium">Total Leads</p>
      <p class="text-2xl font-bold text-slate-800 mt-0.5" x-text="stats.total_leads"></p>
    </div>
    <div class="bg-white rounded-xl border border-slate-200 px-4 py-3">
      <p class="text-xs text-slate-500 font-medium">Verified</p>
      <p class="text-2xl font-bold text-orange-500 mt-0.5" x-text="stats.verified ?? 0"></p>
    </div>
    <div class="bg-white rounded-xl border border-slate-200 px-4 py-3">
      <p class="text-xs text-slate-500 font-medium">Evaluated</p>
      <p class="text-2xl font-bold text-indigo-600 mt-0.5" x-text="stats.evaluations"></p>
    </div>
    <div class="bg-white rounded-xl border border-slate-200 px-4 py-3">
      <p class="text-xs text-slate-500 font-medium">Score ≥ 80</p>
      <p class="text-2xl font-bold text-green-600 mt-0.5" x-text="stats.high_score"></p>
    </div>
  </div>

  <!-- Filter bar -->
  <div class="flex gap-2 mb-4 flex-wrap">
    <input x-model="search" type="text" placeholder="Search projects…"
      class="flex-1 min-w-48 text-sm border border-slate-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-200 bg-white"/>
    <select x-model="filterCat" class="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200">
      <option value="">All Categories</option>
      <option>AI & Agents</option>
      <option>Biotech</option>
      <option>Crypto</option>
      <option>Developer Tools</option>
      <option>Infrastructure</option>
      <option>Robotics</option>
      <option>RWA</option>
    </select>
    <select x-model="filterEval" class="text-sm border border-slate-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-200">
      <option value="">All</option>
      <option value="evaluated">Evaluated only</option>
      <option value="pending">Not evaluated</option>
    </select>
  </div>

  <div x-show="errorMsg" x-cloak class="mb-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-2">
    ⚠️ <span x-text="errorMsg"></span>
  </div>

  <!-- Pipeline result banner -->
  <div x-show="pipelineMsg" x-cloak
       class="mb-4 text-sm rounded-lg px-4 py-2 flex items-start justify-between gap-3"
       :class="pipelineMsgType==='error' ? 'bg-red-50 border border-red-200 text-red-700'
             : pipelineMsgType==='warn'  ? 'bg-amber-50 border border-amber-200 text-amber-700'
             :                             'bg-green-50 border border-green-200 text-green-700'">
    <span x-text="pipelineMsg"></span>
    <button @click="pipelineMsg=''" class="opacity-50 hover:opacity-100 flex-shrink-0">✕</button>
  </div>

  <!-- Lead count -->
  <p class="text-xs text-slate-400 mb-3" x-text="filtered.length + ' projects'"></p>
</div>

<!-- Lead list -->
<div class="max-w-4xl mx-auto px-6 pb-20 space-y-2">
  <div x-show="filtered.length === 0 && !loading"
       class="bg-white rounded-xl border border-slate-200 p-16 text-center text-slate-400 text-sm fade">
    No projects yet — run the pipeline to start.
  </div>

  <template x-for="lead in filtered" :key="lead.id">
    <div class="bg-white rounded-xl border border-slate-200 hover:border-slate-300 transition-colors fade"
         x-data="{ open: false }">

      <!-- ── Compact row (always visible) ── -->
      <div class="px-4 py-3 flex items-center gap-3 cursor-pointer select-none" @click="open = !open">

        <!-- Score badge -->
        <div class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0"
             :class="lead.compatibility_score >= 80 ? 'bg-green-50 text-green-700' :
                     lead.compatibility_score >= 60 ? 'bg-amber-50 text-amber-700' :
                     lead.compatibility_score        ? 'bg-slate-100 text-slate-500' :
                                                       'bg-slate-50 text-slate-300'"
             x-text="lead.compatibility_score || '—'"></div>

        <!-- Name + one-liner -->
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-semibold text-slate-800 text-sm truncate" x-text="lead.name"></span>
            <!-- Category -->
            <span x-show="lead.sector" class="text-xs px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-600 font-medium" x-text="lead.sector"></span>
            <!-- Subcategory -->
            <span x-show="lead.subcategory" class="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-500" x-text="lead.subcategory"></span>
            <!-- Stage -->
            <span x-show="lead.stage" class="text-xs px-1.5 py-0.5 rounded font-medium"
                  :class="stageClass(lead.stage)" x-text="lead.stage"></span>
            <!-- Founded -->
            <span x-show="has(lead.founded)" class="text-xs text-slate-400" x-text="'est. ' + lead.founded"></span>
            <!-- Certainty badge: score + label, tooltip shows note -->
            <span x-show="lead.certainty"
                  class="text-xs px-1.5 py-0.5 rounded font-medium cursor-default"
                  :class="lead.certainty === 'high'   ? 'bg-emerald-50 text-emerald-600' :
                           lead.certainty === 'medium' ? 'bg-amber-50 text-amber-600' :
                                                         'bg-red-50 text-red-500'"
                  :title="lead.certainty_note || lead.certainty"
                  x-text="(lead.certainty_score != null ? lead.certainty_score + ' · ' : '') + lead.certainty"></span>
          </div>
          <p x-show="lead.short_description" class="text-xs text-slate-400 mt-0.5 truncate" x-text="lead.short_description"></p>
        </div>

        <!-- Quick signals -->
        <div class="hidden sm:flex items-center gap-3 text-xs text-slate-400 flex-shrink-0">
          <span x-show="lead.github_stars" x-text="'⭐ ' + (lead.github_stars||0).toLocaleString()"></span>
          <span x-show="lead.twitter_followers" x-text="'🐦 ' + (lead.twitter_followers||0).toLocaleString()"></span>
          <span class="px-1.5 py-0.5 rounded font-medium" :class="srcClass(lead.source)" x-text="lead.source"></span>
        </div>

        <!-- Expand chevron -->
        <svg class="w-4 h-4 text-slate-400 flex-shrink-0 transition-transform duration-200"
             :class="open && 'rotate-180'" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </div>

      <!-- ── Expanded detail ── -->
      <div x-show="open" x-collapse class="border-t border-slate-100">
        <div class="p-5 grid grid-cols-1 md:grid-cols-5 gap-6">

          <!-- LEFT: Profile (3/5) -->
          <div class="md:col-span-3 space-y-4">

            <!-- Description -->
            <div x-show="lead.description">
              <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">About</p>
              <p class="text-sm text-slate-700 leading-relaxed" x-text="lead.description"></p>
            </div>

            <!-- Links -->
            <div>
              <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Links</p>
              <div class="flex flex-wrap gap-2">
                <template x-if="has(lead.website) || has(lead.url)">
                  <a :href="has(lead.website) ? lead.website : lead.url" target="_blank"
                     class="text-xs px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 font-medium transition-colors">🌐 Website</a>
                </template>
                <template x-if="has(lead.github_url)">
                  <a :href="lead.github_url" target="_blank"
                     class="text-xs px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 font-medium transition-colors">
                    <span>GitHub</span>
                    <span x-show="lead.github_stars" class="text-slate-400 ml-1" x-text="'⭐'+lead.github_stars.toLocaleString()"></span>
                  </a>
                </template>
                <template x-if="has(lead.twitter_url)">
                  <a :href="lead.twitter_url" target="_blank"
                     class="text-xs px-2.5 py-1.5 rounded-lg bg-sky-50 hover:bg-sky-100 text-sky-600 font-medium transition-colors">𝕏 Twitter</a>
                </template>
                <template x-if="has(lead.discord_url)">
                  <a :href="lead.discord_url" target="_blank"
                     class="text-xs px-2.5 py-1.5 rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-600 font-medium transition-colors">Discord</a>
                </template>
                <template x-if="has(lead.docs_url)">
                  <a :href="lead.docs_url" target="_blank"
                     class="text-xs px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 font-medium transition-colors">📄 Docs</a>
                </template>
                <template x-for="link in (lead.other_links || [])" :key="link">
                  <a :href="link" target="_blank"
                     class="text-xs px-2.5 py-1.5 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-500 transition-colors" x-text="link.replace(/^https?:\/\//,'').split('/')[0]"></a>
                </template>
              </div>
            </div>

            <!-- Backers -->
            <div x-show="lead.backers?.length">
              <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Backers</p>
              <div class="flex flex-wrap gap-1.5">
                <template x-for="b in (lead.backers || [])" :key="b">
                  <span class="text-xs px-2 py-1 rounded-lg bg-violet-50 text-violet-700 font-medium" x-text="b"></span>
                </template>
              </div>
            </div>

            <!-- Team -->
            <div x-show="lead.team?.length">
              <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Team</p>
              <div class="space-y-2">
                <template x-for="member in (lead.team || [])" :key="member.name">
                  <div class="flex items-start gap-3 p-2.5 rounded-lg bg-slate-50">
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2 flex-wrap">
                        <span class="text-sm font-semibold text-slate-800" x-text="member.name"></span>
                        <span class="text-xs text-slate-500" x-text="member.title"></span>
                        <template x-if="has(member.linkedin)">
                          <a :href="member.linkedin" target="_blank" class="text-xs text-blue-500 hover:underline">LinkedIn</a>
                        </template>
                        <template x-if="has(member.twitter)">
                          <a :href="member.twitter.startsWith('http') ? member.twitter : 'https://x.com/' + member.twitter.replace('@','')" target="_blank" class="text-xs text-sky-500 hover:underline">Twitter</a>
                        </template>
                      </div>
                      <p x-show="member.bio" class="text-xs text-slate-500 mt-1 leading-relaxed" x-text="member.bio"></p>
                    </div>
                  </div>
                </template>
              </div>
            </div>

            <!-- Voices -->
            <div x-show="lead.voices?.length">
              <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Voices</p>
              <div class="space-y-1.5">
                <template x-for="v in (lead.voices || [])" :key="v.url">
                  <div class="flex items-start gap-2 text-xs">
                    <span class="font-medium text-slate-600 flex-shrink-0" x-text="v.source"></span>
                    <span class="text-slate-400" x-text="v.summary"></span>
                    <a :href="v.url" target="_blank" class="text-indigo-400 hover:underline flex-shrink-0">↗</a>
                  </div>
                </template>
              </div>
            </div>

            <!-- Bounties -->
            <div x-show="lead.bounties?.length">
              <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Bounties</p>
              <div class="space-y-2">
                <template x-for="b in (lead.bounties || [])" :key="b.title">
                  <div class="p-2.5 rounded-lg bg-amber-50 border border-amber-100">
                    <div class="flex items-center gap-2">
                      <span class="text-xs font-semibold text-amber-800" x-text="b.title"></span>
                      <span x-show="b.reward" class="text-xs text-amber-600 font-medium" x-text="b.reward"></span>
                    </div>
                    <p x-show="b.description" class="text-xs text-amber-700 mt-0.5" x-text="b.description"></p>
                  </div>
                </template>
              </div>
            </div>

          </div>

          <!-- RIGHT: Evaluation (2/5) -->
          <div class="md:col-span-2 space-y-4">

            <!-- Not evaluated yet -->
            <div x-show="!lead.eval_id" class="p-4 rounded-xl border border-dashed border-slate-200 text-center">
              <p class="text-xs text-slate-400">Not evaluated yet</p>
            </div>

            <!-- Evaluation detail -->
            <template x-if="lead.eval_id">
              <div class="space-y-4">

                <!-- Score + reason -->
                <div class="p-3 rounded-xl bg-slate-50">
                  <div class="flex items-center gap-3 mb-2">
                    <div class="w-12 h-12 rounded-full flex items-center justify-center font-bold text-base flex-shrink-0"
                         :class="lead.compatibility_score >= 80 ? 'bg-green-100 text-green-700' :
                                 lead.compatibility_score >= 60 ? 'bg-amber-100 text-amber-700' :
                                                                   'bg-slate-100 text-slate-500'"
                         x-text="lead.compatibility_score"></div>
                    <div>
                      <p class="text-xs font-semibold text-slate-700">Compatibility Score</p>
                      <span class="text-xs px-1.5 py-0.5 rounded font-medium capitalize"
                            :class="lead.details?.project_type === 'new' ? 'badge-new' : 'badge-est'"
                            x-text="lead.details?.project_type || ''"></span>
                    </div>
                  </div>
                  <p class="text-xs text-slate-600 leading-relaxed" x-text="lead.reason_for_partnership"></p>
                </div>

                <!-- Score breakdown -->
                <div x-show="lead.details?.score_breakdown">
                  <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Score Breakdown</p>
                  <div class="grid grid-cols-3 gap-2 text-center mb-2">
                    <div class="bg-slate-50 rounded-lg py-2">
                      <p class="text-xs text-slate-400">Base</p>
                      <p class="text-sm font-bold text-slate-700" x-text="lead.details?.score_breakdown?.base_score ?? '—'"></p>
                    </div>
                    <div class="bg-slate-50 rounded-lg py-2">
                      <p class="text-xs text-slate-400">Boosters</p>
                      <p class="text-sm font-bold text-indigo-600" x-text="lead.details?.score_breakdown?.booster_points ? '+'+lead.details.score_breakdown.booster_points : '—'"></p>
                    </div>
                    <div class="bg-slate-50 rounded-lg py-2">
                      <p class="text-xs text-slate-400">Velocity</p>
                      <p class="text-sm font-bold text-emerald-600" x-text="lead.details?.score_breakdown?.velocity_multiplier ?? '—'"></p>
                    </div>
                  </div>
                  <div x-show="lead.details?.score_breakdown?.boosters_detail?.length" class="space-y-1">
                    <template x-for="b in (lead.details?.score_breakdown?.boosters_detail || [])" :key="b.signal">
                      <div class="flex items-center gap-1.5 text-xs">
                        <span class="bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded font-medium" x-text="'+'+b.points"></span>
                        <span class="font-medium text-slate-600" x-text="b.signal"></span>
                      </div>
                    </template>
                  </div>
                </div>

                <!-- Criteria -->
                <div x-show="lead.details?.criteria_detail">
                  <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Criteria</p>
                  <div class="space-y-1">
                    <template x-for="[key, val] in Object.entries(lead.details?.criteria_detail || {})" :key="key">
                      <div class="flex items-start gap-2 text-xs">
                        <span class="flex-shrink-0"
                              :class="val?.met === true ? 'text-green-500' : val?.met === false ? 'text-red-400' : 'text-slate-300'"
                              x-text="val?.met === true ? '✓' : val?.met === false ? '✗' : '?'"></span>
                        <span class="font-medium text-slate-600 capitalize w-24 flex-shrink-0" x-text="key.replace(/_/g,' ')"></span>
                        <span class="text-slate-400 leading-relaxed" x-text="val?.note || '—'"></span>
                      </div>
                    </template>
                  </div>
                </div>

                <!-- Velocity -->
                <div x-show="lead.details?.velocity_assessment">
                  <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Velocity</p>
                  <p class="text-xs text-slate-500 italic leading-relaxed" x-text="lead.details?.velocity_assessment"></p>
                </div>

                <!-- Listing fit -->
                <div x-show="lead.listing_fit_notes">
                  <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Listing Fit</p>
                  <p class="text-xs text-slate-500 leading-relaxed" x-text="lead.listing_fit_notes"></p>
                </div>

                <!-- BD contacts -->
                <div x-show="lead.bd_twitter_handles?.length">
                  <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">BD Contacts</p>
                  <div class="space-y-1.5">
                    <template x-for="h in (lead.bd_twitter_handles || [])" :key="h.handle">
                      <a :href="'https://x.com/' + h.handle.replace('@','')" target="_blank"
                         class="flex items-center gap-2 text-xs bg-sky-50 border border-sky-100 text-sky-700 rounded-lg px-2.5 py-1.5 hover:bg-sky-100 transition-colors">
                        <span class="font-semibold" x-text="h.handle"></span>
                        <span class="text-sky-400 capitalize" x-text="h.role"></span>
                        <span x-show="h.followers" class="ml-auto text-sky-400" x-text="Number(h.followers).toLocaleString()"></span>
                      </a>
                    </template>
                  </div>
                </div>

                <!-- Contact email -->
                <div x-show="has(lead.contact_email)">
                  <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-1">Contact Email</p>
                  <a :href="'mailto:' + lead.contact_email"
                     class="text-xs text-indigo-500 hover:underline" x-text="lead.contact_email"></a>
                </div>

              </div>
            </template>

          </div>
        </div>
      </div>
    </div>
  </template>
</div>

<script>
function app() {
  return {
    loading: false,
    lastRefresh: '',
    errorMsg: '',
    stats: { total_leads: 0, evaluations: 0, high_score: 0 },
    allLeads: [],
    search: '',
    filterCat: '',
    filterEval: '',
    pipelineRunning: false,
    runningStep: null,
    pipelineMsg: '',
    pipelineMsgType: 'ok',
    _pollTimer: null,

    get filtered() {
      return this.allLeads.filter(l => {
        if (this.search) {
          const q = this.search.toLowerCase();
          if (!(l.name||'').toLowerCase().includes(q) &&
              !(l.short_description||'').toLowerCase().includes(q) &&
              !(l.description||'').toLowerCase().includes(q) &&
              !(l.subcategory||'').toLowerCase().includes(q)) return false;
        }
        if (this.filterCat && l.sector !== this.filterCat) return false;
        if (this.filterEval === 'evaluated' && !l.eval_id) return false;
        if (this.filterEval === 'pending'   &&  l.eval_id) return false;
        return true;
      });
    },

    async init() {
      await this.refresh();
      await this.checkPipelineStatus();
      // If a run is already in flight (e.g. started in another tab), poll it.
      if (this.pipelineRunning && !this._pollTimer) {
        this._pollTimer = setInterval(() => this.checkPipelineStatus(), 10000);
      }
      setInterval(() => this.refresh(), 30000);
    },

    async checkPipelineStatus() {
      try {
        const s = await this.getJSON('/api/pipeline/status');
        const was = this.pipelineRunning;
        this.pipelineRunning = s.running;
        this.runningStep = s.step;
        if (was && !s.running) {
          await this.refresh();
          clearInterval(this._pollTimer);
          this._pollTimer = null;
          this.showPipelineResult(s);
        }
      } catch(e) {}
    },

    showPipelineResult(s) {
      const label = { scout: 'Scout', verify: 'Verify', evaluate: 'Evaluate', submit: 'Submit', pipeline: 'Pipeline' }[s.last_step] || 'Run';
      const noun  = s.last_step === 'evaluate' ? 'evaluation'
                  : s.last_step === 'submit'   ? 'submission'
                  : s.last_step === 'verify'   ? 'lead verified'
                  : 'lead';
      if (s.last_status === 'error') {
        this.pipelineMsg = `${label} failed: ` + (s.last_error || 'unknown error');
        this.pipelineMsgType = 'error';
      } else if (s.last_status === 'ok') {
        const n = s.last_added;
        if (n > 0) {
          this.pipelineMsg = `${label} finished — ${n} ${noun}${n===1?'':'s'} (${s.last_total} total).`;
          this.pipelineMsgType = 'ok';
        } else if (s.last_step === 'evaluate') {
          this.pipelineMsg = `${label} finished — no new evaluations (nothing pending, or none scored ≥ 55). Check the logs.`;
          this.pipelineMsgType = 'warn';
        } else if (s.last_step === 'verify') {
          this.pipelineMsg = `${label} finished — all ${s.last_total} leads already verified.`;
          this.pipelineMsgType = 'warn';
        } else if (s.last_step === 'submit') {
          this.pipelineMsg = `${label} finished — all leads already submitted (or none scouted yet).`;
          this.pipelineMsgType = 'warn';
        } else {
          this.pipelineMsg = `${label} finished — no new leads saved. Output may have been empty or unparseable; check the logs.`;
          this.pipelineMsgType = 'warn';
        }
      }
    },

    runScout()    { return this._startStep('/api/scout/run',    'Scout'); },
    runVerify()   { return this._startStep('/api/verify/run',   'Verify'); },
    runEvaluate() { return this._startStep('/api/evaluate/run', 'Evaluate'); },
    runSubmit()   { return this._startStep('/api/submit/run',   'Submit'); },

    async clearLeads() {
      if (this.pipelineRunning) return;
      if (!confirm('Delete ALL leads and evaluations from the database? This cannot be undone.')) return;
      try {
        const r = await fetch('/api/leads/clear', { method: 'POST' });
        if (r.ok) {
          const d = await r.json();
          this.pipelineMsg = `Cleared ${d.cleared} lead${d.cleared===1?'':'s'} and their evaluations.`;
          this.pipelineMsgType = 'warn';
          await this.refresh();
        } else {
          const d = await r.json().catch(() => ({}));
          this.errorMsg = d.detail || 'Failed to clear';
        }
      } catch(e) { this.errorMsg = 'Failed to clear'; }
    },

    async _startStep(url, label) {
      if (this.pipelineRunning) return;
      try {
        const r = await fetch(url, { method: 'POST' });
        if (r.ok) {
          this.pipelineRunning = true;
          const d = await r.json();
          this.runningStep = d.step;
          this._pollTimer = setInterval(() => this.checkPipelineStatus(), 10000);
        } else {
          const d = await r.json().catch(() => ({}));
          this.errorMsg = d.detail || ('Failed to start ' + label);
        }
      } catch(e) { this.errorMsg = 'Failed to start ' + label; }
    },

    async getJSON(url) {
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) throw new Error(url + ' → HTTP ' + r.status);
      return r.json();
    },

    async refresh() {
      this.loading = true;
      this.errorMsg = '';
      try {
        try { this.stats    = await this.getJSON('/api/stats'); } catch(e) { this.errorMsg = e.message; }
        try { this.allLeads = await this.getJSON('/api/leads'); } catch(e) { this.errorMsg = e.message; }
        this.lastRefresh = 'Updated ' + new Date().toLocaleTimeString();
      } finally { this.loading = false; }
    },

    // Treat the Scout's "not found" placeholder (and empty values) as absent.
    has(v) {
      return v != null && v !== '' && v !== 'not found' && v !== 'Not Found';
    },

    srcClass(s) {
      return { github:'src-github', twitter:'src-twitter', linkedin:'src-linkedin' }[s] || 'src-web';
    },

    stageClass(s) {
      if (!s) return 'stage-other';
      const sl = s.toLowerCase();
      if (sl.includes('active')) return 'stage-active';
      if (sl === 'beta')         return 'stage-beta';
      if (sl.includes('seed') || sl.includes('series')) return 'stage-fund';
      return 'stage-other';
    },
  };
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def root():
    return HTML


def run():
    import uvicorn
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    print(f"\n🚀  Dashboard → http://localhost:{port}\n")
    dev_mode = os.getenv("DASHBOARD_DEV", "false").lower() == "true"
    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=port, reload=dev_mode)


if __name__ == "__main__":
    run()
