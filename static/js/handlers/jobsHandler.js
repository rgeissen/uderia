/**
 * Jobs Tab — Task Scheduler Component Detail
 *
 * Renders a "Jobs" tab inside the Task Scheduler component detail panel
 * with two sub-tabs:
 *   1. Profile Jobs  — full CRUD for conversation-created agent tasks (per-profile)
 *   2. Platform Jobs — management UI for platform-level jobs (knowledge repository sync)
 *
 * Entry point: window.jobsHandler.initJobsTab(containerId)
 * Called from componentHandler.js after the Jobs tab panel is inserted into the DOM.
 */

(function () {
    'use strict';

    // ── Constants ──────────────────────────────────────────────────────────────

    const AUTH = () => localStorage.getItem('tda_auth_token');
    const BASE = '/api/v1';

    // IFOC profile type → colour tokens
    const IFOC_COLORS = {
        llm_only:     { bg: 'rgba(74,222,128,0.12)', border: 'rgba(74,222,128,0.3)', text: '#4ade80', label: 'Ideate' },
        rag_focused:  { bg: 'rgba(59,130,246,0.12)', border: 'rgba(59,130,246,0.3)', text: '#3b82f6', label: 'Focus' },
        tool_enabled: { bg: 'rgba(241,95,34,0.12)',  border: 'rgba(241,95,34,0.3)',  text: '#F15F22', label: 'Optimize' },
        genie:        { bg: 'rgba(147,51,234,0.12)', border: 'rgba(147,51,234,0.3)', text: '#9333ea', label: 'Coordinate' },
    };

    // Interval labels
    const INTERVALS = [
        { value: 'hourly',  label: 'Hourly' },
        { value: '6h',      label: 'Every 6 hours' },
        { value: 'daily',   label: 'Daily' },
        { value: 'weekly',  label: 'Weekly' },
    ];

    // ── CSS ────────────────────────────────────────────────────────────────────

    function _injectCSS() {
        if (document.getElementById('jobs-handler-css')) return;
        const s = document.createElement('style');
        s.id = 'jobs-handler-css';
        s.textContent = `
/* Jobs tab shell */
.jobs-sub-tabs { display:flex; gap:4px; padding:0 0 12px 0; border-bottom:1px solid rgba(255,255,255,0.08); margin-bottom:16px; }
.jobs-sub-tab  { display:inline-flex; align-items:center; gap:6px; padding:6px 14px; border-radius:8px;
                 font-size:13px; font-weight:500; cursor:pointer; border:none; background:transparent;
                 color:var(--text-muted); transition:background .15s,color .15s; }
.jobs-sub-tab:hover  { background:var(--hover-bg-strong,rgba(255,255,255,0.06)); color:var(--text-primary); }
.jobs-sub-tab.active { background:rgba(6,182,212,0.12); color:#22d3ee; }

/* Split layout */
.jobs-split { display:flex; gap:0; height:520px; overflow:hidden; }
.jobs-list  { flex:0 0 55%; overflow-y:auto; padding-right:12px; border-right:1px solid rgba(255,255,255,0.06); }
.jobs-detail { flex:1; overflow-y:auto; padding-left:16px; }
.jobs-detail.hidden-panel { display:none; }
.jobs-detail-placeholder { display:flex; flex-direction:column; align-items:center; justify-content:center;
    height:100%; gap:8px; color:var(--text-muted); font-size:13px; opacity:.5; }

/* Task rows */
.job-row { display:flex; align-items:center; gap:10px; padding:10px 8px; border-radius:10px;
           cursor:pointer; transition:background .12s; border:1px solid transparent; }
.job-row:hover  { background:var(--hover-bg-strong,rgba(255,255,255,0.05)); }
.job-row.active { background:rgba(6,182,212,0.08); border-color:rgba(6,182,212,0.2); }
.job-row + .job-row { margin-top:4px; }

/* Status dot */
.job-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.job-dot.green  { background:#22c55e; box-shadow:0 0 4px rgba(34,197,94,.5); }
.job-dot.amber  { background:#f59e0b; box-shadow:0 0 4px rgba(245,158,11,.5); }
.job-dot.red    { background:#ef4444; box-shadow:0 0 4px rgba(239,68,68,.5); }
.job-dot.gray   { background:#6b7280; }

/* Badges */
.job-badge { display:inline-flex; align-items:center; padding:2px 8px; border-radius:20px;
             font-size:11px; font-weight:500; border:1px solid; white-space:nowrap; flex-shrink:0; }
.job-meta  { font-size:12px; color:var(--text-muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

/* Row actions (show on hover) */
.job-row-actions { display:flex; gap:2px; flex-shrink:0; opacity:0; transition:opacity .12s; }
.job-row:hover .job-row-actions { opacity:1; }
.job-act-btn { display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px;
               border-radius:6px; border:none; background:transparent; cursor:pointer;
               color:var(--text-muted); transition:background .12s, color .12s; }
.job-act-btn:hover { background:rgba(255,255,255,0.08); color:var(--text-primary); }
.job-act-btn.danger:hover { background:rgba(239,68,68,.15); color:#ef4444; }

/* Toggle */
.job-toggle { position:relative; width:34px; height:18px; flex-shrink:0; cursor:pointer; }
.job-toggle input { opacity:0; width:0; height:0; }
.job-toggle-track { position:absolute; inset:0; border-radius:9px; background:rgba(255,255,255,0.15);
                    transition:background .2s; }
.job-toggle input:checked ~ .job-toggle-track { background:#22c55e; }
.job-toggle-thumb { position:absolute; top:2px; left:2px; width:14px; height:14px; border-radius:50%;
                    background:#fff; transition:transform .2s; }
.job-toggle input:checked ~ .job-toggle-thumb { transform:translateX(16px); }

/* Section header */
.jobs-section-hdr { display:flex; align-items:center; justify-content:space-between;
                    margin-bottom:12px; padding:0 8px; }
.jobs-section-title { font-size:13px; font-weight:600; color:var(--text-muted); letter-spacing:.05em; text-transform:uppercase; }

/* New task button */
.jobs-new-btn { display:inline-flex; align-items:center; gap:5px; padding:5px 12px; border-radius:8px;
                font-size:12px; font-weight:500; cursor:pointer; border:1px solid rgba(6,182,212,.3);
                background:rgba(6,182,212,.08); color:#22d3ee; transition:background .12s; }
.jobs-new-btn:hover { background:rgba(6,182,212,.16); }

/* Detail panel */
.jobs-detail-title { font-size:15px; font-weight:600; color:var(--text-primary); margin-bottom:2px; }
.jobs-detail-sub   { font-size:12px; color:var(--text-muted); margin-bottom:16px; }
.jobs-field-label  { font-size:12px; font-weight:500; color:var(--text-muted); margin-bottom:4px; display:block; }
.jobs-field-value  { font-size:13px; color:var(--text-primary); }
.jobs-input { width:100%; padding:7px 10px; border-radius:8px; font-size:13px;
              border:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.04);
              color:var(--text-primary); outline:none; transition:border-color .15s; }
.jobs-input:focus { border-color:rgba(6,182,212,.4); }
.jobs-textarea { resize:vertical; min-height:72px; font-family:inherit; line-height:1.5; }
.jobs-select { appearance:none; cursor:pointer; }
.jobs-schedule-preview { margin-top:5px; font-size:12px; color:#22d3ee; min-height:16px; transition:opacity .15s; }

/* Action buttons */
.jobs-btn { display:inline-flex; align-items:center; gap:5px; padding:6px 14px; border-radius:8px;
            font-size:13px; font-weight:500; cursor:pointer; border:none; transition:background .12s; }
.jobs-btn-primary  { background:rgba(6,182,212,.15); color:#22d3ee; border:1px solid rgba(6,182,212,.3); }
.jobs-btn-primary:hover  { background:rgba(6,182,212,.25); }
.jobs-btn-secondary { background:rgba(255,255,255,.06); color:var(--text-muted); border:1px solid rgba(255,255,255,.1); }
.jobs-btn-secondary:hover { background:rgba(255,255,255,.1); color:var(--text-primary); }
.jobs-btn-danger   { background:rgba(239,68,68,.1); color:#ef4444; border:1px solid rgba(239,68,68,.2); }
.jobs-btn-danger:hover  { background:rgba(239,68,68,.2); }
.jobs-btn-amber    { background:rgba(245,158,11,.1); color:#f59e0b; border:1px solid rgba(245,158,11,.2); }
.jobs-btn-amber:hover  { background:rgba(245,158,11,.2); }
.jobs-btn:disabled { opacity:.45; cursor:not-allowed; }

/* Undo chip */
.jobs-undo-chip { display:inline-flex; align-items:center; gap:8px; padding:5px 12px; border-radius:8px;
                  background:rgba(239,68,68,.12); color:#ef4444; font-size:12px; border:1px solid rgba(239,68,68,.25); }
.jobs-undo-btn { background:none; border:none; color:#ef4444; cursor:pointer; font-weight:600; padding:0; }

/* Run history */
.jobs-history-item { display:flex; align-items:flex-start; gap:8px; padding:8px 0;
                     border-bottom:1px solid rgba(255,255,255,.05); }
.jobs-history-item:last-child { border-bottom:none; }

/* Document table */
.jobs-doc-table { width:100%; border-collapse:collapse; font-size:12px; }
.jobs-doc-table th { padding:6px 8px; text-align:left; color:var(--text-muted); font-weight:500;
                     border-bottom:1px solid rgba(255,255,255,.08); white-space:nowrap; }
.jobs-doc-table td { padding:7px 8px; vertical-align:middle; border-bottom:1px solid rgba(255,255,255,.04); }
.jobs-doc-table tr:last-child td { border-bottom:none; }
.jobs-uri-cell { max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.jobs-uri-edit { display:inline-flex; align-items:center; gap:4px; }
.jobs-uri-input { padding:3px 6px; border-radius:5px; font-size:11px; width:120px;
                  border:1px solid rgba(6,182,212,.4); background:rgba(255,255,255,.04);
                  color:var(--text-primary); outline:none; }
.jobs-icon-btn { display:inline-flex; align-items:center; justify-content:center; width:22px; height:22px;
                 border-radius:5px; border:none; background:transparent; cursor:pointer;
                 color:var(--text-muted); transition:background .1s, color .1s; }
.jobs-icon-btn:hover { background:rgba(255,255,255,.08); color:var(--text-primary); }

/* Dimmed unmonitored section */
.jobs-unmonitored { opacity:.45; }
.jobs-unmonitored .jobs-section-title { color:var(--text-muted); }

/* Spinner */
@keyframes jobs-spin { to { transform:rotate(360deg); } }
.jobs-spinner { display:inline-block; width:14px; height:14px; border:2px solid rgba(255,255,255,.15);
                border-top-color:#22d3ee; border-radius:50%; animation:jobs-spin .7s linear infinite; }

/* Divider */
.jobs-divider { border:none; border-top:1px solid rgba(255,255,255,.07); margin:14px 0; }

/* Result inline */
.jobs-result-line { font-size:12px; color:#22c55e; margin-top:6px; display:flex; align-items:center; gap:5px; }
.jobs-result-line.error { color:#ef4444; }
.jobs-result-files { display:flex; flex-wrap:wrap; gap:4px; margin-top:5px; }
.jobs-result-file { font-size:11px; padding:2px 8px; border-radius:10px;
                    background:rgba(34,197,94,.1); color:#22c55e;
                    border:1px solid rgba(34,197,94,.25); }

/* No-source chip */
.jobs-no-source { display:inline-flex; align-items:center; gap:4px; padding:1px 7px; border-radius:10px;
                  font-size:11px; background:rgba(245,158,11,.1); color:#f59e0b; border:1px solid rgba(245,158,11,.25); }

/* Scrollbar styling */
.jobs-list::-webkit-scrollbar, .jobs-detail::-webkit-scrollbar { width:4px; }
.jobs-list::-webkit-scrollbar-track, .jobs-detail::-webkit-scrollbar-track { background:transparent; }
.jobs-list::-webkit-scrollbar-thumb, .jobs-detail::-webkit-scrollbar-thumb { background:rgba(255,255,255,.12); border-radius:2px; }
`;
        document.head.appendChild(s);
    }

    // ── SVG icons ──────────────────────────────────────────────────────────────

    const ICONS = {
        plus:    `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>`,
        edit:    `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 013.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>`,
        trash:   `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M9 7V4h6v3M3 7h18"/></svg>`,
        play:    `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 3l14 9-14 9V3z"/></svg>`,
        sync:    `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>`,
        reindex: `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2v-4M9 21H5a2 2 0 01-2-2v-4m0 0h18"/></svg>`,
        clock:   `<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path stroke-linecap="round" d="M12 6v6l4 2"/></svg>`,
        check:   `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>`,
        x:       `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>`,
        pencil:  `<svg width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 013.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>`,
        history: `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
        config:  `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"/></svg>`,
        jobs:    `<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="2" y="7" width="20" height="14" rx="2"/><path stroke-linecap="round" stroke-linejoin="round" d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/></svg>`,
    };

    // ── API helpers ────────────────────────────────────────────────────────────

    async function _api(method, path, body) {
        const opts = {
            method,
            headers: { 'Authorization': `Bearer ${AUTH()}`, 'Content-Type': 'application/json' },
        };
        if (body !== undefined) opts.body = JSON.stringify(body);
        const r = await fetch(BASE + path, opts);
        if (!r.ok) {
            let msg = `HTTP ${r.status}`;
            try { msg = (await r.json()).error || msg; } catch {}
            throw new Error(msg);
        }
        return r.json();
    }

    // ── Schedule preview ───────────────────────────────────────────────────────

    function _scheduleToHuman(expr) {
        if (!expr) return '';
        const e = expr.trim();

        // interval shorthand
        if (e.startsWith('interval:')) {
            const raw = e.slice(9);
            const num = parseInt(raw);
            if (raw.endsWith('m'))  return `Every ${num} minute${num !== 1 ? 's' : ''}`;
            if (raw.endsWith('h'))  return `Every ${num} hour${num !== 1 ? 's' : ''}`;
            if (raw.endsWith('d'))  return `Every ${num} day${num !== 1 ? 's' : ''}`;
            if (raw.endsWith('s'))  return `Every ${num} second${num !== 1 ? 's' : ''}`;
            return `Every ${raw}`;
        }

        // cron: min hour dom mon dow
        const parts = e.split(/\s+/);
        if (parts.length !== 5) return '';
        const [min, hour, dom, , dow] = parts;

        const pad = n => String(n).padStart(2, '0');
        const timeStr = (h, m) => {
            const hh = parseInt(h), mm = parseInt(m);
            if (isNaN(hh) || isNaN(mm)) return null;
            const ampm = hh < 12 ? 'AM' : 'PM';
            const h12 = hh === 0 ? 12 : hh > 12 ? hh - 12 : hh;
            return mm === 0 ? `${h12} ${ampm}` : `${h12}:${pad(mm)} ${ampm}`;
        };
        const t = timeStr(hour, min);

        const DAYS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
        const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

        // Common patterns
        if (e === '* * * * *')  return 'Every minute';
        if (min === '*' && hour === '*') return 'Every minute';
        if (dow === '1-5' && t)  return `Weekdays at ${t}`;
        if (dow === '6,0' || dow === '0,6') return t ? `Weekends at ${t}` : 'Weekends';

        // Day of week (0 or 1-7)
        if (dom === '*' && dow !== '*') {
            const dayIdx = parseInt(dow);
            const dayName = !isNaN(dayIdx) ? DAYS[dayIdx % 7] : null;
            if (t && dayName) return `Weekly on ${dayName} at ${t}`;
            if (dayName) return `Weekly on ${dayName}`;
        }

        // Every N hours
        if (min === '0' && hour.startsWith('*/')) {
            const n = parseInt(hour.slice(2));
            return `Every ${n} hour${n !== 1 ? 's' : ''}`;
        }

        // Every N minutes
        if (min.startsWith('*/') && hour === '*') {
            const n = parseInt(min.slice(2));
            return `Every ${n} minute${n !== 1 ? 's' : ''}`;
        }

        if (dom === '*' && dow === '*' && t) return `Daily at ${t}`;
        if (t) return `At ${t}`;
        return e;
    }

    function _nextRunApprox(expr) {
        if (!expr) return null;
        try {
            const now = new Date();
            const next = new Date(now.getTime() + 60000); // placeholder: at least "in a minute"
            // Simple: show next occurrence description
            const human = _scheduleToHuman(expr);
            if (!human) return null;
            const diffMs = next - now;
            const diffM = Math.round(diffMs / 60000);
            if (diffM < 60) return `in ~${diffM}m`;
        } catch {}
        return null;
    }

    // ── Relative time ──────────────────────────────────────────────────────────

    function _relTime(iso) {
        if (!iso) return null;
        const d = new Date(iso);
        const diffMs = Date.now() - d.getTime();
        const diffM = Math.floor(diffMs / 60000);
        if (diffM < 1)   return 'just now';
        if (diffM < 60)  return `${diffM}m ago`;
        const diffH = Math.floor(diffM / 60);
        if (diffH < 24)  return `${diffH}h ago`;
        const diffD = Math.floor(diffH / 24);
        return `${diffD}d ago`;
    }

    function _isoToDatetimeLocal(iso) {
        if (!iso) return '';
        try {
            const d = new Date(iso);
            // datetime-local needs "YYYY-MM-DDTHH:MM" in local time
            const pad = n => String(n).padStart(2, '0');
            return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
        } catch { return ''; }
    }

    function _nextSyncLabel(iso) {
        if (!iso) return '—';
        const d = new Date(iso);
        const diffMs = d.getTime() - Date.now();
        if (diffMs <= 0) {
            const overM = Math.floor(-diffMs / 60000);
            if (overM < 60)  return `overdue by ${overM}m`;
            const overH = Math.floor(overM / 60);
            if (overH < 24)  return `overdue by ${overH}h`;
            return `overdue by ${Math.floor(overH / 24)}d`;
        }
        const diffM = Math.floor(diffMs / 60000);
        if (diffM < 60)  return `in ${diffM}m`;
        const diffH = Math.floor(diffM / 60);
        if (diffH < 24)  return `in ${diffH}h`;
        return `in ${Math.floor(diffH / 24)}d`;
    }

    // ── Toast ──────────────────────────────────────────────────────────────────

    function _toast(msg, type = 'success') {
        // Reuse platform's showToast if available
        if (typeof showToast === 'function') { showToast(msg, type); return; }
        if (typeof window.showToast === 'function') { window.showToast(msg, type); return; }
        console.log(`[Jobs] ${type}: ${msg}`);
    }

    // ── Module state ───────────────────────────────────────────────────────────

    let _root = null;
    let _profiles = [];
    let _tasks = [];
    let _collections = [];
    let _activeTaskId = null;
    let _activeSyncId = null;
    let _activeSubTab = 'scheduled';
    let _pendingCollectionId = null;

    // ══════════════════════════════════════════════════════════════════════════
    // Entry point
    // ══════════════════════════════════════════════════════════════════════════

    function initJobsTab(containerId) {
        _injectCSS();
        _root = document.getElementById(containerId);
        if (!_root) return;

        _root.innerHTML = `
            <div class="jobs-sub-tabs" id="jobs-sub-tabs">
                <button class="jobs-sub-tab active" data-subtab="scheduled">
                    ${ICONS.jobs} Profile Jobs
                </button>
                <button class="jobs-sub-tab" data-subtab="sync">
                    ${ICONS.sync} Platform Jobs
                </button>
            </div>
            <div id="jobs-panel-scheduled"></div>
            <div id="jobs-panel-sync" class="hidden"></div>
        `;

        _root.querySelectorAll('.jobs-sub-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                _root.querySelectorAll('.jobs-sub-tab').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                _activeSubTab = btn.dataset.subtab;
                _root.querySelectorAll('[id^="jobs-panel-"]').forEach(p => p.classList.add('hidden'));
                document.getElementById(`jobs-panel-${_activeSubTab}`)?.classList.remove('hidden');
            });
        });

        // Load both in parallel
        _loadProfiles().then(() => {
            _renderScheduledTab();
            _renderSyncTab();
        });
    }

    async function _loadProfiles() {
        try {
            const data = await _api('GET', '/profiles');
            _profiles = data.profiles || data || [];
        } catch { _profiles = []; }
    }

    function _profileById(id) { return _profiles.find(p => p.id === id) || null; }

    // ══════════════════════════════════════════════════════════════════════════
    // SCHEDULED TASKS
    // ══════════════════════════════════════════════════════════════════════════

    async function _renderScheduledTab() {
        const panel = document.getElementById('jobs-panel-scheduled');
        if (!panel) return;
        panel.innerHTML = `<div class="jobs-split"><div class="jobs-list" id="sched-list"></div><div class="jobs-detail hidden-panel" id="sched-detail"></div></div>`;
        await _loadAndRenderTasks();
    }

    async function _loadAndRenderTasks() {
        const list = document.getElementById('sched-list');
        if (!list) return;
        try {
            const data = await _api('GET', '/scheduled-tasks');
            _tasks = data.tasks || [];
            _renderTaskList(_tasks, list);
            if (_tasks.length) {
                // Restore active selection or auto-select first
                const toSelect = _activeTaskId
                    ? _tasks.find(t => t.id === _activeTaskId) || _tasks[0]
                    : _tasks[0];
                _openTaskPanel(toSelect);
            }
        } catch (e) {
            list.innerHTML = `<div class="text-sm" style="color:var(--text-muted);padding:8px">Failed to load tasks: ${e.message}</div>`;
        }
    }

    function _renderTaskList(tasks, container) {
        const hdr = `
            <div class="jobs-section-hdr">
                <span class="jobs-section-title">${tasks.length} Task${tasks.length !== 1 ? 's' : ''}</span>
                <button class="jobs-new-btn" id="sched-new-btn">${ICONS.plus} New Task</button>
            </div>`;

        if (!tasks.length) {
            container.innerHTML = hdr + `<div style="padding:24px 8px;text-align:center;color:var(--text-muted);font-size:13px;">
                No scheduled tasks yet.<br>
                <span style="font-size:12px;opacity:.7">Create one here or say "schedule something" in chat.</span>
            </div>`;
        } else {
            container.innerHTML = hdr + tasks.map(t => _taskRowHTML(t)).join('');
        }

        container.querySelector('#sched-new-btn')?.addEventListener('click', e => { e.stopPropagation(); _openTaskPanel(null); });
        container.querySelectorAll('.job-row[data-task-id]').forEach(row => {
            row.addEventListener('click', e => {
                if (e.target.closest('.job-act-btn, .job-toggle')) return;
                const task = _tasks.find(t => t.id === row.dataset.taskId);
                if (task) _openTaskPanel(task);
            });
            _wireTaskRowActions(row);
        });
    }

    function _taskRowHTML(task) {
        const prof = _profileById(task.profile_id);
        const profType = prof?.profile_type || 'llm_only';
        const ifoc = IFOC_COLORS[profType] || IFOC_COLORS.llm_only;
        const profTag = prof?.tag || '?';

        const dotClass = !task.enabled ? 'amber' : task.last_run_status === 'error' ? 'red' : 'green';
        const human = _scheduleToHuman(task.schedule) || task.schedule;
        const lastRan = task.last_run_at ? _relTime(task.last_run_at) : 'Never run';
        const lastStatus = task.last_run_status;
        const statusColor = lastStatus === 'error' ? '#ef4444' : lastStatus === 'skipped' ? '#f59e0b' : 'var(--text-muted)';
        const checked = task.enabled ? 'checked' : '';
        const isActive = task.id === _activeTaskId;

        return `<div class="job-row${isActive ? ' active' : ''}" data-task-id="${task.id}">
            <span class="job-dot ${dotClass}"></span>
            <div style="flex:1;min-width:0">
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
                    <span style="font-size:13px;font-weight:500;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px">${_esc(task.name)}</span>
                    <span class="job-badge" style="background:${ifoc.bg};border-color:${ifoc.border};color:${ifoc.text}">@${_esc(profTag)}</span>
                </div>
                <div style="display:flex;align-items:center;gap:8px">
                    <span class="job-meta">${ICONS.clock} ${_esc(human)}</span>
                    <span class="job-meta" style="color:${statusColor}">${_esc(lastRan)}</span>
                </div>
            </div>
            <div class="job-row-actions">
                <button class="job-act-btn" data-action="run" title="Run Now">${ICONS.play}</button>
                <button class="job-act-btn" data-action="edit" title="Edit">${ICONS.edit}</button>
                <button class="job-act-btn danger" data-action="delete" title="Delete">${ICONS.trash}</button>
            </div>
            <label class="job-toggle" title="${task.enabled ? 'Pause' : 'Enable'}">
                <input type="checkbox" ${checked} data-task-id="${task.id}">
                <span class="job-toggle-track"></span>
                <span class="job-toggle-thumb"></span>
            </label>
        </div>`;
    }

    function _wireTaskRowActions(row) {
        const taskId = row.dataset.taskId;

        row.querySelector('[data-action="run"]')?.addEventListener('click', async e => {
            e.stopPropagation();
            const btn = e.currentTarget;
            btn.innerHTML = `<span class="jobs-spinner"></span>`;
            btn.disabled = true;
            try {
                await _api('POST', `/scheduled-tasks/${taskId}/run-now`);
                btn.innerHTML = ICONS.check;
                btn.style.color = '#22c55e';
                setTimeout(() => { btn.innerHTML = ICONS.play; btn.style.color = ''; btn.disabled = false; }, 2000);
                _toast('Task triggered');
            } catch (e) {
                btn.innerHTML = ICONS.play;
                btn.disabled = false;
                _toast(e.message, 'error');
            }
        });

        row.querySelector('[data-action="edit"]')?.addEventListener('click', e => {
            e.stopPropagation();
            const task = _tasks.find(t => t.id === taskId);
            if (task) _openTaskPanel(task);
        });

        row.querySelector('[data-action="delete"]')?.addEventListener('click', e => {
            e.stopPropagation();
            _confirmDeleteTask(taskId, row);
        });

        row.querySelector('input[type="checkbox"]')?.addEventListener('change', async e => {
            const enabled = e.target.checked ? 1 : 0;
            try {
                await _api('PUT', `/scheduled-tasks/${taskId}`, { enabled });
                const task = _tasks.find(t => t.id === taskId);
                if (task) task.enabled = enabled;
                const dot = row.querySelector('.job-dot');
                if (dot) { dot.className = `job-dot ${!enabled ? 'amber' : task?.last_run_status === 'error' ? 'red' : 'green'}`; }
            } catch (err) {
                e.target.checked = !e.target.checked;
                _toast(err.message, 'error');
            }
        });
    }

    function _confirmDeleteTask(taskId, row) {
        const task = _tasks.find(t => t.id === taskId);
        if (!task) return;
        // Replace row with undo chip for 4 seconds
        const orig = row.outerHTML;
        const chip = document.createElement('div');
        chip.style.cssText = 'padding:8px;';
        chip.innerHTML = `<div class="jobs-undo-chip">
            Deleting "${_esc(task.name)}" &nbsp;
            <button class="jobs-undo-btn" id="undo-delete-${taskId}">Undo</button>
        </div>`;
        row.replaceWith(chip);

        let cancelled = false;
        chip.querySelector(`#undo-delete-${taskId}`)?.addEventListener('click', () => {
            cancelled = true;
            const list = document.getElementById('sched-list');
            chip.outerHTML = orig;
            // Re-render properly
            _loadAndRenderTasks();
        });

        setTimeout(async () => {
            if (cancelled) return;
            try {
                await _api('DELETE', `/scheduled-tasks/${taskId}`);
                _tasks = _tasks.filter(t => t.id !== taskId);
                if (_activeTaskId === taskId) {
                    _activeTaskId = null;
                    const detail = document.getElementById('sched-detail');
                    if (detail) { detail.innerHTML = ''; detail.classList.add('hidden-panel'); }
                }
                chip.remove();
                // Update count
                const title = document.querySelector('#sched-list .jobs-section-title');
                if (title) title.textContent = `${_tasks.length} Task${_tasks.length !== 1 ? 's' : ''}`;
                _toast('Task deleted');
            } catch (err) {
                _loadAndRenderTasks();
                _toast(err.message, 'error');
            }
        }, 4000);
    }

    // ── Task detail / edit panel ───────────────────────────────────────────────

    function _openTaskPanel(task) {
        const detail = document.getElementById('sched-detail');
        if (!detail) return;

        _activeTaskId = task?.id || null;

        // Highlight active row
        document.querySelectorAll('.job-row[data-task-id]').forEach(r => {
            r.classList.toggle('active', r.dataset.taskId === _activeTaskId);
        });

        detail.classList.remove('hidden-panel');
        detail.innerHTML = _taskFormHTML(task);
        _wireTaskForm(task, detail);
    }

    function _taskFormHTML(task) {
        const isNew = !task;
        const profOptions = _profiles.map(p => {
            const ifoc = IFOC_COLORS[p.profile_type] || IFOC_COLORS.llm_only;
            return `<option value="${_esc(p.id)}" ${task?.profile_id === p.id ? 'selected' : ''}>@${_esc(p.tag)} — ${ifoc.label}</option>`;
        }).join('');

        const outChannel = task?.output_channel || 'none';
        const outConfig = (() => { try { return JSON.parse(task?.output_config || '{}'); } catch { return {}; } })();
        const sessionCtx = task?.session_id ? 'current' : 'new';
        const overlap = task?.overlap_policy || 'skip';
        const maxTok = task?.max_tokens_per_run || '';
        const schedule = task?.schedule || '';
        const human = _scheduleToHuman(schedule);

        return `
        <div>
            <div class="jobs-detail-title">${isNew ? 'New Task' : _esc(task.name)}</div>
            <div class="jobs-detail-sub">${isNew ? 'Schedule an agent task' : 'Edit scheduled task'}</div>

            <div style="display:flex;flex-direction:column;gap:12px">
                <div>
                    <label class="jobs-field-label">Name</label>
                    <input class="jobs-input" id="tf-name" placeholder="Daily report" value="${_esc(task?.name || '')}">
                </div>
                <div>
                    <label class="jobs-field-label">Prompt</label>
                    <textarea class="jobs-input jobs-textarea" id="tf-prompt" placeholder="Generate a summary of today's activity...">${_esc(task?.prompt || '')}</textarea>
                </div>
                <div>
                    <label class="jobs-field-label">Schedule</label>
                    <input class="jobs-input" id="tf-schedule" placeholder="0 9 * * 1-5  or  interval:1h" value="${_esc(schedule)}">
                    <div class="jobs-schedule-preview" id="tf-schedule-preview">${human ? human : ''}</div>
                </div>
                <div>
                    <label class="jobs-field-label">Profile</label>
                    <select class="jobs-input jobs-select" id="tf-profile">${profOptions}</select>
                </div>
                <div>
                    <label class="jobs-field-label">Session Context</label>
                    <select class="jobs-input jobs-select" id="tf-session">
                        <option value="new" ${sessionCtx === 'new' ? 'selected' : ''}>New session per run</option>
                        <option value="current" ${sessionCtx === 'current' ? 'selected' : ''}>Current session (pin to active)</option>
                    </select>
                </div>
                <div>
                    <label class="jobs-field-label">Output Channel</label>
                    <select class="jobs-input jobs-select" id="tf-channel">
                        <option value="none" ${outChannel === 'none' || !outChannel ? 'selected' : ''}>None (chat only)</option>
                        <option value="email" ${outChannel === 'email' ? 'selected' : ''}>Email</option>
                        <option value="webhook" ${outChannel === 'webhook' ? 'selected' : ''}>Webhook</option>
                    </select>
                </div>
                <div id="tf-channel-config" class="${(outChannel === 'email' || outChannel === 'webhook') ? '' : 'hidden'}">
                    <label class="jobs-field-label" id="tf-channel-label">${outChannel === 'webhook' ? 'Webhook URL' : 'Email address'}</label>
                    <input class="jobs-input" id="tf-channel-value" placeholder="${outChannel === 'webhook' ? 'https://...' : 'user@example.com'}" value="${_esc(outConfig.url || outConfig.to_address || '')}">
                </div>
                <div>
                    <label class="jobs-field-label">Overlap Policy</label>
                    <select class="jobs-input jobs-select" id="tf-overlap">
                        <option value="skip"  ${overlap === 'skip'  ? 'selected' : ''}>Skip (if previous run still active)</option>
                        <option value="queue" ${overlap === 'queue' ? 'selected' : ''}>Queue (wait up to 5 min)</option>
                        <option value="allow" ${overlap === 'allow' ? 'selected' : ''}>Allow concurrent runs</option>
                    </select>
                </div>
                <div>
                    <label class="jobs-field-label">Max Tokens per Run <span style="opacity:.5">(optional)</span></label>
                    <input class="jobs-input" id="tf-maxtok" type="number" placeholder="Unlimited" value="${_esc(String(maxTok))}">
                </div>
            </div>

            <hr class="jobs-divider">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                <button class="jobs-btn jobs-btn-primary" id="tf-save">${isNew ? ICONS.plus + ' Create' : ICONS.check + ' Save'}</button>
                <button class="jobs-btn jobs-btn-secondary" id="tf-cancel">${ICONS.x} Cancel</button>
                ${!isNew ? `<button class="jobs-btn jobs-btn-danger" id="tf-delete" style="margin-left:auto">${ICONS.trash} Delete</button>` : ''}
            </div>

            ${!isNew ? `
            <hr class="jobs-divider">
            <div>
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                    <span style="font-size:12px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em">Recent Runs</span>
                    <button class="jobs-btn jobs-btn-secondary" id="tf-history" style="padding:3px 9px;font-size:11px">${ICONS.history} Load history</button>
                </div>
                <div id="tf-history-list"><span style="font-size:12px;color:var(--text-muted)">Click "Load history" to view recent runs.</span></div>
            </div>` : ''}
        </div>`;
    }

    function _wireTaskForm(task, container) {
        const isNew = !task;

        // Live schedule preview
        container.querySelector('#tf-schedule')?.addEventListener('input', e => {
            const preview = container.querySelector('#tf-schedule-preview');
            if (preview) preview.textContent = _scheduleToHuman(e.target.value) || '';
        });

        // Channel config visibility
        container.querySelector('#tf-channel')?.addEventListener('change', e => {
            const cfg = container.querySelector('#tf-channel-config');
            const lbl = container.querySelector('#tf-channel-label');
            const val = container.querySelector('#tf-channel-value');
            const ch = e.target.value;
            if (ch === 'email' || ch === 'webhook') {
                cfg?.classList.remove('hidden');
                if (lbl) lbl.textContent = ch === 'webhook' ? 'Webhook URL' : 'Email address';
                if (val) val.placeholder = ch === 'webhook' ? 'https://...' : 'user@example.com';
            } else {
                cfg?.classList.add('hidden');
            }
        });

        // Save
        container.querySelector('#tf-save')?.addEventListener('click', async () => {
            const btn = container.querySelector('#tf-save');
            const name      = container.querySelector('#tf-name')?.value.trim();
            const prompt    = container.querySelector('#tf-prompt')?.value.trim();
            const schedule  = container.querySelector('#tf-schedule')?.value.trim();
            const profileId = container.querySelector('#tf-profile')?.value;
            const sessionCtx= container.querySelector('#tf-session')?.value;
            const channel   = container.querySelector('#tf-channel')?.value;
            const chanVal   = container.querySelector('#tf-channel-value')?.value.trim();
            const overlap   = container.querySelector('#tf-overlap')?.value;
            const maxTok    = parseInt(container.querySelector('#tf-maxtok')?.value) || null;

            if (!name || !prompt || !schedule) { _toast('Name, prompt and schedule are required', 'error'); return; }

            const output_channel = channel === 'none' ? null : channel;
            let output_config = null;
            if (channel === 'email' && chanVal)   output_config = JSON.stringify({ to_address: chanVal });
            if (channel === 'webhook' && chanVal) output_config = JSON.stringify({ url: chanVal });

            const payload = { name, prompt, schedule, profile_id: profileId, overlap_policy: overlap,
                              output_channel, output_config, max_tokens_per_run: maxTok,
                              session_context: sessionCtx };

            btn.disabled = true;
            btn.innerHTML = `<span class="jobs-spinner"></span> Saving…`;
            try {
                if (isNew) {
                    const res = await _api('POST', '/scheduled-tasks', payload);
                    _tasks.unshift(res.task);
                    _activeTaskId = res.task.id;
                    _toast('Task created');
                } else {
                    const res = await _api('PUT', `/scheduled-tasks/${task.id}`, payload);
                    const idx = _tasks.findIndex(t => t.id === task.id);
                    if (idx >= 0) _tasks[idx] = res.task;
                    _toast('Task saved');
                }
                await _loadAndRenderTasks();
                // Re-open the saved task
                const saved = _tasks.find(t => t.id === _activeTaskId);
                if (saved) _openTaskPanel(saved);
            } catch (e) {
                btn.disabled = false;
                btn.innerHTML = isNew ? ICONS.plus + ' Create' : ICONS.check + ' Save';
                _toast(e.message, 'error');
            }
        });

        // Cancel
        container.querySelector('#tf-cancel')?.addEventListener('click', () => {
            const detail = document.getElementById('sched-detail');
            if (detail) { detail.innerHTML = ''; detail.classList.add('hidden-panel'); }
            _activeTaskId = null;
            document.querySelectorAll('.job-row[data-task-id]').forEach(r => r.classList.remove('active'));
        });

        // Delete
        container.querySelector('#tf-delete')?.addEventListener('click', () => {
            if (!task) return;
            const row = document.querySelector(`.job-row[data-task-id="${task.id}"]`);
            if (row) _confirmDeleteTask(task.id, row);
            const detail = document.getElementById('sched-detail');
            if (detail) { detail.innerHTML = ''; detail.classList.add('hidden-panel'); }
            _activeTaskId = null;
        });

        // History
        container.querySelector('#tf-history')?.addEventListener('click', async () => {
            if (!task) return;
            const btn = container.querySelector('#tf-history');
            const list = container.querySelector('#tf-history-list');
            btn.disabled = true;
            btn.innerHTML = `<span class="jobs-spinner"></span>`;
            try {
                const data = await _api('GET', `/scheduled-tasks/${task.id}/runs?limit=10`);
                const runs = data.runs || [];
                if (!runs.length) {
                    list.innerHTML = `<span style="font-size:12px;color:var(--text-muted)">No runs yet.</span>`;
                } else {
                    list.innerHTML = runs.map(r => _runItemHTML(r)).join('');
                }
                btn.style.display = 'none';
            } catch (e) {
                list.innerHTML = `<span style="font-size:12px;color:#ef4444">${e.message}</span>`;
                btn.disabled = false;
                btn.innerHTML = ICONS.history + ' Load history';
            }
        });
    }

    function _runItemHTML(run) {
        const dotColor = run.status === 'success' ? '#22c55e' : run.status === 'skipped' ? '#f59e0b' : '#ef4444';
        const started = run.started_at ? _relTime(run.started_at) : '';
        const dur = run.started_at && run.completed_at
            ? `${Math.round((new Date(run.completed_at) - new Date(run.started_at)) / 1000)}s`
            : run.status === 'running' ? 'running…' : '';
        const summary = run.result_summary || run.skip_reason || '';
        return `<div class="jobs-history-item">
            <span style="width:8px;height:8px;border-radius:50%;background:${dotColor};flex-shrink:0;margin-top:3px"></span>
            <div>
                <div style="font-size:12px;color:var(--text-primary);font-weight:500">${_esc(run.status)} ${started ? '· ' + started : ''} ${dur ? '· ' + dur : ''}</div>
                ${summary ? `<div style="font-size:11px;color:var(--text-muted);margin-top:2px;max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(summary)}</div>` : ''}
                ${run.tokens_used ? `<div style="font-size:11px;color:var(--text-muted)">${run.tokens_used.toLocaleString()} tokens</div>` : ''}
            </div>
        </div>`;
    }

    // ══════════════════════════════════════════════════════════════════════════
    // SYNC JOBS
    // ══════════════════════════════════════════════════════════════════════════

    async function _renderSyncTab() {
        const panel = document.getElementById('jobs-panel-sync');
        if (!panel) return;
        panel.innerHTML = `<div class="jobs-split"><div class="jobs-list" id="sync-list"></div><div class="jobs-detail hidden-panel" id="sync-detail"></div></div>`;
        await _loadAndRenderSync();
    }

    async function _loadAndRenderSync() {
        const list = document.getElementById('sync-list');
        if (!list) return;
        try {
            const data = await _api('GET', '/rag/collections');
            const colls = (data.collections || data || []).filter(c => c.repository_type === 'knowledge');
            _collections = colls;
            _renderSyncList(colls, list);
            if (colls.length) {
                // A deep-link request takes priority over normal restore/auto-select
                let toSelect = null;
                if (_pendingCollectionId !== null) {
                    toSelect = colls.find(c => String(c.id) === String(_pendingCollectionId)) || colls[0];
                    _pendingCollectionId = null;
                } else {
                    toSelect = _activeSyncId
                        ? colls.find(c => String(c.id) === _activeSyncId) || colls[0]
                        : colls[0];
                }
                _openSyncPanel(toSelect);
            }
        } catch (e) {
            list.innerHTML = `<div class="text-sm" style="color:var(--text-muted);padding:8px">Failed to load collections: ${e.message}</div>`;
        }
    }

    function _renderSyncList(colls, container) {
        const monitored   = colls.filter(c => (c.sync_doc_count || 0) > 0);
        const unmonitored = colls.filter(c => !(c.sync_doc_count || 0));

        let html = `<div class="jobs-section-hdr"><span class="jobs-section-title">${colls.length} Collection${colls.length !== 1 ? 's' : ''}</span></div>`;

        if (!colls.length) {
            html += `<div style="padding:24px 8px;text-align:center;color:var(--text-muted);font-size:13px;">No knowledge repositories found.</div>`;
        } else {
            html += monitored.map(c => _syncRowHTML(c)).join('');
            if (unmonitored.length) {
                html += `<div class="jobs-unmonitored" style="margin-top:16px">
                    <div class="jobs-section-hdr"><span class="jobs-section-title">Unmonitored (${unmonitored.length})</span></div>
                    ${unmonitored.map(c => _syncRowHTML(c)).join('')}
                </div>`;
            }
        }

        container.innerHTML = html;
        container.querySelectorAll('.job-row[data-coll-id]').forEach(row => {
            row.addEventListener('click', e => {
                if (e.target.closest('.job-act-btn, .job-toggle')) return;
                const coll = colls.find(c => String(c.id) === row.dataset.collId);
                if (coll) _openSyncPanel(coll);
            });
            _wireSyncRowActions(row, colls);
        });
    }

    function _syncRowHTML(coll) {
        const syncCount  = coll.sync_doc_count || 0;
        const staleCount = coll.stale_doc_count || 0;
        const total      = coll.document_count || 0;
        const interval   = coll.sync_interval || 'daily';
        const backend    = (coll.backend_type || 'chromadb').toLowerCase();
        const isActive   = String(coll.id) === String(_activeSyncId);

        let dotClass = 'gray';
        if (syncCount > 0) dotClass = staleCount > 0 ? 'amber' : 'green';

        const backendColor = backend === 'teradata' ? '#f59e0b' : backend === 'qdrant' ? '#8b5cf6' : '#22d3ee';
        const lastChecked = coll.last_sync_at ? _relTime(coll.last_sync_at) : null;
        const hasSync = syncCount > 0;
        const masterChecked = hasSync ? 'checked' : '';
        const intervalLabel = INTERVALS.find(i => i.value === interval)?.label || interval;

        return `<div class="job-row${isActive ? ' active' : ''}" data-coll-id="${coll.id}">
            <span class="job-dot ${dotClass}"></span>
            <div style="flex:1;min-width:0">
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">
                    <span style="font-size:13px;font-weight:500;color:var(--text-primary);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:150px">${_esc(coll.name || coll.collection_name)}</span>
                    <span class="job-badge" style="background:rgba(${backendColor === '#22d3ee' ? '6,182,212' : backendColor === '#f59e0b' ? '245,158,11' : '139,92,246'},.12);border-color:rgba(${backendColor === '#22d3ee' ? '6,182,212' : backendColor === '#f59e0b' ? '245,158,11' : '139,92,246'},.3);color:${backendColor}">${backend}</span>
                </div>
                <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                    ${hasSync
                        ? `<span class="job-meta">${syncCount}/${total} synced · ${intervalLabel}${lastChecked ? ' · ' + lastChecked : ''}</span>`
                        : `<span class="job-meta">No sync configured</span>`
                    }
                    ${staleCount > 0 ? `<span class="job-badge" style="background:rgba(245,158,11,.1);border-color:rgba(245,158,11,.25);color:#f59e0b">${staleCount} stale</span>` : ''}
                </div>
            </div>
            <div class="job-row-actions">
                ${hasSync ? `<button class="job-act-btn" data-action="syncnow" title="Sync Now">${ICONS.sync}</button>` : ''}
                <button class="job-act-btn" data-action="configure" title="Configure">${ICONS.config}</button>
            </div>
            <label class="job-toggle" title="${hasSync ? 'Disable all sync' : 'Enable sync'}">
                <input type="checkbox" ${masterChecked} data-coll-id="${coll.id}">
                <span class="job-toggle-track"></span>
                <span class="job-toggle-thumb"></span>
            </label>
        </div>`;
    }

    function _wireSyncRowActions(row, colls) {
        const collId = row.dataset.collId;
        const coll = colls.find(c => String(c.id) === collId);

        row.querySelector('[data-action="syncnow"]')?.addEventListener('click', async e => {
            e.stopPropagation();
            const btn = e.currentTarget;
            btn.innerHTML = `<span class="jobs-spinner"></span>`;
            btn.disabled = true;
            try {
                const res = await _api('POST', `/knowledge/repositories/${collId}/sync`);
                btn.innerHTML = ICONS.check;
                btn.style.color = '#22c55e';
                const updatedFiles = res.updated_files || [];
                const fileNote = updatedFiles.length > 0 ? ` · ${updatedFiles.join(', ')}` : '';
                _toast(`Sync done — ${res.checked || 0} checked, ${res.updated || 0} updated${fileNote}`);
                setTimeout(() => { btn.innerHTML = ICONS.sync; btn.style.color = ''; btn.disabled = false; }, 2500);
                _loadAndRenderSync();
            } catch (err) {
                btn.innerHTML = ICONS.sync;
                btn.disabled = false;
                _toast(err.message, 'error');
            }
        });

        row.querySelector('[data-action="configure"]')?.addEventListener('click', e => {
            e.stopPropagation();
            if (coll) _openSyncPanel(coll);
        });

        row.querySelector('input[type="checkbox"]')?.addEventListener('change', async e => {
            const enable = e.target.checked;
            if (!coll) return;
            // Toggle sync_enabled on all documents in the collection
            try {
                // Load documents, then patch each
                const data = await _api('GET', `/knowledge/repositories/${collId}/documents`);
                const docs = data.documents || [];
                await Promise.all(docs.map(d =>
                    _api('PATCH', `/knowledge/repositories/${collId}/documents/${d.document_id}`, { sync_enabled: enable })
                        .catch(() => {})
                ));
                _toast(enable ? 'Sync enabled for all documents' : 'Sync disabled for all documents');
                await _loadAndRenderSync();
            } catch (err) {
                e.target.checked = !enable;
                _toast(err.message, 'error');
            }
        });
    }

    // ── Sync detail panel ──────────────────────────────────────────────────────

    function _openSyncPanel(coll) {
        const detail = document.getElementById('sync-detail');
        if (!detail) return;

        _activeSyncId = String(coll.id);

        document.querySelectorAll('.job-row[data-coll-id]').forEach(r => {
            r.classList.toggle('active', r.dataset.collId === _activeSyncId);
        });

        detail.classList.remove('hidden-panel');
        detail.innerHTML = _syncDetailHTML(coll);
        _wireSyncDetail(coll, detail);
    }

    function _syncDetailHTML(coll) {
        const interval         = coll.sync_interval || 'daily';
        const syncCount        = coll.sync_doc_count || 0;
        const staleCount       = coll.stale_doc_count || 0;
        const modelLocked      = coll.embedding_model_locked;
        const modelName        = coll.embedding_model || 'all-MiniLM-L6-v2';
        const sourceRoot       = coll.source_root || '';
        const effectiveRoot    = coll.effective_source_root || '';

        const intervalOpts = INTERVALS.map(i =>
            `<option value="${i.value}" ${interval === i.value ? 'selected' : ''}>${i.label}</option>`
        ).join('');

        // Last / next sync timing
        const lastSyncAt  = coll.last_sync_at  || null;
        const nextSyncAt  = coll.next_sync_at  || null;
        const lastStr  = lastSyncAt ? _relTime(lastSyncAt)  : 'Never';
        const lastFull = lastSyncAt ? new Date(lastSyncAt).toLocaleString() : '';
        const nextStr  = nextSyncAt ? _nextSyncLabel(nextSyncAt) : '—';
        const nextFull = nextSyncAt ? new Date(nextSyncAt).toLocaleString() : '';
        const nextColor = nextSyncAt && new Date(nextSyncAt) < new Date() ? '#f59e0b' : 'var(--text-muted)';
        // Convert stored ISO to datetime-local value (strip seconds + tz)
        const nextLocalValue = nextSyncAt ? _isoToDatetimeLocal(nextSyncAt) : '';

        return `
        <div>
            <div class="jobs-detail-title">${_esc(coll.name || coll.collection_name)}</div>
            <div class="jobs-detail-sub" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
                <span>${coll.document_count || 0} docs · ${coll.chunk_count || 0} chunks</span>
                <span>·</span>
                <span>${_esc(modelName)}</span>
                ${modelLocked
                    ? `<span class="job-badge" style="background:rgba(34,197,94,.1);border-color:rgba(34,197,94,.25);color:#22c55e">model locked</span>`
                    : `<span class="job-badge" style="background:rgba(245,158,11,.1);border-color:rgba(245,158,11,.25);color:#f59e0b">model unlocked</span>`}
            </div>

            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;flex-wrap:wrap">
                <div style="flex:1;min-width:120px">
                    <label class="jobs-field-label">Sync Interval</label>
                    <select class="jobs-input jobs-select" id="sd-interval" style="width:100%">${intervalOpts}</select>
                </div>
                <div style="display:flex;flex-direction:column;gap:6px;padding-top:18px">
                    <button class="jobs-btn jobs-btn-primary" id="sd-syncnow">
                        ${ICONS.sync} Sync Now
                    </button>
                    <button class="jobs-btn jobs-btn-amber" id="sd-reindex" title="Re-embeds all documents using the current model">
                        ${ICONS.reindex} Re-index
                    </button>
                </div>
            </div>

            <div style="display:flex;gap:20px;margin-bottom:10px;font-size:12px">
                <div title="${_esc(lastFull)}">
                    <span style="color:var(--text-muted)">Last run:</span>
                    <span style="color:var(--text-primary);margin-left:4px">${_esc(lastStr)}</span>
                </div>
                <div title="${_esc(nextFull)}">
                    <span style="color:var(--text-muted)">Next due:</span>
                    <span style="color:${nextColor};margin-left:4px">${_esc(nextStr)}</span>
                </div>
            </div>

            <div style="margin-bottom:14px">
                <label class="jobs-field-label">Next Run</label>
                <div style="display:flex;gap:6px;align-items:center">
                    <input class="jobs-input" id="sd-next-run" type="datetime-local"
                           value="${_esc(nextLocalValue)}"
                           style="flex:1;font-size:12px">
                    <button class="jobs-btn jobs-btn-secondary" id="sd-next-run-set" style="white-space:nowrap;padding:6px 10px">
                        ${ICONS.check} Set
                    </button>
                </div>
                <div style="margin-top:5px;font-size:11px;color:var(--text-muted);line-height:1.5">
                    Sets the schedule anchor. After each sync the next run advances by one interval.
                </div>
                <div id="sd-next-run-result"></div>
            </div>

            <div style="margin-bottom:14px">
                <label class="jobs-field-label">Source Root</label>
                <div style="display:flex;gap:6px;align-items:center">
                    <input class="jobs-input" id="sd-source-root" type="text"
                           placeholder="${_esc(effectiveRoot)}"
                           value="${_esc(sourceRoot)}"
                           style="flex:1;font-family:monospace;font-size:12px">
                    <button class="jobs-btn jobs-btn-secondary" id="sd-source-root-set" style="white-space:nowrap;padding:6px 10px">
                        ${ICONS.check} Set
                    </button>
                </div>
                <div style="margin-top:5px;font-size:11px;color:var(--text-muted);line-height:1.5">
                    Relative <code style="font-size:10px;background:rgba(255,255,255,.06);padding:1px 4px;border-radius:3px">file://</code> paths resolve against this directory.
                    ${sourceRoot ? '' : `<span style="opacity:.75">Currently using auto-detected root.</span>`}
                </div>
                <div id="sd-source-root-result"></div>
            </div>

            <div id="sd-sync-result"></div>

            <hr class="jobs-divider">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
                <span style="font-size:12px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em">Documents (${syncCount} synced${staleCount ? ' · ' + staleCount + ' stale' : ''})</span>
            </div>
            <div id="sd-docs-container">
                <div style="font-size:12px;color:var(--text-muted)">Loading documents…</div>
            </div>
        </div>`;
    }

    function _wireSyncDetail(coll, container) {
        const collId = coll.id;

        // Interval change
        container.querySelector('#sd-interval')?.addEventListener('change', async e => {
            try {
                await _api('PATCH', `/knowledge/repositories/${collId}`, { sync_interval: e.target.value });
                _toast('Sync interval updated');
                _loadAndRenderSync();
            } catch (err) {
                _toast(err.message, 'error');
            }
        });

        // Next Run — Set button (stores schedule anchor; auto-advances by interval after each sync)
        container.querySelector('#sd-next-run-set')?.addEventListener('click', async () => {
            const btn = container.querySelector('#sd-next-run-set');
            const input = container.querySelector('#sd-next-run');
            const resultEl = container.querySelector('#sd-next-run-result');
            const rawVal = input?.value || '';
            // Convert datetime-local (YYYY-MM-DDTHH:MM, local time) to ISO UTC string, or null to clear
            const isoVal = rawVal ? new Date(rawVal).toISOString() : null;
            btn.disabled = true;
            btn.innerHTML = `<span class="jobs-spinner"></span>`;
            try {
                await _api('PATCH', `/knowledge/repositories/${collId}`, { next_sync_at: isoVal });
                btn.disabled = false;
                btn.innerHTML = ICONS.check + ' Set';
                if (resultEl) resultEl.innerHTML = `<div class="jobs-result-line">${ICONS.check} Next run ${isoVal ? 'set to ' + new Date(isoVal).toLocaleString() : 'cleared'}</div>`;
                setTimeout(() => { if (resultEl) resultEl.innerHTML = ''; }, 3500);
                _loadAndRenderSync();
            } catch (err) {
                btn.disabled = false;
                btn.innerHTML = ICONS.check + ' Set';
                if (resultEl) resultEl.innerHTML = `<div class="jobs-result-line error">${ICONS.x} ${_esc(err.message)}</div>`;
            }
        });

        // Source Root — Set button
        container.querySelector('#sd-source-root-set')?.addEventListener('click', async () => {
            const btn = container.querySelector('#sd-source-root-set');
            const input = container.querySelector('#sd-source-root');
            const resultEl = container.querySelector('#sd-source-root-result');
            const val = input?.value.trim() || null;
            btn.disabled = true;
            btn.innerHTML = `<span class="jobs-spinner"></span>`;
            try {
                await _api('PATCH', `/knowledge/repositories/${collId}`, { source_root: val });
                btn.disabled = false;
                btn.innerHTML = ICONS.check + ' Set';
                if (resultEl) resultEl.innerHTML = `<div class="jobs-result-line">${ICONS.check} Source root ${val ? 'set to: ' + _esc(val) : 'cleared (auto-detect)'}</div>`;
                setTimeout(() => { if (resultEl) resultEl.innerHTML = ''; }, 3500);
            } catch (err) {
                btn.disabled = false;
                btn.innerHTML = ICONS.check + ' Set';
                if (resultEl) resultEl.innerHTML = `<div class="jobs-result-line error">${ICONS.x} ${_esc(err.message)}</div>`;
            }
        });

        // Sync Now
        container.querySelector('#sd-syncnow')?.addEventListener('click', async () => {
            const btn = container.querySelector('#sd-syncnow');
            const result = container.querySelector('#sd-sync-result');
            btn.disabled = true;
            btn.innerHTML = `<span class="jobs-spinner"></span> Syncing…`;
            if (result) result.innerHTML = '';
            try {
                const res = await _api('POST', `/knowledge/repositories/${collId}/sync`);
                const updatedFiles = res.updated_files || [];
                let resultHtml = `<div class="jobs-result-line">${ICONS.check} ${res.checked || 0} checked · ${res.updated || 0} updated · ${res.unchanged || 0} unchanged · ${res.duration_seconds || 0}s</div>`;
                if (updatedFiles.length > 0) {
                    resultHtml += `<div class="jobs-result-files">${updatedFiles.map(f => `<span class="jobs-result-file">${_esc(f)}</span>`).join('')}</div>`;
                }
                // Reload list + panel (re-renders #sd-sync-result), then restore result
                await _loadAndRenderSync();
                const freshResult = document.getElementById('sync-detail')?.querySelector('#sd-sync-result');
                if (freshResult) freshResult.innerHTML = resultHtml;
                // Reload doc list in the freshly-rendered panel
                const freshDetail = document.getElementById('sync-detail');
                if (freshDetail) _loadSyncDocs(collId, freshDetail);
            } catch (err) {
                btn.innerHTML = ICONS.sync + ' Sync Now';
                btn.disabled = false;
                if (result) result.innerHTML = `<div class="jobs-result-line error">${ICONS.x} ${err.message}</div>`;
            }
        });

        // Re-index
        container.querySelector('#sd-reindex')?.addEventListener('click', async () => {
            const btn = container.querySelector('#sd-reindex');
            const result = container.querySelector('#sd-sync-result');
            btn.disabled = true;
            btn.innerHTML = `<span class="jobs-spinner"></span> Re-indexing…`;
            if (result) result.innerHTML = `<div class="jobs-result-line" style="color:#f59e0b">Re-embedding all documents — this may take a moment…</div>`;
            try {
                const res = await _api('POST', `/knowledge/repositories/${collId}/reindex`);
                btn.innerHTML = ICONS.reindex + ' Re-index';
                btn.disabled = false;
                const reindexHtml = `<div class="jobs-result-line">${ICONS.check} ${res.reindexed || 0} re-indexed · ${res.errors || 0} errors · ${res.duration_seconds || 0}s</div>`;
                await _loadAndRenderSync();
                const freshResult2 = document.getElementById('sync-detail')?.querySelector('#sd-sync-result');
                if (freshResult2) freshResult2.innerHTML = reindexHtml;
            } catch (err) {
                btn.innerHTML = ICONS.reindex + ' Re-index';
                btn.disabled = false;
                if (result) result.innerHTML = `<div class="jobs-result-line error">${ICONS.x} ${err.message}</div>`;
            }
        });

        // Load documents
        _loadSyncDocs(collId, container);
    }

    async function _loadSyncDocs(collId, container) {
        const docsDiv = container.querySelector('#sd-docs-container');
        if (!docsDiv) return;
        try {
            const data = await _api('GET', `/knowledge/repositories/${collId}/documents`);
            const docs = data.documents || [];
            if (!docs.length) {
                docsDiv.innerHTML = `<div style="font-size:12px;color:var(--text-muted)">No documents found.</div>`;
                return;
            }
            docsDiv.innerHTML = `<div style="overflow-x:auto">
                <table class="jobs-doc-table">
                    <thead><tr>
                        <th>Filename</th>
                        <th>Source URI</th>
                        <th>Sync</th>
                        <th>Last Checked</th>
                        <th>Status</th>
                    </tr></thead>
                    <tbody id="sd-doc-tbody">
                        ${docs.map(d => _docRowHTML(d, collId)).join('')}
                    </tbody>
                </table>
            </div>`;
            docsDiv.querySelectorAll('tr[data-doc-id]').forEach(row => _wireDocRow(row, collId));
        } catch (e) {
            docsDiv.innerHTML = `<div style="font-size:12px;color:#ef4444">Failed to load documents: ${e.message}</div>`;
        }
    }

    function _docRowHTML(doc, collId) {
        const docId = doc.document_id;
        const syncEnabled = doc.sync_enabled || 0;
        const sourceUri = doc.source_uri || '';
        const lastChecked = doc.last_checked_at ? _relTime(doc.last_checked_at) : '—';
        const isStale = syncEnabled && !doc.last_checked_at;
        const statusChip = !syncEnabled
            ? `<span style="font-size:11px;color:var(--text-muted)">off</span>`
            : isStale
            ? `<span class="job-badge" style="background:rgba(245,158,11,.1);border-color:rgba(245,158,11,.25);color:#f59e0b">stale</span>`
            : `<span class="job-badge" style="background:rgba(34,197,94,.1);border-color:rgba(34,197,94,.25);color:#22c55e">ok</span>`;

        const uriDisplay = sourceUri
            ? `<span class="jobs-uri-edit" data-editing="false">
                <span class="jobs-uri-display" title="${_esc(sourceUri)}" style="font-size:11px;color:var(--text-muted);max-width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block">${_esc(sourceUri.replace(/^file:\/\//, ''))}</span>
                <button class="jobs-icon-btn jobs-uri-edit-btn" title="Edit source URI">${ICONS.pencil}</button>
               </span>`
            : `<span class="jobs-no-source" data-editing="false">No source <button class="jobs-icon-btn jobs-uri-edit-btn" style="width:18px;height:18px" title="Set source URI">${ICONS.pencil}</button></span>`;

        return `<tr data-doc-id="${_esc(docId)}" data-coll-id="${collId}">
            <td style="color:var(--text-primary);font-size:12px;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${_esc(doc.filename)}">${_esc(doc.filename)}</td>
            <td class="jobs-uri-cell">${uriDisplay}</td>
            <td>
                <label class="job-toggle" style="width:28px;height:15px">
                    <input type="checkbox" ${syncEnabled ? 'checked' : ''} data-doc-id="${_esc(docId)}">
                    <span class="job-toggle-track"></span>
                    <span class="job-toggle-thumb" style="width:11px;height:11px;top:2px;left:2px"></span>
                </label>
            </td>
            <td style="font-size:11px;color:var(--text-muted);white-space:nowrap">${lastChecked}</td>
            <td>${statusChip}</td>
        </tr>`;
    }

    function _wireDocRow(row, collId) {
        const docId = row.dataset.docId;

        // Sync enable/disable toggle
        row.querySelector('input[type="checkbox"]')?.addEventListener('change', async e => {
            const enabled = e.target.checked;
            try {
                await _api('PATCH', `/knowledge/repositories/${collId}/documents/${docId}`, { sync_enabled: enabled });
            } catch (err) {
                e.target.checked = !enabled;
                _toast(err.message, 'error');
            }
        });

        // Inline URI edit
        row.querySelector('.jobs-uri-edit-btn')?.addEventListener('click', e => {
            e.stopPropagation();
            const cell = row.querySelector('td:nth-child(2)');
            const uriSpan = row.querySelector('.jobs-uri-display');
            const currentUri = uriSpan ? (uriSpan.title) : '';

            cell.innerHTML = `<div style="display:flex;align-items:center;gap:4px">
                <input class="jobs-uri-input" id="uri-input-${_esc(docId)}" value="${_esc(currentUri)}" placeholder="file:///path/to/file.md">
                <button class="jobs-icon-btn" id="uri-confirm-${_esc(docId)}" style="color:#22c55e">${ICONS.check}</button>
                <button class="jobs-icon-btn" id="uri-cancel-${_esc(docId)}" style="color:#ef4444">${ICONS.x}</button>
            </div>`;

            const input = cell.querySelector(`#uri-input-${CSS.escape(docId)}`);
            input?.focus();

            cell.querySelector(`#uri-confirm-${CSS.escape(docId)}`)?.addEventListener('click', async () => {
                const newUri = input?.value.trim() || null;
                try {
                    await _api('PATCH', `/knowledge/repositories/${collId}/documents/${docId}`, {
                        source_uri: newUri,
                        sync_enabled: newUri ? true : false,
                    });
                    _toast('Source URI updated');
                    // Reload docs
                    const container = document.getElementById('sync-detail');
                    if (container) _loadSyncDocs(collId, container);
                } catch (err) {
                    _toast(err.message, 'error');
                    const container = document.getElementById('sync-detail');
                    if (container) _loadSyncDocs(collId, container);
                }
            });

            cell.querySelector(`#uri-cancel-${CSS.escape(docId)}`)?.addEventListener('click', () => {
                const container = document.getElementById('sync-detail');
                if (container) _loadSyncDocs(collId, container);
            });
        });
    }

    // ── Utility ────────────────────────────────────────────────────────────────

    function _esc(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#x27;');
    }

    // ── Deep-link entry point ──────────────────────────────────────────────────

    /**
     * Navigate the Platform Jobs sub-tab to a specific collection.
     * Called externally (e.g. from a knowledge repository card "Manage" button)
     * after the scheduler component detail has been opened.
     */
    function openToCollection(collectionId) {
        // Switch to Platform Jobs sub-tab
        if (_root) {
            _root.querySelectorAll('.jobs-sub-tab').forEach(b => b.classList.remove('active'));
            const syncBtn = _root.querySelector('[data-subtab="sync"]');
            if (syncBtn) syncBtn.classList.add('active');
            _activeSubTab = 'sync';
            _root.querySelectorAll('[id^="jobs-panel-"]').forEach(p => p.classList.add('hidden'));
            document.getElementById('jobs-panel-sync')?.classList.remove('hidden');
        }

        // If collections already loaded, select the matching one immediately
        if (_collections.length > 0) {
            const coll = _collections.find(c => String(c.id) === String(collectionId));
            if (coll) _openSyncPanel(coll);
        } else {
            // _loadAndRenderSync hasn't completed yet; store for pick-up
            _pendingCollectionId = collectionId;
        }
    }

    // ── Export ─────────────────────────────────────────────────────────────────

    window.jobsHandler = { initJobsTab, openToCollection };

})();
