"""AthenaX Partnership Agent — Admin Dashboard."""
import json
import os
import threading
from datetime import datetime, timezone

from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

load_dotenv(Path(__file__).parent.parent / ".env")

app = FastAPI(title="AthenaX Dashboard", docs_url=None, redoc_url=None)

# ── Pipeline run state ────────────────────────────────────────────────────────
_pipeline_state = {
    "running": False,
    "last_run": None,
    "last_status": None,
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
        total   = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        evaled  = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
        high    = conn.execute("SELECT COUNT(*) FROM evaluations WHERE compatibility_score >= 80").fetchone()[0]
        new_ct  = conn.execute(
            "SELECT COUNT(*) FROM evaluations WHERE details_json LIKE '%\"project_type\": \"new\"%' OR details_json LIKE '%\"project_type\":\"new\"%'"
        ).fetchone()[0]
        est_ct  = conn.execute(
            "SELECT COUNT(*) FROM evaluations WHERE details_json LIKE '%\"project_type\": \"established\"%' OR details_json LIKE '%\"project_type\":\"established\"%'"
        ).fetchone()[0]
    return {
        "total_leads": total,
        "evaluations": evaled,
        "high_score":  high,
        "new_projects": new_ct,
        "established":  est_ct,
    }


@app.get("/api/pipeline")
def pipeline():
    with _db() as conn:
        scout = [dict(r) for r in conn.execute("""
            SELECT id, source, name, url, description,
                   github_stars, github_forks, commits_last_30d,
                   twitter_handle, twitter_followers, twitter_recent_tweet,
                   linkedin_profile, linkedin_recent_post,
                   tech_stack, sector, created_at
            FROM leads ORDER BY created_at DESC LIMIT 100
        """).fetchall()]

        evaluator = [dict(r) for r in conn.execute("""
            SELECT e.id, e.lead_id, e.compatibility_score,
                   e.nounish_traits, e.reason_for_partnership,
                   e.listing_fit_notes, e.details_json, e.created_at,
                   l.name AS lead_name, l.url AS lead_url, l.source AS lead_source,
                   l.sector, l.github_stars, l.commits_last_30d,
                   l.twitter_handle, l.twitter_followers,
                   l.bd_twitter_handles, l.contact_email
            FROM evaluations e
            JOIN leads l ON e.lead_id = l.id
            ORDER BY e.compatibility_score DESC
        """).fetchall()]

    for e in evaluator:
        if e["nounish_traits"]:
            try: e["nounish_traits"] = json.loads(e["nounish_traits"])
            except: e["nounish_traits"] = []
        if e.get("details_json"):
            try: e["details"] = json.loads(e["details_json"])
            except: e["details"] = {}
        else:
            e["details"] = {}
        del e["details_json"]
        if e.get("bd_twitter_handles"):
            try: e["bd_twitter_handles"] = json.loads(e["bd_twitter_handles"])
            except: e["bd_twitter_handles"] = []

    for s in scout:
        if s["tech_stack"]:
            try: s["tech_stack"] = json.loads(s["tech_stack"])
            except: s["tech_stack"] = []

    return {"scout": scout, "evaluator": evaluator}


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
    .fade { animation: fadeIn .25s ease; }
    @keyframes fadeIn { from{opacity:0;transform:translateY(4px)} to{opacity:1;transform:translateY(0)} }
    .source-github  { background:#f0fdf4; color:#15803d; }
    .source-twitter { background:#eff6ff; color:#1d4ed8; }
    .source-linkedin{ background:#f0f9ff; color:#0369a1; }
    .source-web     { background:#faf5ff; color:#7e22ce; }
    .badge-new      { background:#fef9c3; color:#854d0e; }
    .badge-est      { background:#e0f2fe; color:#0369a1; }
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

<!-- Step headers -->
<div class="max-w-screen-xl mx-auto px-6 mt-5">
  <div class="grid grid-cols-2 gap-4 mb-4">
    <div class="flex items-center gap-3 bg-white rounded-xl border border-slate-200 px-4 py-3">
      <div class="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">1</div>
      <div>
        <p class="font-semibold text-slate-800 text-sm">Agent A — Scout</p>
        <p class="text-xs text-slate-400">Raw leads collected</p>
      </div>
      <div class="ml-auto text-lg font-bold text-blue-600" x-text="pipeline.scout.length"></div>
    </div>
    <div class="flex items-center gap-3 bg-white rounded-xl border border-slate-200 px-4 py-3">
      <div class="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">2</div>
      <div>
        <p class="font-semibold text-slate-800 text-sm">Agent B — Evaluator</p>
        <p class="text-xs text-slate-400">All leads scored</p>
      </div>
      <div class="ml-auto text-lg font-bold text-indigo-600" x-text="pipeline.evaluator.length"></div>
    </div>
  </div>

  <!-- Two columns -->
  <div class="grid grid-cols-2 gap-4 items-start pb-16">

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
          <div class="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">
            <template x-if="l.sector">
              <span class="bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded" x-text="l.sector"></span>
            </template>
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
          <template x-if="l.twitter_recent_tweet">
            <p class="mt-2 text-xs text-slate-400 italic line-clamp-2 border-l-2 border-slate-100 pl-2"
               x-text="l.twitter_recent_tweet"></p>
          </template>
          <template x-if="l.linkedin_recent_post && !l.twitter_recent_tweet">
            <p class="mt-2 text-xs text-slate-400 italic line-clamp-2 border-l-2 border-slate-100 pl-2"
               x-text="l.linkedin_recent_post"></p>
          </template>
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
        <div class="bg-white rounded-xl border border-slate-200 hover:border-indigo-200 transition-colors" x-data="{open:false}">
          <div class="p-3.5 cursor-pointer" @click="open=!open">
            <div class="flex items-center gap-2.5">
              <div class="w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm flex-shrink-0"
                   :class="scoreRing(e.compatibility_score)"
                   x-text="e.compatibility_score"></div>
              <div class="min-w-0 flex-1">
                <a :href="e.lead_url" target="_blank" @click.stop
                   class="text-sm font-semibold text-slate-800 hover:text-indigo-600 truncate block"
                   x-text="e.lead_name"></a>
                <div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
                  <span class="text-xs px-1.5 py-0.5 rounded font-medium"
                        :class="sourceClass(e.lead_source)" x-text="e.lead_source"></span>
                  <span x-show="e.details?.project_type"
                        class="text-xs px-1.5 py-0.5 rounded font-medium capitalize"
                        :class="e.details?.project_type==='new' ? 'badge-new' : 'badge-est'"
                        x-text="e.details?.project_type"></span>
                  <span x-show="e.sector" class="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-500"
                        x-text="e.sector"></span>
                </div>
              </div>
              <svg class="w-4 h-4 text-slate-400 flex-shrink-0 transition-transform"
                   :class="open && 'rotate-180'" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
              </svg>
            </div>
            <p class="text-xs text-slate-500 mt-2 leading-relaxed line-clamp-2" x-text="e.reason_for_partnership"></p>
          </div>

          <div x-show="open" x-collapse class="border-t border-slate-100 px-3.5 pb-3.5 pt-3 space-y-3">

            <!-- Score breakdown -->
            <div x-show="e.details?.score_breakdown">
              <p class="text-xs font-semibold text-slate-700 mb-1.5">Score Breakdown</p>
              <div class="grid grid-cols-3 gap-2 text-center">
                <div class="bg-slate-50 rounded-lg py-2">
                  <p class="text-xs text-slate-400">Base</p>
                  <p class="text-sm font-bold text-slate-700" x-text="e.details?.score_breakdown?.base_score ?? '—'"></p>
                </div>
                <div class="bg-slate-50 rounded-lg py-2">
                  <p class="text-xs text-slate-400">Boosters</p>
                  <p class="text-sm font-bold text-indigo-600" x-text="e.details?.score_breakdown?.booster_points ? '+'+e.details.score_breakdown.booster_points : '—'"></p>
                </div>
                <div class="bg-slate-50 rounded-lg py-2">
                  <p class="text-xs text-slate-400">Velocity ×</p>
                  <p class="text-sm font-bold text-emerald-600" x-text="e.details?.score_breakdown?.velocity_multiplier ?? '—'"></p>
                </div>
              </div>
              <div x-show="e.details?.score_breakdown?.boosters_detail?.length" class="mt-2 space-y-1">
                <template x-for="b in (e.details?.score_breakdown?.boosters_detail||[])" :key="b.signal">
                  <div class="flex items-center gap-2 text-xs">
                    <span class="bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded font-medium" x-text="'+'+b.points"></span>
                    <span class="font-medium text-slate-700" x-text="b.signal"></span>
                    <span class="text-slate-400 truncate" x-text="b.note"></span>
                  </div>
                </template>
              </div>
            </div>

            <!-- Criteria checklist -->
            <div x-show="e.details?.criteria_detail">
              <p class="text-xs font-semibold text-slate-700 mb-1.5">Criteria Checklist</p>
              <div class="space-y-1">
                <template x-for="[key, val] in Object.entries(e.details?.criteria_detail||{})" :key="key">
                  <div class="flex items-start gap-2 text-xs">
                    <span class="flex-shrink-0 mt-0.5"
                          :class="val?.met===true ? 'text-green-500' : val?.met===false ? 'text-red-400' : 'text-slate-300'"
                          x-text="val?.met===true ? '✓' : val?.met===false ? '✗' : '?'"></span>
                    <span class="font-medium text-slate-600 capitalize flex-shrink-0 w-28"
                          x-text="key.replace(/_/g,' ')"></span>
                    <span class="text-slate-400 leading-relaxed"
                          x-text="val?.note || (val?.followers ? val.followers.toLocaleString()+' followers' : val?.stars ? val.stars.toLocaleString()+' stars' : '—')"></span>
                  </div>
                </template>
              </div>
            </div>

            <!-- Velocity -->
            <div x-show="e.details?.velocity_assessment">
              <p class="text-xs font-semibold text-slate-700 mb-1">Velocity</p>
              <p class="text-xs text-slate-500 italic" x-text="e.details?.velocity_assessment"></p>
            </div>

            <!-- BD contacts -->
            <div x-show="e.bd_twitter_handles?.length">
              <p class="text-xs font-semibold text-slate-700 mb-1.5">BD / Partnerships Contacts</p>
              <div class="flex flex-wrap gap-2">
                <template x-for="h in (e.bd_twitter_handles||[])" :key="h.handle">
                  <a :href="'https://x.com/'+h.handle.replace('@','')" target="_blank"
                     class="flex items-center gap-1.5 text-xs bg-sky-50 text-sky-700 border border-sky-200 rounded-lg px-2.5 py-1.5 hover:bg-sky-100 transition-colors">
                    <span class="font-semibold" x-text="h.handle"></span>
                    <span class="text-sky-500 capitalize" x-text="h.role"></span>
                    <span x-show="h.followers" class="text-sky-400" x-text="'· '+Number(h.followers).toLocaleString()"></span>
                  </a>
                </template>
              </div>
            </div>

            <!-- Contact email -->
            <div x-show="e.contact_email">
              <p class="text-xs font-semibold text-slate-700 mb-1">Contact Email</p>
              <a :href="'mailto:'+e.contact_email" class="text-xs text-indigo-500 hover:underline" x-text="e.contact_email"></a>
            </div>

            <!-- Listing fit -->
            <p x-show="e.listing_fit_notes"
               class="text-xs text-slate-400 border-t border-slate-100 pt-2"
               x-text="e.listing_fit_notes"></p>
          </div>
        </div>
      </template>
    </div>

  </div>
</div>

<script>
function app() {
  return {
    loading: false,
    lastRefresh: '',
    stats: { total_leads:0, evaluations:0, high_score:0, new_projects:0, established:0 },
    pipeline: { scout:[], evaluator:[] },
    pipelineRunning: false,
    _pollTimer: null,
    errorMsg: '',

    get statCards() {
      return [
        { label:'Total Leads',   value:this.stats.total_leads,   color:'text-slate-800' },
        { label:'Evaluated',     value:this.stats.evaluations,   color:'text-indigo-600' },
        { label:'Score ≥ 80',    value:this.stats.high_score,    color:'text-green-600' },
        { label:'New Projects',  value:this.stats.new_projects,  color:'text-amber-600' },
        { label:'Established',   value:this.stats.established,   color:'text-blue-600' },
      ];
    },

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
        try { this.stats = await this.getJSON('/api/stats'); }
        catch (e) { this.errorMsg = 'stats: ' + e.message; }

        try { this.pipeline = await this.getJSON('/api/pipeline'); }
        catch (e) { this.errorMsg = 'pipeline: ' + e.message; }

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
