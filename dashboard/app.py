"""AthenaX Partnership Agent — Admin Dashboard."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="AthenaX Dashboard", docs_url=None, redoc_url=None)

# ── DB helpers ────────────────────────────────────────────────────────────────

def _db():
    from athenax.db.database import get_connection
    return get_connection()

def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ── REST API ──────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def stats():
    with _db() as conn:
        total   = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM outreach_drafts WHERE status='pending'").fetchone()[0]
        approved= conn.execute("SELECT COUNT(*) FROM outreach_drafts WHERE status='approved'").fetchone()[0]
        rejected= conn.execute("SELECT COUNT(*) FROM outreach_drafts WHERE status='rejected'").fetchone()[0]
        evals   = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
    return {"total_leads": total, "evaluations": evals,
            "pending": pending, "approved": approved, "rejected": rejected}


@app.get("/api/pending")
def pending_drafts():
    with _db() as conn:
        rows = conn.execute("""
            SELECT
                od.id, od.channel, od.subject, od.body, od.status, od.created_at,
                l.name  AS lead_name,
                l.url   AS lead_url,
                l.source AS lead_source,
                l.twitter_handle,
                l.github_stars,
                l.commits_last_30d,
                e.compatibility_score,
                e.nounish_traits,
                e.reason_for_partnership,
                e.listing_fit_notes
            FROM outreach_drafts od
            JOIN leads       l ON od.lead_id       = l.id
            JOIN evaluations e ON od.evaluation_id = e.id
            WHERE od.status = 'pending'
            ORDER BY e.compatibility_score DESC
        """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d["nounish_traits"]:
            try:
                d["nounish_traits"] = json.loads(d["nounish_traits"])
            except Exception:
                d["nounish_traits"] = []
        result.append(d)
    return result


@app.get("/api/leads")
def all_leads(limit: int = 50):
    with _db() as conn:
        rows = conn.execute("""
            SELECT
                l.id, l.name, l.url, l.source, l.description,
                l.github_stars, l.commits_last_30d,
                l.twitter_handle, l.twitter_followers,
                l.created_at, l.updated_at,
                e.compatibility_score,
                e.reason_for_partnership,
                e.listing_fit_notes
            FROM leads l
            LEFT JOIN evaluations e ON e.lead_id = l.id
            ORDER BY COALESCE(e.compatibility_score, 0) DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


class ApproveRequest(BaseModel):
    pass  # no body needed


