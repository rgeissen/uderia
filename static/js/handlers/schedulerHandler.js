/**
 * schedulerHandler.js
 *
 * World-class task scheduler UI for the Platform Components → Scheduler card.
 * Follows Uderia's glass-panel design language with purple accent (service type).
 *
 * Entry points:
 *   schedulerHandler.loadTasksPanel(profileId?)  — renders the Tasks tab content
 *   window.schedulerHandler                       — public API
 */

(function () {
    'use strict';

    // ── Constants & helpers ───────────────────────────────────────────────────

    const ACCENT = {
        bg:      'rgba(168,85,247,0.12)',
        border:  'rgba(168,85,247,0.30)',
        text:    '#c084fc',
        btnHover:'rgba(168,85,247,0.20)',
    };

    const STATUS = {
        success: { dot: 'bg-emerald-400', text: 'text-emerald-400', label: 'Success', ring: 'ring-emerald-400/20' },
        error:   { dot: 'bg-red-400',     text: 'text-red-400',     label: 'Error',   ring: 'ring-red-400/20' },
        skipped: { dot: 'bg-amber-400',   text: 'text-amber-400',   label: 'Skipped', ring: 'ring-amber-400/20' },
        running: { dot: 'bg-blue-400 animate-pulse', text: 'text-blue-400', label: 'Running', ring: 'ring-blue-400/20' },
        timeout: { dot: 'bg-orange-400',  text: 'text-orange-400',  label: 'Timeout', ring: 'ring-orange-400/20' },
    };

    const CRON_PRESETS = [
        { label: 'Every hour',           value: '0 * * * *',     desc: 'Runs at the start of every hour' },
        { label: 'Daily at 9 AM',        value: '0 9 * * *',     desc: 'Every day at 09:00' },
        { label: 'Weekdays at 9 AM',     value: '0 9 * * 1-5',   desc: 'Monday–Friday at 09:00' },
        { label: 'Weekly (Mon 9 AM)',     value: '0 9 * * 1',     desc: 'Every Monday at 09:00' },
        { label: 'Daily at midnight',    value: '0 0 * * *',     desc: 'Every day at 00:00' },
        { label: 'Every 30 minutes',     value: 'interval:1800s', desc: 'Every 30 minutes' },
        { label: 'Every 15 minutes',     value: 'interval:900s',  desc: 'Every 15 minutes' },
        { label: 'Custom',               value: '',               desc: 'Enter a cron expression or interval' },
    ];

    function _authHeaders(json = true) {
        const h = {};
        if (json) h['Content-Type'] = 'application/json';
        const tok = localStorage.getItem('tda_auth_token');
        if (tok) h['Authorization'] = `Bearer ${tok}`;
        return h;
    }

    function _notify(type, msg) {
        if (window.showNotification) window.showNotification(type, msg);
        else console.log(`[Scheduler] ${type}: ${msg}`);
    }

    function _confirm(msg, cb) {
        if (window.showConfirmation) window.showConfirmation(msg, cb);
        else if (confirm(msg)) cb();
    }

    function _esc(str) {
        const d = document.createElement('div');
        d.textContent = String(str || '');
        return d.innerHTML;
    }

    function _relTime(iso) {
        if (!iso) return '—';
        const diff = Date.now() - new Date(iso).getTime();
        const abs = Math.abs(diff);
        if (abs < 60000) return 'just now';
        if (abs < 3600000) return `${Math.round(abs / 60000)}m ago`;
        if (abs < 86400000) return `${Math.round(abs / 3600000)}h ago`;
        return `${Math.round(abs / 86400000)}d ago`;
    }

    function _friendlySchedule(s) {
        if (!s) return '—';
        const found = CRON_PRESETS.find(p => p.value === s && p.value);
        if (found && found.label !== 'Custom') return found.label;
        if (s.startsWith('interval:')) {
            const raw = s.slice(9).toLowerCase();
            if (raw.endsWith('h')) return `Every ${raw.slice(0,-1)} hour${raw.slice(0,-1)==='1'?'':'s'}`;
            if (raw.endsWith('m')) return `Every ${raw.slice(0,-1)} min`;
            const sec = parseInt(raw);
            if (sec < 60) return `Every ${sec}s`;
            if (sec < 3600) return `Every ${Math.round(sec/60)}m`;
            return `Every ${Math.round(sec/3600)}h`;
        }
        return s;
    }

    // ── State ─────────────────────────────────────────────────────────────────

    let _profiles = [];
    let _tasks = [];
    let _activeProfileId = null;
    let _editingTaskId = null;   // null = new task
    let _showingRunHistoryId = null;

    // ── Public API ────────────────────────────────────────────────────────────

    async function loadTasksPanel(profileId) {
        const container = document.getElementById('scheduler-tasks-panel');
        if (!container) return;

        container.innerHTML = _spinner();

        try {
            // Load profiles
            const pr = await fetch('/api/v1/profiles', { headers: _authHeaders(false) });
            const pd = await pr.json();
            _profiles = (pd.profiles || []).filter(p => {
                const cfg = (p.componentConfig || {}).scheduler || {};
                return cfg.enabled;
            });
        } catch (e) {
            _profiles = [];
        }

        if (_profiles.length === 0) {
            container.innerHTML = _emptyNoProfiles();
            return;
        }

        // Select initial profile
        if (profileId && _profiles.find(p => p.id === profileId)) {
            _activeProfileId = profileId;
        } else {
            _activeProfileId = _profiles[0].id;
        }

        await _loadAndRender(container);
    }

    async function _loadAndRender(container) {
        if (!container) container = document.getElementById('scheduler-tasks-panel');
        if (!container) return;

        try {
            const r = await fetch(`/api/v1/scheduled-tasks?profile_id=${_activeProfileId}`, {
                headers: _authHeaders(false)
            });
            const d = await r.json();
            _tasks = d.tasks || [];
        } catch (e) {
            _tasks = [];
        }

        container.innerHTML = _renderFullPanel();
        _wireEvents(container);
    }

    // ── Full panel render ─────────────────────────────────────────────────────

    function _renderFullPanel() {
        return `
            <!-- Profile selector pills -->
            ${_profiles.length > 1 ? _renderProfilePills() : ''}

            <!-- Task list or empty state -->
            <div id="sched-task-list">
                ${_tasks.length === 0 ? _emptyNoTasks() : _renderTaskCards()}
            </div>

            <!-- "New task" FAB-style button -->
            <div class="mt-4">
                <button id="sched-new-task-btn"
                        class="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all"
                        style="background:${ACCENT.bg};border:1px solid ${ACCENT.border};color:${ACCENT.text}"
                        onmouseenter="this.style.background='${ACCENT.btnHover}'"
                        onmouseleave="this.style.background='${ACCENT.bg}'">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
                    </svg>
                    New scheduled task
                </button>
            </div>

            <!-- Task editor (hidden until needed) -->
            <div id="sched-editor-container" class="hidden mt-4"></div>

            <!-- Run history panel (hidden until needed) -->
            <div id="sched-history-container" class="hidden mt-4"></div>
        `;
    }

    function _renderProfilePills() {
        const pills = _profiles.map(p => {
            const active = p.id === _activeProfileId;
            return `<button class="sched-profile-pill filter-pill ${active ? 'filter-pill--active' : ''}"
                            data-profile-id="${p.id}">
                        @${_esc(p.tag || p.id)}
                    </button>`;
        }).join('');
        return `<div class="flex items-center gap-2 mb-5 flex-wrap">
                    <span class="text-xs text-gray-500 uppercase tracking-wide mr-1">Profile</span>
                    ${pills}
                </div>`;
    }

    function _renderTaskCards() {
        return `<div class="space-y-3">
            ${_tasks.map(_renderTaskCard).join('')}
        </div>`;
    }

    function _renderTaskCard(task) {
        const enabled = !!task.enabled;
        const status = task.last_run_status;
        const statusCfg = STATUS[status] || null;
        const scheduleFriendly = _friendlySchedule(task.schedule);

        return `
            <div class="glass-panel rounded-xl overflow-hidden sched-task-card" data-task-id="${task.id}">
                <div class="p-4 flex items-start gap-4">
                    <!-- Status indicator -->
                    <div class="flex-shrink-0 mt-0.5">
                        <div class="w-2 h-2 rounded-full ${enabled ? 'bg-emerald-400' : 'bg-gray-600'} mt-1.5"
                             title="${enabled ? 'Enabled' : 'Disabled'}"></div>
                    </div>

                    <!-- Task info -->
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 flex-wrap">
                            <span class="text-sm font-semibold text-white">${_esc(task.name)}</span>
                            ${statusCfg ? `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ring-1
                                                  bg-${statusCfg.dot.split(' ')[0]}/10 ${statusCfg.text} ring-${statusCfg.ring.replace('ring-','')}">
                                <span class="w-1.5 h-1.5 rounded-full ${statusCfg.dot} inline-block"></span>
                                ${statusCfg.label}
                            </span>` : ''}
                        </div>
                        <div class="mt-1 flex items-center gap-3 flex-wrap text-xs text-gray-400">
                            <!-- Schedule badge -->
                            <span class="inline-flex items-center gap-1">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                </svg>
                                ${_esc(scheduleFriendly)}
                            </span>
                            ${task.output_channel ? `<span class="inline-flex items-center gap-1">
                                <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                    <path stroke-linecap="round" stroke-linejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                                </svg>
                                ${_esc(task.output_channel)}
                            </span>` : ''}
                            ${task.last_run_at ? `<span>Last run ${_relTime(task.last_run_at)}</span>` : ''}
                        </div>
                        <p class="text-xs text-gray-500 mt-1 line-clamp-1">${_esc(task.prompt)}</p>
                    </div>

                    <!-- Actions -->
                    <div class="flex-shrink-0 flex items-center gap-1">
                        <!-- Run now -->
                        <button class="sched-run-now p-1.5 rounded-lg text-gray-400 hover:text-emerald-400 hover:bg-emerald-400/10 transition-all"
                                data-task-id="${task.id}" title="Run now">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
                                <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                        </button>
                        <!-- History -->
                        <button class="sched-history p-1.5 rounded-lg text-gray-400 hover:text-indigo-400 hover:bg-indigo-400/10 transition-all"
                                data-task-id="${task.id}" title="Run history">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                            </svg>
                        </button>
                        <!-- Edit -->
                        <button class="sched-edit p-1.5 rounded-lg text-gray-400 hover:text-purple-400 hover:bg-purple-400/10 transition-all"
                                data-task-id="${task.id}" title="Edit task">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                            </svg>
                        </button>
                        <!-- Enable toggle -->
                        <label class="ind-toggle ind-toggle--sm ml-1">
                            <input type="checkbox" class="sched-enable-toggle" data-task-id="${task.id}" ${enabled ? 'checked' : ''}>
                            <span class="ind-track"></span>
                        </label>
                        <!-- Delete -->
                        <button class="sched-delete p-1.5 rounded-lg text-gray-600 hover:text-red-400 hover:bg-red-400/10 transition-all ml-1"
                                data-task-id="${task.id}" title="Delete task">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                            </svg>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    // ── Task editor ───────────────────────────────────────────────────────────

    function _openEditor(taskId) {
        _editingTaskId = taskId || null;
        const task = taskId ? _tasks.find(t => t.id === taskId) : null;
        const container = document.getElementById('sched-editor-container');
        if (!container) return;

        // Close history if open
        const hist = document.getElementById('sched-history-container');
        if (hist) { hist.classList.add('hidden'); hist.innerHTML = ''; }

        container.classList.remove('hidden');
        container.innerHTML = _renderEditor(task);
        _wireEditorEvents(container, task);

        container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function _renderEditor(task) {
        const isEdit = !!task;
        const v = (f, def = '') => task ? (task[f] ?? def) : def;

        const schedule = v('schedule', '0 9 * * *');
        const activePreset = CRON_PRESETS.find(p => p.value === schedule && p.value) || CRON_PRESETS[CRON_PRESETS.length - 1];
        const isCustom = activePreset.label === 'Custom' || !CRON_PRESETS.find(p => p.value === schedule && p.value);

        const presetChips = CRON_PRESETS.map(p => `
            <button type="button" class="sched-preset-chip px-2.5 py-1 rounded-lg text-xs font-medium border transition-all ${p.value === schedule && p.value !== '' ? 'sched-preset-chip--active' : ''}"
                    style="${p.value === schedule && p.value !== '' ? `background:${ACCENT.bg};border-color:${ACCENT.border};color:${ACCENT.text}` : 'background:rgba(255,255,255,0.04);border-color:rgba(255,255,255,0.08);color:var(--text-muted)'}"
                    data-preset-value="${_esc(p.value)}" data-preset-desc="${_esc(p.desc)}">
                ${_esc(p.label)}
            </button>
        `).join('');

        const outputChannel = v('output_channel', '');
        let outputCfg = {};
        try { outputCfg = JSON.parse(v('output_config', '{}')); } catch (e) { outputCfg = {}; }

        return `
            <div class="glass-panel rounded-xl p-5" style="border-color:${ACCENT.border}">
                <!-- Editor header -->
                <div class="flex items-center justify-between mb-5">
                    <div class="flex items-center gap-3">
                        <div class="w-8 h-8 rounded-lg flex items-center justify-center"
                             style="background:${ACCENT.bg}">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" style="color:${ACCENT.text}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                            </svg>
                        </div>
                        <h3 class="text-sm font-semibold text-white">${isEdit ? 'Edit task' : 'New scheduled task'}</h3>
                    </div>
                    <button id="sched-editor-close"
                            class="p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-all">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>

                <div class="space-y-4">
                    <!-- Name -->
                    <div>
                        <label class="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-1.5">Task name</label>
                        <input id="sched-name" type="text" value="${_esc(v('name'))}"
                               placeholder="e.g. Daily sales summary"
                               class="w-full px-3 py-2 rounded-lg text-sm text-white bg-gray-800/60 border border-gray-700/60
                                      focus:outline-none focus:ring-1 focus:ring-purple-500/50 focus:border-purple-500/50 transition-all"
                               style="background:rgba(255,255,255,0.04)">
                    </div>

                    <!-- Prompt -->
                    <div>
                        <label class="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-1.5">Prompt</label>
                        <textarea id="sched-prompt" rows="3"
                                  placeholder="What should the agent do? e.g. 'Generate a daily summary of open support tickets grouped by priority.'"
                                  class="w-full px-3 py-2 rounded-lg text-sm text-white bg-gray-800/60 border border-gray-700/60
                                         focus:outline-none focus:ring-1 focus:ring-purple-500/50 focus:border-purple-500/50 transition-all resize-none"
                                  style="background:rgba(255,255,255,0.04)">${_esc(v('prompt'))}</textarea>
                    </div>

                    <!-- Schedule -->
                    <div>
                        <label class="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-2">Schedule</label>
                        <div class="flex flex-wrap gap-1.5 mb-3" id="sched-preset-chips">
                            ${presetChips}
                        </div>
                        <div id="sched-custom-row" class="${isCustom ? '' : 'hidden'}">
                            <input id="sched-custom-value" type="text" value="${isCustom ? _esc(schedule) : ''}"
                                   placeholder="Cron: 0 9 * * 1-5  or  Interval: interval:3600s"
                                   class="w-full px-3 py-2 rounded-lg text-sm font-mono text-white bg-gray-800/60 border border-gray-700/60
                                          focus:outline-none focus:ring-1 focus:ring-purple-500/50 focus:border-purple-500/50 transition-all"
                                   style="background:rgba(255,255,255,0.04)">
                            <p id="sched-schedule-preview" class="text-xs text-gray-500 mt-1.5"></p>
                        </div>
                        <p id="sched-preset-desc" class="text-xs text-gray-500 mt-1 ${isCustom ? 'hidden' : ''}">${_esc(activePreset.desc)}</p>
                    </div>

                    <!-- Delivery channel + Advanced — two-column on wider screens -->
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <!-- Output channel -->
                        <div>
                            <label class="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-1.5">Delivery</label>
                            <select id="sched-channel"
                                    class="w-full px-3 py-2 rounded-lg text-sm text-white border border-gray-700/60
                                           focus:outline-none focus:ring-1 focus:ring-purple-500/50 transition-all"
                                    style="background:rgba(255,255,255,0.04)">
                                <option value="" ${!outputChannel ? 'selected' : ''}>None (run silently)</option>
                                <option value="email" ${outputChannel === 'email' ? 'selected' : ''}>Email</option>
                                <option value="webhook" ${outputChannel === 'webhook' ? 'selected' : ''}>Webhook (HTTP POST)</option>
                                <option value="google_mail" ${outputChannel === 'google_mail' ? 'selected' : ''} disabled>Google Mail (Track C)</option>
                            </select>
                        </div>
                        <!-- Overlap policy -->
                        <div>
                            <label class="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-1.5">Overlap policy</label>
                            <select id="sched-overlap"
                                    class="w-full px-3 py-2 rounded-lg text-sm text-white border border-gray-700/60
                                           focus:outline-none focus:ring-1 focus:ring-purple-500/50 transition-all"
                                    style="background:rgba(255,255,255,0.04)">
                                <option value="skip"  ${v('overlap_policy','skip') === 'skip'  ? 'selected' : ''}>Skip — skip if still running</option>
                                <option value="queue" ${v('overlap_policy','skip') === 'queue' ? 'selected' : ''}>Queue — wait for previous</option>
                                <option value="allow" ${v('overlap_policy','skip') === 'allow' ? 'selected' : ''}>Allow — run concurrently</option>
                            </select>
                        </div>
                    </div>

                    <!-- Channel-specific config (dynamic) -->
                    <div id="sched-channel-config" class="${outputChannel ? '' : 'hidden'}">
                        ${_renderChannelConfig(outputChannel, outputCfg)}
                    </div>

                    <!-- Token budget -->
                    <div>
                        <label class="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-1.5">
                            Token budget <span class="normal-case font-normal text-gray-600">(optional — leave blank for no limit)</span>
                        </label>
                        <input id="sched-max-tokens" type="number" min="100" step="100"
                               value="${v('max_tokens_per_run', '')}"
                               placeholder="e.g. 5000"
                               class="w-full px-3 py-2 rounded-lg text-sm text-white bg-gray-800/60 border border-gray-700/60
                                      focus:outline-none focus:ring-1 focus:ring-purple-500/50 transition-all"
                               style="background:rgba(255,255,255,0.04)">
                    </div>
                </div>

                <!-- Footer actions -->
                <div class="flex items-center justify-between mt-5 pt-4 border-t border-white/5">
                    <button id="sched-editor-cancel"
                            class="px-4 py-2 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-white/5 transition-all border border-white/5">
                        Cancel
                    </button>
                    <button id="sched-editor-save"
                            class="px-5 py-2 rounded-lg text-sm font-medium text-white transition-all"
                            style="background:${ACCENT.bg};border:1px solid ${ACCENT.border};color:${ACCENT.text}">
                        ${isEdit ? 'Save changes' : 'Create task'}
                    </button>
                </div>
            </div>
        `;
    }

    function _renderChannelConfig(channel, cfg) {
        if (!channel) return '';
        if (channel === 'email') return `
            <div>
                <label class="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-1.5">Send results to</label>
                <input id="sched-email-to" type="email" value="${_esc(cfg.to_address || '')}"
                       placeholder="recipient@example.com"
                       class="w-full px-3 py-2 rounded-lg text-sm text-white border border-gray-700/60
                              focus:outline-none focus:ring-1 focus:ring-purple-500/50 transition-all"
                       style="background:rgba(255,255,255,0.04)">
            </div>`;
        if (channel === 'webhook') return `
            <div class="space-y-3">
                <div>
                    <label class="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-1.5">Webhook URL</label>
                    <input id="sched-webhook-url" type="url" value="${_esc(cfg.webhook_url || '')}"
                           placeholder="https://your-endpoint.example.com/hook"
                           class="w-full px-3 py-2 rounded-lg text-sm font-mono text-white border border-gray-700/60
                                  focus:outline-none focus:ring-1 focus:ring-purple-500/50 transition-all"
                           style="background:rgba(255,255,255,0.04)">
                </div>
                <div>
                    <label class="text-xs font-medium text-gray-400 uppercase tracking-wider block mb-1.5">
                        Bearer token <span class="normal-case font-normal text-gray-600">(optional)</span>
                    </label>
                    <input id="sched-webhook-token" type="password" value="${_esc(cfg.bearer_token || '')}"
                           placeholder="••••••••"
                           class="w-full px-3 py-2 rounded-lg text-sm font-mono text-white border border-gray-700/60
                                  focus:outline-none focus:ring-1 focus:ring-purple-500/50 transition-all"
                           style="background:rgba(255,255,255,0.04)">
                </div>
            </div>`;
        return '';
    }

    // ── Run history panel ─────────────────────────────────────────────────────

    async function _openHistory(taskId) {
        _showingRunHistoryId = taskId;
        const container = document.getElementById('sched-history-container');
        if (!container) return;

        // Close editor if open
        const ed = document.getElementById('sched-editor-container');
        if (ed) { ed.classList.add('hidden'); ed.innerHTML = ''; }

        container.classList.remove('hidden');
        container.innerHTML = `<div class="glass-panel rounded-xl p-5" style="border-color:rgba(99,102,241,0.25)">
            <div class="flex items-center gap-2 mb-4">
                <h3 class="text-sm font-semibold text-white">Run history</h3>
                <button id="sched-history-close" class="ml-auto p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-all">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            ${_spinner('Loading run history…')}
        </div>`;

        container.querySelector('#sched-history-close').addEventListener('click', () => {
            container.classList.add('hidden');
            container.innerHTML = '';
            _showingRunHistoryId = null;
        });

        container.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

        try {
            const r = await fetch(`/api/v1/scheduled-tasks/${taskId}/runs?limit=20`, {
                headers: _authHeaders(false)
            });
            const d = await r.json();
            const runs = d.runs || [];
            const task = _tasks.find(t => t.id === taskId);

            const runsHTML = runs.length === 0
                ? `<p class="text-sm text-gray-500 py-4 text-center">No runs yet</p>`
                : `<div class="space-y-2 mt-1">
                    ${runs.map(run => {
                        const s = STATUS[run.status] || { dot: 'bg-gray-400', text: 'text-gray-400', label: run.status };
                        const dur = (run.started_at && run.completed_at)
                            ? Math.round((new Date(run.completed_at) - new Date(run.started_at)) / 1000) + 's'
                            : null;
                        return `
                            <div class="flex items-start gap-3 p-3 rounded-lg bg-white/3 border border-white/5">
                                <span class="w-2 h-2 rounded-full ${s.dot} flex-shrink-0 mt-1.5"></span>
                                <div class="flex-1 min-w-0">
                                    <div class="flex items-center gap-2 flex-wrap">
                                        <span class="text-xs font-medium ${s.text}">${s.label}</span>
                                        ${run.tokens_used ? `<span class="text-[11px] text-gray-500">${run.tokens_used.toLocaleString()} tokens</span>` : ''}
                                        ${dur ? `<span class="text-[11px] text-gray-500">${dur}</span>` : ''}
                                        <span class="text-[11px] text-gray-600 ml-auto">${_relTime(run.started_at)}</span>
                                    </div>
                                    ${run.result_summary ? `<p class="text-xs text-gray-400 mt-1 line-clamp-2">${_esc(run.result_summary)}</p>` : ''}
                                    ${run.skip_reason ? `<p class="text-xs text-amber-500/70 mt-1">${_esc(run.skip_reason)}</p>` : ''}
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>`;

            const panel = container.querySelector('.glass-panel');
            panel.innerHTML = `
                <div class="flex items-center gap-3 mb-4">
                    <div class="w-7 h-7 rounded-lg bg-indigo-500/10 flex items-center justify-center flex-shrink-0">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                        </svg>
                    </div>
                    <div>
                        <h3 class="text-sm font-semibold text-white">${_esc(task ? task.name : 'Run history')}</h3>
                        <p class="text-xs text-gray-500">${runs.length} recent run${runs.length !== 1 ? 's' : ''}</p>
                    </div>
                    <button class="sched-history-close ml-auto p-1.5 rounded-lg text-gray-500 hover:text-gray-300 hover:bg-white/5 transition-all">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </button>
                </div>
                ${runsHTML}
            `;

            panel.querySelector('.sched-history-close').addEventListener('click', () => {
                container.classList.add('hidden');
                container.innerHTML = '';
                _showingRunHistoryId = null;
            });

        } catch (e) {
            console.error('[Scheduler] Error loading run history:', e);
        }
    }

    // ── Event wiring ──────────────────────────────────────────────────────────

    function _wireEvents(container) {
        // Profile pill switching
        container.querySelectorAll('.sched-profile-pill').forEach(btn => {
            btn.addEventListener('click', async () => {
                _activeProfileId = btn.dataset.profileId;
                // Close any open editor/history
                const ed = container.querySelector('#sched-editor-container');
                if (ed) { ed.classList.add('hidden'); ed.innerHTML = ''; }
                const hist = container.querySelector('#sched-history-container');
                if (hist) { hist.classList.add('hidden'); hist.innerHTML = ''; }
                await _loadAndRender();
            });
        });

        // New task button
        const newBtn = container.querySelector('#sched-new-task-btn');
        if (newBtn) newBtn.addEventListener('click', () => _openEditor(null));

        // Task card actions (delegated)
        container.querySelector('#sched-task-list')?.addEventListener('click', async (e) => {
            const runBtn  = e.target.closest('.sched-run-now');
            const histBtn = e.target.closest('.sched-history');
            const editBtn = e.target.closest('.sched-edit');
            const delBtn  = e.target.closest('.sched-delete');

            if (runBtn) {
                const taskId = runBtn.dataset.taskId;
                runBtn.disabled = true;
                runBtn.innerHTML = `<svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>`;
                try {
                    await fetch(`/api/v1/scheduled-tasks/${taskId}/run-now`, {
                        method: 'POST', headers: _authHeaders(false)
                    });
                    _notify('success', 'Task triggered — it will appear in run history shortly.');
                } catch (err) {
                    _notify('error', 'Failed to trigger task.');
                }
                runBtn.disabled = false;
                runBtn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`;
            }

            if (histBtn) _openHistory(histBtn.dataset.taskId);
            if (editBtn) _openEditor(editBtn.dataset.taskId);

            if (delBtn) {
                const taskId = delBtn.dataset.taskId;
                const task = _tasks.find(t => t.id === taskId);
                _confirm(`Delete "${task?.name || taskId}"? This cannot be undone.`, async () => {
                    await fetch(`/api/v1/scheduled-tasks/${taskId}`, {
                        method: 'DELETE', headers: _authHeaders(false)
                    });
                    _notify('success', 'Task deleted.');
                    await _loadAndRender();
                });
            }
        });

        // Enable toggles
        container.querySelectorAll('.sched-enable-toggle').forEach(toggle => {
            toggle.addEventListener('change', async (e) => {
                const taskId = e.target.dataset.taskId;
                const enabled = e.target.checked ? 1 : 0;
                await fetch(`/api/v1/scheduled-tasks/${taskId}`, {
                    method: 'PUT',
                    headers: _authHeaders(),
                    body: JSON.stringify({ enabled })
                });
                // Update local state
                const task = _tasks.find(t => t.id === taskId);
                if (task) task.enabled = enabled;
            });
        });
    }

    function _wireEditorEvents(container, task) {
        // Close / cancel
        const closeEditor = () => {
            container.classList.add('hidden');
            container.innerHTML = '';
            _editingTaskId = null;
        };
        container.querySelector('#sched-editor-close')?.addEventListener('click', closeEditor);
        container.querySelector('#sched-editor-cancel')?.addEventListener('click', closeEditor);

        // Preset chips
        container.querySelectorAll('.sched-preset-chip').forEach(chip => {
            chip.addEventListener('click', () => {
                container.querySelectorAll('.sched-preset-chip').forEach(c => {
                    c.classList.remove('sched-preset-chip--active');
                    c.style.background = 'rgba(255,255,255,0.04)';
                    c.style.borderColor = 'rgba(255,255,255,0.08)';
                    c.style.color = 'var(--text-muted)';
                });
                chip.classList.add('sched-preset-chip--active');
                chip.style.background = ACCENT.bg;
                chip.style.borderColor = ACCENT.border;
                chip.style.color = ACCENT.text;

                const val = chip.dataset.presetValue;
                const desc = chip.dataset.presetDesc;
                const customRow = container.querySelector('#sched-custom-row');
                const presetDesc = container.querySelector('#sched-preset-desc');

                if (!val) {
                    // Custom
                    customRow?.classList.remove('hidden');
                    presetDesc?.classList.add('hidden');
                } else {
                    customRow?.classList.add('hidden');
                    presetDesc?.classList.remove('hidden');
                    if (presetDesc) presetDesc.textContent = desc;
                    const customInput = container.querySelector('#sched-custom-value');
                    if (customInput) customInput.value = val;
                }
            });
        });

        // Cron preview
        const cronInput = container.querySelector('#sched-custom-value');
        const preview = container.querySelector('#sched-schedule-preview');
        if (cronInput && preview) {
            cronInput.addEventListener('input', () => {
                const v = cronInput.value.trim();
                if (v.startsWith('interval:')) {
                    preview.textContent = _friendlySchedule(v);
                } else if (v.split(' ').length === 5) {
                    preview.textContent = 'Cron: ' + v;
                } else {
                    preview.textContent = v ? 'Enter 5-part cron (min hr dom mon dow) or interval:Ns' : '';
                }
            });
        }

        // Channel config dynamic render
        const channelSelect = container.querySelector('#sched-channel');
        const channelCfgEl = container.querySelector('#sched-channel-config');
        if (channelSelect && channelCfgEl) {
            channelSelect.addEventListener('change', () => {
                const ch = channelSelect.value;
                if (ch) {
                    channelCfgEl.classList.remove('hidden');
                    channelCfgEl.innerHTML = _renderChannelConfig(ch, {});
                } else {
                    channelCfgEl.classList.add('hidden');
                    channelCfgEl.innerHTML = '';
                }
            });
        }

        // Save
        container.querySelector('#sched-editor-save')?.addEventListener('click', async () => {
            await _saveTask(container, task);
        });
    }

    async function _saveTask(container, existingTask) {
        const name  = container.querySelector('#sched-name')?.value?.trim();
        const prompt = container.querySelector('#sched-prompt')?.value?.trim();
        const channel = container.querySelector('#sched-channel')?.value;
        const overlap = container.querySelector('#sched-overlap')?.value || 'skip';
        const maxTok  = parseInt(container.querySelector('#sched-max-tokens')?.value) || null;

        // Resolve schedule: active preset value OR custom input
        let schedule = '';
        const activeChip = container.querySelector('.sched-preset-chip--active');
        if (activeChip) {
            schedule = activeChip.dataset.presetValue || container.querySelector('#sched-custom-value')?.value?.trim() || '';
        }
        if (!schedule) schedule = container.querySelector('#sched-custom-value')?.value?.trim() || '';

        if (!name || !prompt || !schedule) {
            _notify('error', 'Name, prompt, and schedule are required.');
            return;
        }

        // Gather channel config
        let outputConfig = null;
        if (channel === 'email') {
            const to = container.querySelector('#sched-email-to')?.value?.trim();
            if (!to) { _notify('error', 'Email delivery requires a recipient address.'); return; }
            outputConfig = { to_address: to };
        } else if (channel === 'webhook') {
            const url = container.querySelector('#sched-webhook-url')?.value?.trim();
            if (!url) { _notify('error', 'Webhook delivery requires a URL.'); return; }
            const tok = container.querySelector('#sched-webhook-token')?.value?.trim();
            outputConfig = { webhook_url: url, bearer_token: tok || undefined };
        }

        const saveBtn = container.querySelector('#sched-editor-save');
        if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }

        try {
            const body = {
                name, prompt, schedule,
                profile_id: _activeProfileId,
                output_channel: channel || null,
                output_config: outputConfig,
                max_tokens_per_run: maxTok,
                overlap_policy: overlap,
            };

            const url  = existingTask ? `/api/v1/scheduled-tasks/${existingTask.id}` : '/api/v1/scheduled-tasks';
            const meth = existingTask ? 'PUT' : 'POST';
            const r = await fetch(url, { method: meth, headers: _authHeaders(), body: JSON.stringify(body) });
            if (!r.ok) {
                const e = await r.json();
                throw new Error(e.error || 'Save failed');
            }

            _notify('success', existingTask ? 'Task updated.' : 'Task created.');
            container.classList.add('hidden');
            container.innerHTML = '';
            _editingTaskId = null;
            await _loadAndRender();

        } catch (err) {
            _notify('error', `Failed to save: ${err.message}`);
            if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = existingTask ? 'Save changes' : 'Create task'; }
        }
    }

    // ── Empty states ──────────────────────────────────────────────────────────

    function _emptyNoTasks() {
        return `
            <div class="flex flex-col items-center gap-3 py-10 text-center">
                <div class="w-14 h-14 rounded-full flex items-center justify-center ring-1"
                     style="background:${ACCENT.bg};ring-color:${ACCENT.border}">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-7 w-7" style="color:${ACCENT.text}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                </div>
                <div>
                    <p class="text-white font-semibold text-sm">No scheduled tasks yet</p>
                    <p class="text-xs text-gray-400 mt-1 max-w-xs">Create your first task to run queries automatically on a schedule and deliver results via email or webhook.</p>
                </div>
            </div>
        `;
    }

    function _emptyNoProfiles() {
        return `
            <div class="flex flex-col items-center gap-3 py-10 text-center">
                <div class="w-14 h-14 rounded-full flex items-center justify-center ring-1"
                     style="background:${ACCENT.bg};ring-color:${ACCENT.border}">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-7 w-7" style="color:${ACCENT.text}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>
                    </svg>
                </div>
                <div>
                    <p class="text-white font-semibold text-sm">No profiles have the Scheduler enabled</p>
                    <p class="text-xs text-gray-400 mt-1 max-w-xs">Go to the <strong>Profiles</strong> tab and enable the Task Scheduler for at least one profile.</p>
                </div>
            </div>
        `;
    }

    function _spinner(msg = 'Loading…') {
        return `<div class="flex items-center gap-2 py-4 text-gray-400 text-sm">
            <svg class="animate-spin h-4 w-4 text-purple-400" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            ${msg}
        </div>`;
    }

    // ── Export ────────────────────────────────────────────────────────────────

    window.schedulerHandler = {
        loadTasksPanel,
    };

})();
