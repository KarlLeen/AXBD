"""AthenaX Partnership Agent — Admin Dashboard."""
import json
import os
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

load_dotenv()

app = FastAPI(title="AthenaX Dashboard", docs_url=None, redoc_url=None)

# ── Pipeline run state ────────────────────────────────────────────────────────
_pipeline_state = {
    "running": False,
    "last_run": None,       # ISO timestamp
    "last_status": None,    # "ok" | "error"
    "last_error": None,
}
_pipeline_lock = threading.Lock()


def _run_pipeline_bg():
    from athenax.main import run_pipeline
    with _pipeline_lock:
        _pipeline_state["running"] = True
        _pipeline_state["last_error"] = None
    try:
        run_pipeline()
        with _pipeline_lock:
            _pipeline_state["last_status"] = "ok"
    except Exception as exc:
        with _pipeline_lock:
            _pipeline_state["last_status"] = "error"
            _pipeline_state["last_error"] = str(exc)
    finally:
        with _pipeline_lock:
            _pipeline_state["running"] = False
            _pipeline_state["last_run"] = datetime.now(timezone.utc).isoformat()


@app.middleware("http")
async def no_cache(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


def _db():
    from athenax.db.database import get_connection
    return get_connection()


# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def stats():
    with _db() as conn:
        return {
            "total_leads":  conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
            "evaluations":  conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0],
            "pending":      conn.execute("SELECT COUNT(*) FROM outreach_drafts WHERE status='pending'").fetchone()[0],
            "approved":     conn.execute("SELECT COUNT(*) FROM outreach_drafts WHERE status='approved'").fetchone()[0],
            "rejected":     conn.execute("SELECT COUNT(*) FROM outreach_drafts WHERE status='rejected'").fetchone()[0],
        }


@app.get("/api/pipeline")
def pipeline():
    """Return Scout / Evaluator / Writer outputs in one call."""
    with _db() as conn:
        # Agent A — all leads
        scout = [dict(r) for r in conn.execute("""
            SELECT id, source, name, url, description,
                   github_stars, github_forks, commits_last_30d,
                   twitter_handle, twitter_followers, twitter_recent_tweet,
                   linkedin_profile, linkedin_recent_post,
                   tech_stack, created_at
            FROM leads ORDER BY created_at DESC LIMIT 50
        """).fetchall()]

        # Agent B — evaluations (joined with lead name)
        evaluator = [dict(r) for r in conn.execute("""
            SELECT e.id, e.lead_id, e.compatibility_score,
                   e.nounish_traits, e.reason_for_partnership,
                   e.listing_fit_notes, e.created_at,
                   l.name AS lead_name, l.url AS lead_url, l.source AS lead_source,
                   l.github_stars, l.commits_last_30d
            FROM evaluations e
            JOIN leads l ON e.lead_id = l.id
            ORDER BY e.compatibility_score DESC
        """).fetchall()]

        # Agent C — all drafts (all statuses)
        writer = [dict(r) for r in conn.execute("""
            SELECT od.id, od.channel, od.subject, od.body,
                   od.status, od.approved_at, od.created_at,
                   l.name AS lead_name, l.url AS lead_url,
                   l.twitter_handle, l.source AS lead_source,
                   e.compatibility_score, e.reason_for_partnership
            FROM outreach_drafts od
            JOIN leads l       ON od.lead_id       = l.id
            JOIN evaluations e ON od.evaluation_id = e.id
            ORDER BY e.compatibility_score DESC
        """).fetchall()]

    # Parse JSON fields
    for e in evaluator:
        if e["nounish_traits"]:
            try: e["nounish_traits"] = json.loads(e["nounish_traits"])
            except: e["nounish_traits"] = []
    for s in scout:
        if s["tech_stack"]:
            try: s["tech_stack"] = json.loads(s["tech_stack"])
            except: s["tech_stack"] = []

    return {"scout": scout, "evaluator": evaluator, "writer": writer}