@app.post("/api/drafts/{draft_id}/approve")
def approve(draft_id: str):
    with _db() as conn:
        row = conn.execute("""
            SELECT od.id, od.lead_id, od.evaluation_id, od.channel, od.subject, od.body,
                   l.name AS lead_name, l.url AS lead_url, l.source AS lead_source,
                   l.tech_stack, l.twitter_handle, l.remote_lead_id,
                   e.compatibility_score, e.nounish_traits, e.reason_for_partnership, e.listing_fit_notes
            FROM outreach_drafts od
            JOIN leads l       ON od.lead_id       = l.id
            JOIN evaluations e ON od.evaluation_id = e.id
            WHERE od.id = ?
        """, (draft_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Draft not found")

    draft = dict(row)
    if draft.get("status") == "approved":
        return {"status": "already_approved"}

    from athenax.cli.review import _approve
    from athenax.api.athenax_client import AthenaXClient
    try:
        _approve(draft, AthenaXClient())
        return {"status": "approved"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/drafts/{draft_id}/reject")
def reject(draft_id: str):
    with _db() as conn:
        exists = conn.execute("SELECT id FROM outreach_drafts WHERE id=?", (draft_id,)).fetchone()
        if not exists:
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


# ── HTML Dashboard ────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>AthenaX Partnership Agent</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
  <style>
    body { font-family: 'Inter', sans-serif; }
    .channel-badge-twitter { background:#e8f4fd; color:#1d9bf0; }
    .channel-badge-email   { background:#f0fdf4; color:#16a34a; }
    [x-cloak] { display: none !important; }
    .fade-enter { animation: fadeIn .3s ease; }
    @keyframes fadeIn { from { opacity:0; transform:translateY(6px) } to { opacity:1; transform:translateY(0) } }
  </style>
</head>
<body class="bg-gray-50 min-h-screen" x-data="dashboard()" x-init="init()">

<!-- ── Header ──────────────────────────────────────────────────────────────── -->
<header class="bg-white border-b border-gray-200 sticky top-0 z-10">
  <div class="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
    <div class="flex items-center gap-3">
      <div class="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center">
        <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M13 10V3L4 14h7v7l9-11h-7z"/>
        </svg>
      </div>
      <div>
        <h1 class="text-lg font-bold text-gray-900">AthenaX Partnership Agent</h1>
        <p class="text-xs text-gray-500">Admin Dashboard</p>
      </div>
    </div>
    <div class="flex items-center gap-3">
      <span class="text-xs text-gray-400" x-text="lastRefresh"></span>
      <button @click="refresh()"
        class="text-sm px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-600 flex items-center gap-1.5 transition-colors">
        <svg class="w-3.5 h-3.5" :class="loading && 'animate-spin'" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
        Refresh
      </button>
    </div>
  </div>
</header>

<!-- ── Stats ───────────────────────────────────────────────────────────────── -->
<div class="max-w-7xl mx-auto px-6 mt-6">
  <div class="grid grid-cols-2 sm:grid-cols-5 gap-4">
    <template x-for="s in statCards" :key="s.label">
      <div class="bg-white rounded-xl border border-gray-200 p-4 fade-enter">
        <p class="text-xs font-medium text-gray-500 uppercase tracking-wide" x-text="s.label"></p>
        <p class="text-2xl font-bold mt-1" :class="s.color" x-text="s.value"></p>
      </div>
    </template>
  </div>
</div>

<!-- ── Tabs ────────────────────────────────────────────────────────────────── -->
<div class="max-w-7xl mx-auto px-6 mt-6">
  <div class="flex gap-1 bg-gray-100 rounded-xl p-1 w-fit">
    <button @click="tab='pending'"
      :class="tab==='pending' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-700'"
      class="px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2">
      Pending Review
      <span x-show="stats.pending > 0"
        class="bg-indigo-600 text-white text-xs px-1.5 py-0.5 rounded-full" x-text="stats.pending"></span>
    </button>
    <button @click="tab='leads'"
      :class="tab==='leads' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-500 hover:text-gray-700'"
      class="px-4 py-2 rounded-lg text-sm font-medium transition-all">
      All Leads
    </button>
  </div>
</div>

<!-- ── Pending Drafts ──────────────────────────────────────────────────────── -->
<div class="max-w-7xl mx-auto px-6 mt-4 pb-12" x-show="tab==='pending'" x-cloak>

  <div x-show="pending.length === 0 && !loading"
    class="bg-white rounded-xl border border-gray-200 p-12 text-center fade-enter">
    <div class="w-12 h-12 bg-green-50 rounded-full flex items-center justify-center mx-auto">
      <svg class="w-6 h-6 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
      </svg>
    </div>
    <p class="mt-3 text-gray-500 font-medium">No pending drafts</p>
    <p class="text-sm text-gray-400 mt-1">Run the pipeline to generate new outreach drafts.</p>
  </div>

  <div class="space-y-4">
    <template x-for="(d, idx) in pending" :key="d.id">
      <div class="bg-white rounded-xl border border-gray-200 overflow-hidden fade-enter"
           x-show="!d._dismissed">

        <!-- Card header -->
        <div class="px-5 py-4 flex items-start justify-between border-b border-gray-100">
          <div class="flex items-start gap-3">
            <!-- Score ring -->
            <div class="w-12 h-12 rounded-full flex items-center justify-center flex-shrink-0 font-bold text-sm"
                 :class="d.compatibility_score >= 80 ? 'bg-green-50 text-green-700' :
                          d.compatibility_score >= 60 ? 'bg-amber-50 text-amber-700' : 'bg-gray-100 text-gray-600'"
                 x-text="d.compatibility_score || '—'"></div>
            <div>
              <div class="flex items-center gap-2 flex-wrap">
                <h3 class="font-semibold text-gray-900" x-text="d.lead_name"></h3>
                <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                      :class="d.channel === 'twitter_dm' ? 'channel-badge-twitter' : 'channel-badge-email'"
                      x-text="d.channel === 'twitter_dm' ? '𝕏 Twitter DM' : '✉ Email'"></span>
                <span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 capitalize"
                      x-text="d.lead_source"></span>
              </div>
              <p class="text-xs text-gray-500 mt-0.5" x-text="d.reason_for_partnership"></p>
              <div class="flex items-center gap-3 mt-1 flex-wrap">
                <a :href="d.lead_url" target="_blank"
                   class="text-xs text-indigo-500 hover:underline truncate max-w-xs" x-text="d.lead_url"></a>
                <template x-if="d.github_stars">
                  <span class="text-xs text-gray-400">⭐ <span x-text="d.github_stars?.toLocaleString()"></span></span>
                </template>
                <template x-if="d.commits_last_30d !== null && d.commits_last_30d !== undefined">
                  <span class="text-xs text-gray-400">🔨 <span x-text="d.commits_last_30d"></span> commits/30d</span>
                </template>
              </div>
              <!-- Traits -->
              <div class="flex gap-1 mt-2 flex-wrap" x-show="d.nounish_traits?.length">
                <template x-for="t in (d.nounish_traits || [])" :key="t">
                  <span class="text-xs bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded" x-text="t"></span>
                </template>
              </div>
            </div>
          </div>
        </div>

        <!-- Message body -->
        <div class="px-5 py-4">
          <div x-show="d.subject" class="text-xs font-medium text-gray-500 mb-1">
            Subject: <span class="text-gray-700" x-text="d.subject"></span>
          </div>
          <div x-show="!d._editing"
               class="text-sm text-gray-700 bg-gray-50 rounded-lg p-4 whitespace-pre-wrap leading-relaxed"
               x-text="d.body"></div>
          <textarea x-show="d._editing" x-cloak
                    x-model="d._editBody"
                    class="w-full text-sm text-gray-700 bg-gray-50 rounded-lg p-4 border border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-200 resize-none"
                    rows="5"></textarea>
        </div>

        <!-- Actions -->
        <div class="px-5 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between gap-3">
          <div class="flex items-center gap-2">
            <!-- Edit / Save -->
            <button x-show="!d._editing" @click="startEdit(d)"
              class="text-sm px-3 py-1.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-100 text-gray-600 transition-colors">
              Edit
            </button>
            <template x-if="d._editing">
              <div class="flex gap-2">
                <button @click="saveEdit(d)"
                  class="text-sm px-3 py-1.5 rounded-lg bg-gray-700 hover:bg-gray-900 text-white transition-colors">
                  Save
                </button>
                <button @click="d._editing=false"
                  class="text-sm px-3 py-1.5 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 text-gray-500 transition-colors">
                  Cancel
                </button>
              </div>
            </template>
          </div>

          <div class="flex gap-2">
            <!-- Reject -->
            <button @click="rejectDraft(d)"
              :disabled="d._loading"
              class="text-sm px-4 py-1.5 rounded-lg border border-red-200 bg-white hover:bg-red-50 text-red-600 font-medium transition-colors disabled:opacity-50">
              <span x-show="!d._loading">✕ Reject</span>
              <span x-show="d._loading">…</span>
            </button>
            <!-- Approve -->
            <button @click="approveDraft(d)"
              :disabled="d._loading"
              class="text-sm px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-medium transition-colors disabled:opacity-50 flex items-center gap-1.5">
              <span x-show="!d._loading">✓ Approve & Push</span>
              <span x-show="d._loading" class="flex items-center gap-1">
                <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                Pushing…
              </span>
            </button>
          </div>
        </div>

        <!-- Toast on action -->
        <div x-show="d._toast" x-cloak x-transition
             class="px-5 py-2 text-sm font-medium"
             :class="d._toastType === 'success' ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'"
             x-text="d._toast"></div>
      </div>
    </template>
  </div>
</div>

<!-- ── All Leads ───────────────────────────────────────────────────────────── -->
<div class="max-w-7xl mx-auto px-6 mt-4 pb-12" x-show="tab==='leads'" x-cloak>
  <div class="bg-white rounded-xl border border-gray-200 overflow-hidden fade-enter">
    <div class="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
      <h2 class="font-semibold text-gray-900">All Leads</h2>
      <span class="text-xs text-gray-400" x-text="leads.length + ' leads'"></span>
    </div>
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="text-xs text-gray-500 uppercase tracking-wide border-b border-gray-100 bg-gray-50">
            <th class="px-5 py-3 text-left font-medium">Project</th>
            <th class="px-4 py-3 text-left font-medium">Source</th>
            <th class="px-4 py-3 text-right font-medium">Score</th>
            <th class="px-4 py-3 text-right font-medium">Stars</th>
            <th class="px-4 py-3 text-right font-medium">Commits/30d</th>
            <th class="px-4 py-3 text-left font-medium">Notes</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <template x-for="l in leads" :key="l.id">
            <tr class="hover:bg-gray-50 transition-colors">
              <td class="px-5 py-3">
                <a :href="l.url" target="_blank" class="font-medium text-gray-900 hover:text-indigo-600 transition-colors" x-text="l.name"></a>
                <p class="text-xs text-gray-400 mt-0.5 truncate max-w-xs" x-text="l.description || '—'"></p>
              </td>
              <td class="px-4 py-3">
                <span class="text-xs px-2 py-0.5 rounded-full capitalize font-medium"
                      :class="{'bg-gray-100 text-gray-600': true}"
                      x-text="l.source"></span>
              </td>
              <td class="px-4 py-3 text-right">
                <span x-show="l.compatibility_score"
                      class="font-semibold"
                      :class="l.compatibility_score >= 80 ? 'text-green-600' : l.compatibility_score >= 60 ? 'text-amber-600' : 'text-gray-400'"
                      x-text="l.compatibility_score + '/100'"></span>
                <span x-show="!l.compatibility_score" class="text-gray-300">—</span>
              </td>
              <td class="px-4 py-3 text-right text-gray-500" x-text="l.github_stars?.toLocaleString() || '—'"></td>
              <td class="px-4 py-3 text-right text-gray-500" x-text="l.commits_last_30d ?? '—'"></td>
              <td class="px-4 py-3 text-xs text-gray-500 max-w-xs truncate" x-text="l.listing_fit_notes || '—'"></td>
            </tr>
          </template>
        </tbody>
      </table>
      <div x-show="leads.length === 0 && !loading" class="px-5 py-12 text-center text-gray-400 text-sm">
        No leads yet — run the pipeline first.
      </div>
    </div>
  </div>
</div>

<script>
function dashboard() {
  return {
    tab: 'pending',
    loading: false,
    stats: { total_leads:0, evaluations:0, pending:0, approved:0, rejected:0 },
    pending: [],
    leads: [],
    lastRefresh: '',

    get statCards() {
      return [
        { label:'Total Leads',   value: this.stats.total_leads,  color:'text-gray-900' },
        { label:'Evaluated',     value: this.stats.evaluations,  color:'text-indigo-600' },
        { label:'Pending Review',value: this.stats.pending,      color:'text-amber-600' },
        { label:'Approved',      value: this.stats.approved,     color:'text-green-600' },
        { label:'Rejected',      value: this.stats.rejected,     color:'text-red-500'  },
      ];
    },

    async init() {
      await this.refresh();
      setInterval(() => this.refresh(), 30000);
    },

    async refresh() {
      this.loading = true;
      try {
        const [s, p, l] = await Promise.all([
          fetch('/api/stats').then(r => r.json()),
          fetch('/api/pending').then(r => r.json()),
          fetch('/api/leads').then(r => r.json()),
        ]);
        this.stats = s;
        this.pending = p.map(d => ({ ...d, _loading:false, _toast:'', _toastType:'', _editing:false, _editBody:d.body, _dismissed:false }));
        this.leads = l;
        this.lastRefresh = 'Updated ' + new Date().toLocaleTimeString();
      } finally {
        this.loading = false;
      }
    },

    startEdit(d) { d._editBody = d.body; d._editing = true; },

    async saveEdit(d) {
      if (!d._editBody.trim()) return;
      const r = await fetch(`/api/drafts/${d.id}/body`, {
        method:'PUT',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ body: d._editBody })
      });
      if (r.ok) { d.body = d._editBody; d._editing = false; }
    },

    async approveDraft(d) {
      d._loading = true;
      try {
        const r = await fetch(`/api/drafts/${d.id}/approve`, { method:'POST' });
        const data = await r.json();
        if (r.ok) {
          d._toast = '✓ Approved and pushed to AthenaX API';
          d._toastType = 'success';
          setTimeout(() => { d._dismissed = true; this.stats.pending--; this.stats.approved++; }, 1500);
        } else {
          d._toast = '✗ ' + (data.detail || 'Push failed');
          d._toastType = 'error';
          setTimeout(() => d._toast = '', 4000);
        }
      } finally { d._loading = false; }
    },

    async rejectDraft(d) {
      d._loading = true;
      try {
        const r = await fetch(`/api/drafts/${d.id}/reject`, { method:'POST' });
        if (r.ok) {
          d._toast = '✗ Rejected';
          d._toastType = 'error';
          setTimeout(() => { d._dismissed = true; this.stats.pending--; this.stats.rejected++; }, 1000);
        }
      } finally { d._loading = false; }
    }
  };
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def root():
    return HTML


# ── Entry point ───────────────────────────────────────────────────────────────

def run():
    import uvicorn
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    print(f"\n🚀  Dashboard running at http://localhost:{port}\n")
    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    run()