@app.get("/api/pipeline/status")
def pipeline_status():
    with _pipeline_lock:
        return dict(_pipeline_state)


@app.post("/api/pipeline/run")
def trigger_run():
    with _pipeline_lock:
        if _pipeline_state["running"]:
            raise HTTPException(status_code=409, detail="Pipeline already running")
    t = threading.Thread(target=_run_pipeline_bg, daemon=True)
    t.start()
    return {"started": True}


@app.get("/api/pending")
def pending_drafts():
    with _db() as conn:
        rows = conn.execute("""
            SELECT od.id, od.channel, od.subject, od.body, od.status, od.created_at,
                   l.name AS lead_name, l.url AS lead_url, l.source AS lead_source,
                   l.twitter_handle, l.github_stars, l.commits_last_30d,
                   l.remote_lead_id,
                   e.compatibility_score, e.nounish_traits,
                   e.reason_for_partnership, e.listing_fit_notes,
                   e.lead_id, e.id AS evaluation_id
            FROM outreach_drafts od
            JOIN leads       l ON od.lead_id       = l.id
            JOIN evaluations e ON od.evaluation_id = e.id
            WHERE od.status = 'pending'
            ORDER BY e.compatibility_score DESC
        """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["lead_id"] = d.pop("lead_id", None)
        d["evaluation_id"] = d.pop("evaluation_id", None)
        if d.get("nounish_traits"):
            try: d["nounish_traits"] = json.loads(d["nounish_traits"])
            except: d["nounish_traits"] = []
        result.append(d)
    return result


@app.post("/api/drafts/{draft_id}/approve")
def approve(draft_id: str):
    with _db() as conn:
        row = conn.execute("""
            SELECT od.id, od.lead_id, od.evaluation_id, od.channel, od.subject, od.body,
                   l.name AS lead_name, l.url AS lead_url, l.source AS lead_source,
                   l.tech_stack, l.twitter_handle, l.remote_lead_id,
                   e.compatibility_score, e.nounish_traits,
                   e.reason_for_partnership, e.listing_fit_notes
            FROM outreach_drafts od
            JOIN leads       l ON od.lead_id       = l.id
            JOIN evaluations e ON od.evaluation_id = e.id
            WHERE od.id = ?
        """, (draft_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")
    from athenax.cli.review import _approve
    from athenax.api.athenax_client import AthenaXClient
    try:
        _approve(dict(row), AthenaXClient())
        return {"status": "approved"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/drafts/{draft_id}/reject")
def reject(draft_id: str):
    with _db() as conn:
        if not conn.execute("SELECT id FROM outreach_drafts WHERE id=?", (draft_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Draft not found")
        conn.execute("UPDATE outreach_drafts SET status='rejected' WHERE id=?", (draft_id,))
        conn.commit()
    return {"status": "rejected"}


@app.put("/api/drafts/{draft_id}/body")
def update_body(draft_id: str, payload: dict):
    new_body = payload.get("body", "").strip()
    if not new_body:
        raise HTTPException(status_code=400, detail="body cannot be empty")
    with _db() as conn:
        conn.execute("UPDATE outreach_drafts SET body=? WHERE id=?", (new_body, draft_id))
        conn.commit()
    return {"status": "updated"}


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>AthenaX Partnership Agent</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
  <style>
    body { font-family: 'Inter', sans-serif; }
    [x-cloak] { display: none !important; }
    .fade { animation: fadeIn .25s ease; }
    @keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
    .step-connector { background: linear-gradient(90deg,#6366f1,#8b5cf6); }
    .source-github  { background:#f0fdf4; color:#15803d; }
    .source-twitter { background:#eff6ff; color:#1d4ed8; }
    .source-linkedin{ background:#f0f9ff; color:#0369a1; }
    .source-web     { background:#faf5ff; color:#7e22ce; }
    .ch-twitter     { background:#e0f2fe; color:#0369a1; }
    .ch-email       { background:#f0fdf4; color:#15803d; }
    .status-pending  { background:#fefce8; color:#a16207; }
    .status-approved { background:#f0fdf4; color:#15803d; }
    .status-rejected { background:#fef2f2; color:#b91c1c; }
  </style>
</head>
<body class="bg-slate-50 min-h-screen" x-data="app()" x-init="init()">

<!-- Header -->
<header class="bg-white border-b border-slate-200 sticky top-0 z-20 shadow-sm">
  <div class="max-w-screen-xl mx-auto px-6 h-14 flex items-center justify-between">
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
      <!-- Run Pipeline button -->
      <button @click="runPipeline()" :disabled="pipelineRunning"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium transition-colors"
        :class="pipelineRunning
          ? 'bg-indigo-50 border border-indigo-200 text-indigo-400 cursor-not-allowed'
          : 'bg-indigo-600 hover:bg-indigo-700 text-white'">
        <svg x-show="!pipelineRunning" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
        </svg>
        <svg x-show="pipelineRunning" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span x-text="pipelineRunning ? 'Running…' : 'Run Pipeline'"></span>
      </button>
      <button @click="refresh()"
        class="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 transition-colors">
        <svg class="w-3.5 h-3.5" :class="loading&&'animate-spin'" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
        Refresh
      </button>
    </div>
  </div>
</header>

<!-- Stats bar -->
<div class="max-w-screen-xl mx-auto px-6 mt-5">
  <div class="grid grid-cols-5 gap-3">
    <template x-for="s in statCards" :key="s.label">
      <div class="bg-white rounded-xl border border-slate-200 px-4 py-3 fade">
        <p class="text-xs text-slate-500 font-medium" x-text="s.label"></p>
        <p class="text-2xl font-bold mt-0.5" :class="s.color" x-text="s.value"></p>
      </div>
    </template>
  </div>
  <div x-show="errorMsg" x-cloak
       class="mt-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-2">
    ⚠️ <span x-text="errorMsg"></span>
  </div>
</div>

<!-- Tab bar -->
<div class="max-w-screen-xl mx-auto px-6 mt-5">
  <div class="flex gap-1 bg-slate-100 rounded-xl p-1 w-fit">
    <template x-for="t in tabs" :key="t.id">
      <button @click="tab=t.id"
        :class="tab===t.id ? 'bg-white shadow-sm text-slate-900 font-semibold' : 'text-slate-500 hover:text-slate-700'"
        class="flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all">
        <span x-text="t.icon"></span>
        <span x-text="t.label"></span>
        <span x-show="t.id==='review' && stats.pending>0"
              class="bg-indigo-600 text-white text-xs px-1.5 py-0.5 rounded-full font-bold"
              x-text="stats.pending"></span>
      </button>
    </template>
  </div>
</div>

<!-- ════════════ PIPELINE TAB ════════════ -->
<div class="max-w-screen-xl mx-auto px-6 mt-5 pb-16" x-show="tab==='pipeline'" x-cloak>

  <!-- Step headers -->
  <div class="grid grid-cols-3 gap-4 mb-4">
    <template x-for="(step, i) in steps" :key="step.id">
      <div class="flex items-center gap-3 bg-white rounded-xl border border-slate-200 px-4 py-3">
        <div class="w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold flex-shrink-0"
             :class="step.bg" x-text="i+1"></div>
        <div>
          <p class="font-semibold text-slate-800 text-sm" x-text="step.name"></p>
          <p class="text-xs text-slate-400" x-text="step.desc"></p>
        </div>
        <div class="ml-auto text-lg font-bold" :class="step.color" x-text="step.count"></div>
      </div>
    </template>
  </div>

  <!-- Three columns -->
  <div class="grid grid-cols-3 gap-4 items-start">

    <!-- Agent A: Scout -->
    <div class="space-y-2 fade">
      <div x-show="pipeline.scout.length===0" class="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-400 text-sm">
        No leads yet — run the pipeline
      </div>
      <template x-for="l in pipeline.scout" :key="l.id">
        <div class="bg-white rounded-xl border border-slate-200 p-3.5 hover:border-slate-300 transition-colors">
          <div class="flex items-start gap-2">
            <span class="text-xs px-1.5 py-0.5 rounded font-medium flex-shrink-0"
                  :class="sourceClass(l.source)" x-text="l.source"></span>
            <div class="min-w-0">
              <a :href="l.url" target="_blank"
                 class="text-sm font-semibold text-slate-800 hover:text-indigo-600 truncate block"
                 x-text="l.name"></a>
              <p class="text-xs text-slate-400 mt-0.5 line-clamp-2" x-text="l.description||'No description'"></p>
            </div>
          </div>
          <!-- Signals -->
          <div class="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
            <template x-if="l.github_stars">
              <span>⭐ <span x-text="l.github_stars?.toLocaleString()"></span></span>
            </template>
            <template x-if="l.commits_last_30d !== null && l.commits_last_30d !== undefined">
              <span>🔨 <span x-text="l.commits_last_30d"></span>/30d</span>
            </template>
            <template x-if="l.twitter_followers">
              <span>🐦 <span x-text="l.twitter_followers?.toLocaleString()"></span></span>
            </template>
          </div>
          <!-- Recent tweet / post -->
          <template x-if="l.twitter_recent_tweet">
            <p class="mt-2 text-xs text-slate-400 italic line-clamp-2 border-l-2 border-slate-100 pl-2"
               x-text="l.twitter_recent_tweet"></p>
          </template>
          <template x-if="l.linkedin_recent_post && !l.twitter_recent_tweet">
            <p class="mt-2 text-xs text-slate-400 italic line-clamp-2 border-l-2 border-slate-100 pl-2"
               x-text="l.linkedin_recent_post"></p>
          </template>
          <!-- Tech tags -->
          <div x-show="l.tech_stack?.length" class="mt-2 flex flex-wrap gap-1">
            <template x-for="t in (l.tech_stack||[])" :key="t">
              <span class="text-xs bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded" x-text="t"></span>
            </template>
          </div>
        </div>
      </template>
    </div>

    <!-- Agent B: Evaluator -->
    <div class="space-y-2 fade">
      <div x-show="pipeline.evaluator.length===0" class="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-400 text-sm">
        No evaluations yet
      </div>
      <template x-for="e in pipeline.evaluator" :key="e.id">
        <div class="bg-white rounded-xl border border-slate-200 p-3.5 hover:border-indigo-200 transition-colors">
          <!-- Score + name -->
          <div class="flex items-center gap-2.5 mb-2">
            <div class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0"
                 :class="scoreRing(e.compatibility_score)"
                 x-text="e.compatibility_score"></div>
            <div class="min-w-0">
              <a :href="e.lead_url" target="_blank"
                 class="text-sm font-semibold text-slate-800 hover:text-indigo-600 truncate block"
                 x-text="e.lead_name"></a>
              <span class="text-xs px-1.5 py-0.5 rounded font-medium"
                    :class="sourceClass(e.lead_source)" x-text="e.lead_source"></span>
            </div>
          </div>
          <!-- Reason -->
          <p class="text-xs text-slate-600 leading-relaxed" x-text="e.reason_for_partnership"></p>
          <!-- Traits -->
          <div x-show="e.nounish_traits?.length" class="flex flex-wrap gap-1 mt-2">
            <template x-for="t in (e.nounish_traits||[])" :key="t">
              <span class="text-xs bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded" x-text="t"></span>
            </template>
          </div>
          <!-- Notes -->
          <p x-show="e.listing_fit_notes"
             class="mt-2 text-xs text-slate-400 border-t border-slate-100 pt-2"
             x-text="e.listing_fit_notes"></p>
        </div>
      </template>
    </div>

    <!-- Agent C: Writer -->
    <div class="space-y-2 fade">
      <div x-show="pipeline.writer.length===0" class="bg-white rounded-xl border border-slate-200 p-8 text-center text-slate-400 text-sm">
        No drafts yet
      </div>
      <template x-for="d in pipeline.writer" :key="d.id">
        <div class="bg-white rounded-xl border border-slate-200 p-3.5 hover:border-slate-300 transition-colors">
          <!-- Header -->
          <div class="flex items-center gap-2 mb-2">
            <span class="text-xs px-1.5 py-0.5 rounded font-medium"
                  :class="d.channel==='twitter_dm' ? 'ch-twitter' : 'ch-email'"
                  x-text="d.channel==='twitter_dm' ? '𝕏 DM' : '✉ Email'"></span>
            <span class="text-xs font-semibold text-slate-700 truncate flex-1" x-text="d.lead_name"></span>
            <span class="text-xs px-1.5 py-0.5 rounded font-medium"
                  :class="`status-${d.status}`" x-text="d.status"></span>
          </div>
          <!-- Subject -->
          <p x-show="d.subject" class="text-xs text-slate-500 mb-1.5">
            Subject: <span class="font-medium text-slate-700" x-text="d.subject"></span>
          </p>
          <!-- Body -->
          <p class="text-xs text-slate-600 bg-slate-50 rounded-lg p-2.5 whitespace-pre-wrap leading-relaxed max-h-36 overflow-y-auto"
             x-text="d.body"></p>
          <!-- Score -->
          <p class="text-xs text-slate-400 mt-1.5">Score: <span class="font-semibold" :class="scoreColor(d.compatibility_score)" x-text="d.compatibility_score + '/100'"></span></p>
        </div>
      </template>
    </div>
  </div>
</div>

<!-- ════════════ REVIEW TAB ════════════ -->
<div class="max-w-screen-xl mx-auto px-6 mt-5 pb-16" x-show="tab==='review'" x-cloak>
  <div x-show="pending.length===0 && !loading"
       class="bg-white rounded-xl border border-slate-200 p-16 text-center fade">
    <div class="w-12 h-12 bg-green-50 rounded-full flex items-center justify-center mx-auto">
      <svg class="w-6 h-6 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
      </svg>
    </div>
    <p class="mt-3 font-medium text-slate-500">No pending drafts</p>
    <p class="text-sm text-slate-400 mt-1">Run the pipeline to generate outreach drafts.</p>
  </div>

  <div class="space-y-4">
    <template x-for="d in pending" :key="d.id">
      <div class="bg-white rounded-xl border border-slate-200 overflow-hidden fade" x-show="!d._done">

        <!-- Card top -->
        <div class="px-5 py-4 border-b border-slate-100 flex items-start gap-3">
          <!-- Score -->
          <div class="w-12 h-12 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0"
               :class="scoreRing(d.compatibility_score)" x-text="d.compatibility_score||'—'"></div>
          <div class="flex-1 min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-semibold text-slate-900" x-text="d.lead_name"></span>
              <span class="text-xs px-1.5 py-0.5 rounded font-medium"
                    :class="d.channel==='twitter_dm' ? 'ch-twitter' : 'ch-email'"
                    x-text="d.channel==='twitter_dm' ? '𝕏 Twitter DM' : '✉ Email'"></span>
              <span class="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-600 capitalize" x-text="d.lead_source"></span>
            </div>
            <p class="text-xs text-slate-500 mt-0.5" x-text="d.reason_for_partnership"></p>
            <div class="flex flex-wrap items-center gap-3 mt-1">
              <a :href="d.lead_url" target="_blank" class="text-xs text-indigo-500 hover:underline truncate max-w-xs" x-text="d.lead_url"></a>
              <template x-if="d.github_stars"><span class="text-xs text-slate-400">⭐ <span x-text="d.github_stars?.toLocaleString()"></span></span></template>
              <template x-if="d.commits_last_30d!=null"><span class="text-xs text-slate-400">🔨 <span x-text="d.commits_last_30d"></span>/30d</span></template>
            </div>
            <div class="flex flex-wrap gap-1 mt-1.5" x-show="d.nounish_traits?.length">
              <template x-for="t in (d.nounish_traits||[])" :key="t">
                <span class="text-xs bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded" x-text="t"></span>
              </template>
            </div>
          </div>
        </div>

        <!-- Body -->
        <div class="px-5 py-4">
          <p x-show="d.subject" class="text-xs text-slate-500 font-medium mb-1">
            Subject: <span class="text-slate-700" x-text="d.subject"></span></p>
          <div x-show="!d._editing" class="text-sm text-slate-700 bg-slate-50 rounded-lg p-4 whitespace-pre-wrap leading-relaxed" x-text="d.body"></div>
          <textarea x-show="d._editing" x-cloak x-model="d._editBody" rows="5"
            class="w-full text-sm text-slate-700 bg-slate-50 rounded-lg p-4 border border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-200 resize-none"></textarea>
        </div>

        <!-- Actions -->
        <div class="px-5 py-3 bg-slate-50 border-t border-slate-100 flex items-center justify-between gap-3">
          <div class="flex gap-2">
            <button x-show="!d._editing" @click="d._editBody=d.body; d._editing=true"
              class="text-xs px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-100 text-slate-600 transition-colors">Edit</button>
            <template x-if="d._editing">
              <div class="flex gap-2">
                <button @click="saveEdit(d)" class="text-xs px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-900 text-white transition-colors">Save</button>
                <button @click="d._editing=false" class="text-xs px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-slate-500 transition-colors">Cancel</button>
              </div>
            </template>
          </div>
          <div class="flex gap-2">
            <button @click="rejectDraft(d)" :disabled="d._loading"
              class="text-xs px-4 py-1.5 rounded-lg border border-red-200 bg-white hover:bg-red-50 text-red-600 font-medium transition-colors disabled:opacity-50">
              <span x-show="!d._loading">✕ Reject</span><span x-show="d._loading">…</span>
            </button>
            <button @click="approveDraft(d)" :disabled="d._loading"
              class="text-xs px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5">
              <span x-show="!d._loading">✓ Approve & Push</span>
              <span x-show="d._loading" class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>Pushing…
              </span>
            </button>
          </div>
        </div>

        <div x-show="d._toast" x-cloak x-transition class="px-5 py-2 text-xs font-medium"
             :class="d._toastType==='ok' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'"
             x-text="d._toast"></div>
      </div>
    </template>
  </div>
</div>

<script>
function app() {
  return {
    tab: 'pipeline',
    loading: false,
    lastRefresh: '',
    stats: { total_leads:0, evaluations:0, pending:0, approved:0, rejected:0 },
    pipeline: { scout:[], evaluator:[], writer:[] },
    pending: [],
    pipelineRunning: false,
    _pollTimer: null,

    tabs: [
      { id:'pipeline', icon:'🔍', label:'Pipeline' },
      { id:'review',   icon:'✏️',  label:'Review' },
    ],

    get steps() {
      return [
        { id:'scout',     name:'Agent A — Scout',     desc:'Raw leads collected',   bg:'bg-blue-500',   color:'text-blue-600',   count: this.pipeline.scout.length     },
        { id:'evaluator', name:'Agent B — Evaluator', desc:'Top leads scored',      bg:'bg-indigo-500', color:'text-indigo-600', count: this.pipeline.evaluator.length  },
        { id:'writer',    name:'Agent C — Writer',    desc:'Outreach drafts ready', bg:'bg-violet-500', color:'text-violet-600', count: this.pipeline.writer.length     },
      ];
    },

    get statCards() {
      return [
        { label:'Total Leads',    value:this.stats.total_leads,  color:'text-slate-800' },
        { label:'Evaluated',      value:this.stats.evaluations,  color:'text-indigo-600' },
        { label:'Pending Review', value:this.stats.pending,      color:'text-amber-600' },
        { label:'Approved',       value:this.stats.approved,     color:'text-green-600' },
        { label:'Rejected',       value:this.stats.rejected,     color:'text-red-500' },
      ];
    },

    errorMsg: '',

    async init() {
      await this.refresh();
      await this.checkPipelineStatus();
      setInterval(()=>this.refresh(), 30000);
    },

    async checkPipelineStatus() {
      try {
        const s = await this.getJSON('/api/pipeline/status');
        const wasRunning = this.pipelineRunning;
        this.pipelineRunning = s.running;
        if (wasRunning && !s.running) {
          // just finished — refresh data
          await this.refresh();
          clearInterval(this._pollTimer);
          this._pollTimer = null;
        }
      } catch(e) {}
    },

    async runPipeline() {
      if (this.pipelineRunning) return;
      try {
        const r = await fetch('/api/pipeline/run', { method: 'POST' });
        if (r.ok) {
          this.pipelineRunning = true;
          // poll every 10s until done
          this._pollTimer = setInterval(()=>this.checkPipelineStatus(), 10000);
        } else {
          const d = await r.json();
          this.errorMsg = d.detail || 'Failed to start pipeline';
        }
      } catch(e) { this.errorMsg = 'Failed to start pipeline'; }
    },

    async getJSON(url) {
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) throw new Error(url + ' → HTTP ' + r.status);
      return await r.json();
    },

    async refresh() {
      this.loading = true;
      this.errorMsg = '';
      try {
        // Independent fetches — one failure doesn't blank everything
        try { this.stats = await this.getJSON('/api/stats'); }
        catch (e) { this.errorMsg = 'stats: ' + e.message; console.error(e); }

        try { this.pipeline = await this.getJSON('/api/pipeline'); }
        catch (e) { this.errorMsg = 'pipeline: ' + e.message; console.error(e); }

        try {
          const p = await this.getJSON('/api/pending');
          this.pending = p.map(d=>({...d, _loading:false, _toast:'', _toastType:'', _editing:false, _editBody:d.body, _done:false}));
        } catch (e) { this.errorMsg = 'pending: ' + e.message; console.error(e); }

        this.lastRefresh = 'Updated ' + new Date().toLocaleTimeString();
      } finally { this.loading = false; }
    },

    sourceClass(s) {
      const m = { github:'source-github', twitter:'source-twitter', linkedin:'source-linkedin' };
      return m[s] || 'source-web';
    },

    scoreRing(n) {
      if (n >= 80) return 'bg-green-50 text-green-700';
      if (n >= 60) return 'bg-amber-50 text-amber-700';
      return 'bg-slate-100 text-slate-500';
    },

    scoreColor(n) {
      if (n >= 80) return 'text-green-600';
      if (n >= 60) return 'text-amber-600';
      return 'text-slate-400';
    },

    async saveEdit(d) {
      if (!d._editBody.trim()) return;
      const r = await fetch(`/api/drafts/${d.id}/body`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({body:d._editBody})});
      if (r.ok) { d.body=d._editBody; d._editing=false; }
    },

    async approveDraft(d) {
      d._loading = true;
      try {
        const r = await fetch(`/api/drafts/${d.id}/approve`,{method:'POST'});
        const data = await r.json();
        if (r.ok) {
          d._toast='✓ Approved & pushed to AthenaX'; d._toastType='ok';
          setTimeout(()=>{ d._done=true; this.stats.pending--; this.stats.approved++; },1500);
        } else {
          d._toast='✗ '+(data.detail||'Push failed'); d._toastType='err';
          setTimeout(()=>d._toast='',4000);
        }
      } finally { d._loading=false; }
    },

    async rejectDraft(d) {
      d._loading = true;
      try {
        const r = await fetch(`/api/drafts/${d.id}/reject`,{method:'POST'});
        if (r.ok) {
          d._toast='Rejected'; d._toastType='err';
          setTimeout(()=>{ d._done=true; this.stats.pending--; this.stats.rejected++; },800);
        }
      } finally { d._loading=false; }
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
