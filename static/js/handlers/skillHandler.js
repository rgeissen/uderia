/**
 * Skills tab handler — manages the Skills configuration panel.
 *
 * Skills are pre-processing prompt injections (emerald green, ! trigger).
 * This handler renders skill cards, manages activation/deactivation,
 * and provides import/export functionality.
 */

// ── State ────────────────────────────────────────────────────────────────────

let _allSkills = [];
let _allActivations = [];
let _skillSettings = {};
let _searchQuery = '';
let _activeTag = 'all';
let _activeSource = 'all';
let _activeStatus = 'all';
let _sortMode = 'default';

// ── API Helpers ──────────────────────────────────────────────────────────────

function _authHeaders() {
    const token = localStorage.getItem('tda_auth_token');
    return {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
    };
}

function _notify(type, message) {
    if (window.showNotification) {
        window.showNotification(message, type);
    } else {
        console.log(`[Skills] ${type}: ${message}`);
    }
}

async function _fetchSkills() {
    const res = await fetch('/api/v1/skills', { headers: _authHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
}

async function _fetchActivated() {
    const res = await fetch('/api/v1/skills/activated', { headers: _authHeaders() });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return data.skills || [];
}

async function _activateSkill(skillId, activationName = null) {
    const body = {};
    if (activationName) body.activation_name = activationName;
    const res = await fetch(`/api/v1/skills/${skillId}/activate`, {
        method: 'POST',
        headers: _authHeaders(),
        body: JSON.stringify(body),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
    }
    return res.json();
}

async function _deactivateSkill(activationName) {
    const res = await fetch(`/api/v1/skills/activations/${activationName}/deactivate`, {
        method: 'POST',
        headers: _authHeaders(),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function _deleteSkillFromDisk(skillId) {
    const res = await fetch(`/api/v1/skills/${skillId}`, {
        method: 'DELETE',
        headers: _authHeaders(),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
    }
    return res.json();
}

async function _reloadSkillsAPI() {
    const res = await fetch('/api/v1/skills/reload', {
        method: 'POST',
        headers: _authHeaders(),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
}

async function _exportSkill(skillId) {
    const token = localStorage.getItem('tda_auth_token');
    const res = await fetch(`/api/v1/skills/${skillId}/export`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${skillId}.skill`;
    a.click();
    URL.revokeObjectURL(url);
}

async function _importSkillFile(file) {
    const token = localStorage.getItem('tda_auth_token');
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/api/v1/skills/import', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `HTTP ${res.status}`);
    }
    return res.json();
}

// ── Data Refresh ─────────────────────────────────────────────────────────────

async function _refreshSkillData() {
    const [skillsResp, activations] = await Promise.all([
        _fetchSkills(),
        _fetchActivated(),
    ]);
    _allSkills = skillsResp.skills || [];
    _skillSettings = skillsResp._settings || {};
    _allActivations = activations;
    _rebuildTagPills();
    renderSkillGrid();
}

// ── Tag Color Config ────────────────────────────────────────────────────────

const TAG_COLOR = { color: '#94a3b8', bg: 'rgba(148,163,184,0.10)', border: 'rgba(148,163,184,0.18)' };

const INJECTION_TARGET_CONFIG = {
    system_prompt: { color: '#a78bfa', bg: 'rgba(167,139,250,0.12)', border: 'rgba(167,139,250,0.25)', label: 'System Prompt' },
    user_context:  { color: '#60a5fa', bg: 'rgba(96,165,250,0.12)',  border: 'rgba(96,165,250,0.25)',  label: 'User Context' },
};

// ── Card Rendering ───────────────────────────────────────────────────────────

function _createSkillCard(skill, activation) {
    const card = document.createElement('div');
    card.className = 'glass-panel rounded-lg p-4 transition-all duration-200';
    card.style.cssText = activation
        ? 'border: 1px solid rgba(16,185,129,0.3); border-left: 3px solid rgba(16,185,129,0.5);'
        : 'border: 1px solid var(--border-secondary); border-left: 3px solid rgba(148,163,184,0.15);';

    const isBuiltin = skill.is_builtin;
    const activationName = activation?.activation_name || skill.skill_id;
    const tags = skill.tags || [];
    const params = skill.allowed_params || [];

    // Header: badge + name + actions
    const header = document.createElement('div');
    header.className = 'flex items-center justify-between mb-2';

    const left = document.createElement('div');
    left.className = 'flex items-center gap-2 min-w-0';

    const badge = document.createElement('span');
    badge.className = 'text-xs font-mono font-semibold px-1.5 py-0.5 rounded';
    badge.style.cssText = 'background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);';
    badge.textContent = `!${activationName}`;
    left.appendChild(badge);

    const nameEl = document.createElement('span');
    nameEl.className = 'text-sm font-medium truncate';
    nameEl.style.color = 'var(--text-primary)';
    nameEl.textContent = skill.name || skill.skill_id;
    left.appendChild(nameEl);

    // Spacer to push target badge + actions to the right
    const spacer = document.createElement('div');
    spacer.style.flex = '1';
    left.appendChild(spacer);

    // Injection target badge (in header, right-aligned)
    const target = skill.injection_target || 'system_prompt';
    const targetCfg = INJECTION_TARGET_CONFIG[target] || INJECTION_TARGET_CONFIG.system_prompt;
    const targetBadge = document.createElement('span');
    targetBadge.className = 'text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap';
    targetBadge.style.cssText = `background: ${targetCfg.bg}; color: ${targetCfg.color}; border: 1px solid ${targetCfg.border};`;
    targetBadge.textContent = targetCfg.label;
    left.appendChild(targetBadge);

    header.appendChild(left);

    // Action buttons
    const actions = document.createElement('div');
    actions.className = 'flex items-center gap-1';

    // Toggle button
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'px-2 py-1 text-xs rounded transition-colors';
    if (activation) {
        toggleBtn.textContent = 'Active';
        toggleBtn.style.cssText = 'background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.25);';
        toggleBtn.addEventListener('click', async () => {
            try {
                await _deactivateSkill(activationName);
                await _refreshSkillData();
                if (window.loadActivatedSkills) window.loadActivatedSkills();
                _notify('success', `Skill !${activationName} deactivated`);
            } catch (err) {
                _notify('error', `Deactivation failed: ${err.message}`);
            }
        });
    } else {
        toggleBtn.textContent = 'Activate';
        toggleBtn.style.cssText = 'background: var(--hover-bg); color: var(--text-muted); border: 1px solid var(--border-subtle);';
        toggleBtn.addEventListener('click', async () => {
            try {
                await _activateSkill(skill.skill_id);
                await _refreshSkillData();
                if (window.loadActivatedSkills) window.loadActivatedSkills();
                _notify('success', `Skill !${skill.skill_id} activated`);
            } catch (err) {
                _notify('error', `Activation failed: ${err.message}`);
            }
        });
    }
    actions.appendChild(toggleBtn);

    // Edit button
    const editBtn = document.createElement('button');
    editBtn.className = 'p-1 rounded transition-colors';
    editBtn.style.cssText = 'color: var(--text-muted);';
    editBtn.title = 'Edit skill';
    editBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>';
    editBtn.addEventListener('click', async () => {
        try {
            const token = localStorage.getItem('tda_auth_token');
            const resp = await fetch(`/api/v1/skills/${skill.skill_id}/content`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (!resp.ok) throw new Error('Failed to load skill content');
            const data = await resp.json();
            if (window.openSkillEditor) {
                window.openSkillEditor(data);
            }
        } catch (err) {
            _notify('error', `Failed to open editor: ${err.message}`);
        }
    });
    actions.appendChild(editBtn);

    // Export button
    const exportBtn = document.createElement('button');
    exportBtn.className = 'p-1 rounded transition-colors';
    exportBtn.style.cssText = 'color: var(--text-muted);';
    exportBtn.title = 'Export skill';
    exportBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>';
    exportBtn.addEventListener('click', async () => {
        try {
            await _exportSkill(skill.skill_id);
            _notify('success', `Skill exported as ${skill.skill_id}.skill`);
        } catch (err) {
            _notify('error', `Export failed: ${err.message}`);
        }
    });
    actions.appendChild(exportBtn);

    // Publish button (user-created only, marketplace enabled)
    if (!isBuiltin && _skillSettings.user_skills_marketplace_enabled !== false) {
        const publishBtn = document.createElement('button');
        publishBtn.className = 'p-1 rounded transition-colors';
        publishBtn.style.cssText = 'color: var(--text-muted);';
        publishBtn.title = 'Publish to marketplace';
        publishBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>';
        const _pubIcon = publishBtn.innerHTML;
        publishBtn.addEventListener('click', async () => {
            try {
                publishBtn.disabled = true;
                publishBtn.textContent = '...';
                const res = await fetch(`/api/v1/skills/${skill.skill_id}/publish`, {
                    method: 'POST',
                    headers: _authHeaders(),
                    body: JSON.stringify({ visibility: 'public' }),
                });
                const data = await res.json();
                if (res.ok) {
                    _notify('success', data.message || 'Published to marketplace');
                    publishBtn.textContent = 'Published';
                    publishBtn.disabled = true;
                } else {
                    _notify('error', data.error || 'Publish failed');
                    publishBtn.disabled = false;
                    publishBtn.innerHTML = _pubIcon;
                }
            } catch (err) {
                _notify('error', 'Publish failed: ' + err.message);
                publishBtn.disabled = false;
                publishBtn.innerHTML = _pubIcon;
            }
        });
        actions.appendChild(publishBtn);
    }

    // Delete button (user-created only)
    if (!isBuiltin) {
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'p-1 rounded transition-colors';
        deleteBtn.style.cssText = 'color: var(--text-muted);';
        deleteBtn.title = 'Delete skill';
        deleteBtn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>';
        deleteBtn.addEventListener('click', () => {
            window.showConfirmation(
                'Delete Skill',
                `<p>Delete skill <strong>"${skill.name || skill.skill_id}"</strong>?</p><p>This cannot be undone.</p>`,
                async () => {
                    try {
                        await _deleteSkillFromDisk(skill.skill_id);
                        await _refreshSkillData();
                        if (window.loadActivatedSkills) window.loadActivatedSkills();
                        _notify('success', `Skill deleted`);
                    } catch (err) {
                        _notify('error', `Delete failed: ${err.message}`);
                    }
                }
            );
        });
        actions.appendChild(deleteBtn);
    }

    header.appendChild(actions);
    card.appendChild(header);

    // Description
    if (skill.description) {
        const desc = document.createElement('p');
        desc.className = 'text-xs mb-2';
        desc.style.color = 'var(--text-muted)';
        desc.textContent = skill.description;
        card.appendChild(desc);
    }

    // Tags
    if (tags.length > 0) {
        const tagContainer = document.createElement('div');
        tagContainer.className = 'flex flex-wrap gap-1 mb-2';
        tags.forEach(t => {
            const tc = TAG_COLOR;
            const tag = document.createElement('span');
            tag.className = 'text-[10px] px-1.5 py-0.5 rounded';
            tag.style.cssText = `background: ${tc.bg}; color: ${tc.color}; border: 1px solid ${tc.border};`;
            tag.textContent = t;
            tagContainer.appendChild(tag);
        });
        card.appendChild(tagContainer);
    }

    // Params
    if (params.length > 0) {
        const paramRow = document.createElement('div');
        paramRow.className = 'text-[10px] flex items-center gap-1';
        paramRow.style.color = '#6b7280';

        const paramLabel = document.createElement('span');
        paramLabel.textContent = 'Params:';
        paramRow.appendChild(paramLabel);

        params.forEach(p => {
            const paramBadge = document.createElement('span');
            paramBadge.className = 'font-mono font-semibold px-1 py-0.5 rounded';
            paramBadge.style.cssText = 'background: rgba(16,185,129,0.15); color: #34d399; border: 1px solid rgba(16,185,129,0.3);';
            paramBadge.textContent = p;
            paramRow.appendChild(paramBadge);
        });

        card.appendChild(paramRow);
    }

    // Footer: source badge (left) + param count (right)
    const footer = document.createElement('div');
    footer.className = 'flex items-center justify-between mt-2 pt-2';
    footer.style.borderTop = '1px solid rgba(148,163,184,0.08)';

    const sourceBadge = document.createElement('span');
    sourceBadge.className = 'text-[10px] font-medium px-1.5 py-0.5 rounded';
    if (isBuiltin) {
        sourceBadge.style.cssText = 'background: rgba(148,163,184,0.06); color: var(--text-subtle);';
        sourceBadge.textContent = 'Built-in';
    } else {
        sourceBadge.style.cssText = 'background: rgba(16,185,129,0.08); color: #34d399; border: 1px solid rgba(16,185,129,0.15);';
        sourceBadge.textContent = 'User';
    }
    footer.appendChild(sourceBadge);

    if (params.length > 0) {
        const paramCount = document.createElement('span');
        paramCount.className = 'text-[10px] font-medium px-1.5 py-0.5 rounded';
        paramCount.style.cssText = 'background: rgba(16,185,129,0.12); color: #34d399;';
        paramCount.textContent = `${params.length} param${params.length > 1 ? 's' : ''}`;
        footer.appendChild(paramCount);
    }

    card.appendChild(footer);

    return card;
}

function renderSkillGrid() {
    const container = document.getElementById('skills-grid');
    if (!container) return;

    // Build activation lookup
    const activationMap = {};
    for (const act of _allActivations) {
        activationMap[act.skill_id] = act;
    }

    // Apply all filters
    let filtered = _allSkills;

    // 1. Search filter
    if (_searchQuery) {
        const q = _searchQuery.toLowerCase();
        filtered = filtered.filter(s => {
            const searchable = [
                s.skill_id,
                s.name || '',
                s.description || '',
                ...(s.tags || []),
                ...(s.keywords || []),
            ].join(' ').toLowerCase();
            return searchable.includes(q);
        });
    }

    // 2. Tag filter
    if (_activeTag !== 'all') {
        filtered = filtered.filter(s => (s.tags || []).includes(_activeTag));
    }

    // 3. Source filter
    if (_activeSource === 'builtin') {
        filtered = filtered.filter(s => s.is_builtin);
    } else if (_activeSource === 'user') {
        filtered = filtered.filter(s => !s.is_builtin);
    }

    // 4. Status filter
    if (_activeStatus === 'active') {
        filtered = filtered.filter(s => !!activationMap[s.skill_id]);
    } else if (_activeStatus === 'inactive') {
        filtered = filtered.filter(s => !activationMap[s.skill_id]);
    }

    // 5. Sort
    filtered = [...filtered].sort((a, b) => {
        switch (_sortMode) {
            case 'az':
                return (a.name || a.skill_id).localeCompare(b.name || b.skill_id);
            case 'za':
                return (b.name || b.skill_id).localeCompare(a.name || a.skill_id);
            case 'tags':
                return (b.tags || []).length - (a.tags || []).length;
            default: {
                // Active first, then alphabetical
                const aActive = activationMap[a.skill_id] ? 1 : 0;
                const bActive = activationMap[b.skill_id] ? 1 : 0;
                if (bActive !== aActive) return bActive - aActive;
                return (a.name || a.skill_id).localeCompare(b.name || b.skill_id);
            }
        }
    });

    container.innerHTML = '';

    if (_allSkills.length === 0) {
        container.innerHTML = `
            <div class="text-center py-8" style="grid-column: 1 / -1;">
                <p class="text-gray-400 text-sm">No skills available.</p>
                <p class="text-gray-500 text-xs mt-1">Skills are loaded from the skills/ directory.</p>
            </div>
        `;
        return;
    }

    if (filtered.length === 0) {
        const hasFilters = _activeTag !== 'all' || _activeSource !== 'all' || _activeStatus !== 'all' || _searchQuery;
        container.innerHTML = `
            <div class="text-center py-8" style="grid-column: 1 / -1;">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-8 w-8 text-gray-600 mx-auto mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                <p class="text-gray-500 text-sm">No skills match ${hasFilters ? 'your filters' : 'your search'}.</p>
                <button class="text-[11px] mt-2 px-2 py-1 rounded transition-colors" style="color: #34d399; background: rgba(16,185,129,0.08);"
                        onclick="window._skillClearAllFilters?.()">
                    Clear ${hasFilters ? 'filters' : 'search'}
                </button>
            </div>
        `;
        return;
    }

    for (const skill of filtered) {
        const activation = activationMap[skill.skill_id] || null;
        container.appendChild(_createSkillCard(skill, activation));
    }
}

// ── Filter System ───────────────────────────────────────────────────────────

function _updateSkillPillStyles(pill, isActive) {
    if (isActive) {
        pill.classList.add('active');
    } else {
        pill.classList.remove('active');
    }
}

/**
 * Rebuild dynamic tag pills based on loaded skills.
 * Inserts after the static "All" pill in the Tag group.
 */
function _rebuildTagPills() {
    const filtersContainer = document.getElementById('skill-filters');
    if (!filtersContainer) return;

    // Remove existing dynamic tag pills
    filtersContainer.querySelectorAll('.skill-filter-pill[data-filter="tag"][data-dynamic]').forEach(el => el.remove());

    // Collect all unique tags across loaded skills
    const tagSet = new Set();
    for (const skill of _allSkills) {
        for (const t of (skill.tags || [])) {
            tagSet.add(t);
        }
    }

    // Find the "All" tag pill to insert after
    const allTagPill = filtersContainer.querySelector('.skill-filter-pill[data-filter="tag"][data-value="all"]');
    if (!allTagPill) return;

    // Insert sorted tag pills after "All"
    const sortedTags = [...tagSet].sort();
    let insertAfter = allTagPill;
    for (const tag of sortedTags) {
        const pill = document.createElement('button');
        pill.className = 'skill-filter-pill';
        pill.dataset.filter = 'tag';
        pill.dataset.value = tag;
        pill.dataset.dynamic = 'true';
        pill.textContent = tag;
        if (_activeTag === tag) pill.classList.add('active');
        insertAfter.after(pill);
        insertAfter = pill;
    }

    // Re-wire click handlers for all tag pills
    _wireFilterPills();
}

function _wireFilterPills() {
    const filtersContainer = document.getElementById('skill-filters');
    if (!filtersContainer) return;

    // Pill click handler
    filtersContainer.querySelectorAll('.skill-filter-pill[data-filter]').forEach(pill => {
        // Skip sort trigger (handled separately)
        if (pill.id === 'skill-sort-trigger') return;

        pill.onclick = () => {
            const filterGroup = pill.dataset.filter;
            const value = pill.dataset.value;

            // Update state
            if (filterGroup === 'tag') _activeTag = value;
            else if (filterGroup === 'source') _activeSource = value;
            else if (filterGroup === 'status') _activeStatus = value;

            // Update pill styles within group
            filtersContainer.querySelectorAll(`.skill-filter-pill[data-filter="${filterGroup}"]`).forEach(p => {
                _updateSkillPillStyles(p, p.dataset.value === value);
            });

            renderSkillGrid();
        };
    });
}

function setupSkillFilters() {
    const filtersContainer = document.getElementById('skill-filters');
    if (!filtersContainer) return;

    // Wire all static pill clicks
    _wireFilterPills();

    // Sort dropdown
    const sortTrigger = document.getElementById('skill-sort-trigger');
    const sortMenu = document.getElementById('skill-sort-menu');
    if (sortTrigger && sortMenu) {
        sortTrigger.addEventListener('click', (e) => {
            e.stopPropagation();
            sortMenu.classList.toggle('hidden');
        });

        sortMenu.querySelectorAll('.skill-sort-option').forEach(opt => {
            opt.addEventListener('click', (e) => {
                e.stopPropagation();
                _sortMode = opt.dataset.value;

                // Update label
                const label = document.getElementById('skill-sort-label');
                if (label) label.textContent = opt.textContent.trim();

                // Update selected state
                sortMenu.querySelectorAll('.skill-sort-option').forEach(o => o.classList.remove('selected'));
                opt.classList.add('selected');

                // Highlight sort trigger when non-default
                _updateSkillPillStyles(sortTrigger, _sortMode !== 'default');

                sortMenu.classList.add('hidden');
                renderSkillGrid();
            });
        });

        // Close sort menu on outside click
        document.addEventListener('click', () => {
            sortMenu.classList.add('hidden');
        });
    }

    // Clear all filters handler
    window._skillClearAllFilters = () => {
        _activeTag = 'all';
        _activeSource = 'all';
        _activeStatus = 'all';
        _sortMode = 'default';
        _searchQuery = '';

        const searchInput = document.getElementById('skill-search');
        if (searchInput) searchInput.value = '';

        const sortLabel = document.getElementById('skill-sort-label');
        if (sortLabel) sortLabel.textContent = 'Default';

        // Reset all pill styles
        filtersContainer.querySelectorAll('.skill-filter-pill[data-filter]').forEach(p => {
            _updateSkillPillStyles(p, p.dataset.value === 'all');
        });
        if (sortTrigger) _updateSkillPillStyles(sortTrigger, false);
        if (sortMenu) sortMenu.querySelectorAll('.skill-sort-option').forEach(o => o.classList.remove('selected'));

        renderSkillGrid();
    };
}

// ── Import Handler ───────────────────────────────────────────────────────────

function handleImportSkill() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.skill,.zip';

    // iOS fix: remove accept attribute for iPadOS
    if (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) {
        input.removeAttribute('accept');
    }

    input.addEventListener('change', async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        try {
            const result = await _importSkillFile(file);
            _notify('success', result.message || `Skill imported: ${result.skill_id}`);
            await _refreshSkillData();
            if (window.loadActivatedSkills) window.loadActivatedSkills();
        } catch (err) {
            _notify('error', `Import failed: ${err.message}`);
        }
    });

    input.click();
}

// ── Marketplace Modal ────────────────────────────────────────────────────────

let _mktPage = 1;
let _mktSearch = '';
let _mktSort = 'recent';
let _mktTotalPages = 1;

function _escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
}

function _starsHtml(rating) {
    return Array.from({ length: 5 }, (_, i) =>
        `<svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20" style="color: ${i < Math.round(rating) ? '#facc15' : '#4b5563'}">
            <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/>
        </svg>`
    ).join('');
}

function _createMktSkillCard(skill) {
    const card = document.createElement('div');
    card.className = 'glass-panel rounded-xl p-4 flex flex-col gap-3';
    card.style.cssText = 'border: 1px solid rgba(255,255,255,0.1); transition: border-color 0.2s;';
    card.addEventListener('mouseenter', () => card.style.borderColor = 'rgba(16,185,129,0.5)');
    card.addEventListener('mouseleave', () => card.style.borderColor = 'rgba(255,255,255,0.1)');

    const isPublisher = skill.is_publisher || false;
    const rating = skill.average_rating || 0;
    const target = skill.injection_target || 'system_prompt';
    const targetCfg = INJECTION_TARGET_CONFIG[target] || INJECTION_TARGET_CONFIG.system_prompt;
    const tags = (() => { try { return JSON.parse(skill.tags_json || '[]'); } catch { return []; } })();

    card.innerHTML = `
        <!-- Header -->
        <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:8px;">
            <div style="flex:1; min-width:0;">
                <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
                    <h3 style="font-size:1rem; font-weight:600; color:var(--text-primary); margin:0;">${_escHtml(skill.name)}</h3>
                    ${skill.version ? `<span style="font-size:11px; padding:1px 6px; border-radius:9999px; background:rgba(255,255,255,0.1); color:#d1d5db;">v${_escHtml(skill.version)}</span>` : ''}
                    <span style="font-size:11px; padding:1px 6px; border-radius:9999px; background:${targetCfg.bg}; color:${targetCfg.color}; border:1px solid ${targetCfg.border};">${targetCfg.label}</span>
                    ${skill.has_params ? '<span style="font-size:11px; padding:1px 6px; border-radius:9999px; background:rgba(16,185,129,0.1); color:#34d399;">Params</span>' : ''}
                </div>
                ${skill.author ? `<p style="font-size:13px; color:#9ca3af; margin-top:2px;">by ${_escHtml(skill.author)}</p>` : ''}
            </div>
        </div>

        <!-- Description -->
        ${skill.description ? `<p style="font-size:13px; color:#d1d5db; margin:0;">${_escHtml(skill.description)}</p>` : ''}

        <!-- Tags -->
        ${tags.length > 0 ? `
            <div style="display:flex; flex-wrap:wrap; gap:4px;">
                ${tags.map(t => {
                    const tc = TAG_COLOR;
                    return `<span style="font-size:10px; padding:1px 6px; border-radius:4px; background:${tc.bg}; color:${tc.color}; border:1px solid ${tc.border};">${_escHtml(t)}</span>`;
                }).join('')}
                <span style="font-size:10px; padding:1px 6px; border-radius:4px; background:rgba(255,255,255,0.06); color:#9ca3af; font-family:monospace;">#${_escHtml(skill.skill_id)}</span>
            </div>
        ` : ''}

        <!-- Publisher -->
        ${skill.publisher_username ? `
            <div style="display:flex; align-items:center; gap:6px; font-size:13px; color:#9ca3af;">
                <svg style="width:16px; height:16px; flex-shrink:0;" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/>
                </svg>
                <span style="color:#d1d5db;">${_escHtml(skill.publisher_username)}</span>
            </div>
        ` : ''}

        <!-- Stats -->
        <div style="display:flex; align-items:center; flex-wrap:wrap; gap:16px; font-size:13px; color:#d1d5db;">
            <div style="display:flex; align-items:center; gap:3px;">
                ${_starsHtml(rating)}
                <span style="margin-left:4px; color:#9ca3af;">${rating.toFixed(1)} (${skill.rating_count || 0})</span>
            </div>
            <div style="display:flex; align-items:center; gap:5px;">
                <svg style="width:16px; height:16px; color:#9ca3af;" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>
                </svg>
                <span>${skill.install_count || 0} installs</span>
            </div>
        </div>

        <!-- Actions -->
        <div style="display:flex; align-items:center; gap:8px; padding-top:8px; border-top:1px solid rgba(255,255,255,0.05);">
            ${isPublisher ? `
                <button class="skill-mkt-unpublish" style="flex:1; padding:6px 12px; font-size:12px; font-weight:500; border-radius:8px; background:rgba(239,68,68,0.1); color:#f87171; border:1px solid rgba(239,68,68,0.2); cursor:pointer; transition:background 0.2s;">
                    Unpublish
                </button>
            ` : `
                <button class="skill-mkt-install" style="flex:1; padding:6px 12px; font-size:12px; font-weight:500; border-radius:8px; background:rgba(16,185,129,0.1); color:#34d399; border:1px solid rgba(16,185,129,0.2); cursor:pointer; transition:background 0.2s;">
                    Install
                </button>
            `}
            <button class="skill-mkt-rate" style="padding:6px 12px; font-size:12px; font-weight:500; border-radius:8px; background:rgba(250,204,21,0.08); color:#facc15; border:1px solid rgba(250,204,21,0.2); cursor:pointer; transition:background 0.2s;">
                Rate
            </button>
        </div>
    `;

    // Wire install button
    const installBtn = card.querySelector('.skill-mkt-install');
    if (installBtn) {
        installBtn.addEventListener('click', async () => {
            installBtn.disabled = true;
            installBtn.textContent = 'Installing...';
            try {
                const res = await fetch(`/api/v1/marketplace/skills/${skill.id}/install`, {
                    method: 'POST',
                    headers: _authHeaders(),
                });
                const data = await res.json();
                if (res.ok) {
                    _notify('success', data.message || 'Skill installed');
                    installBtn.textContent = 'Installed';
                    installBtn.style.color = '#34d399';
                    installBtn.style.borderColor = 'rgba(16,185,129,0.3)';
                    installBtn.style.background = 'rgba(16,185,129,0.15)';
                    // Refresh local skills list
                    await _refreshSkillData();
                    if (window.loadActivatedSkills) window.loadActivatedSkills();
                } else {
                    _notify('error', data.error || 'Install failed');
                    installBtn.textContent = 'Install';
                    installBtn.disabled = false;
                }
            } catch (err) {
                _notify('error', 'Install failed: ' + err.message);
                installBtn.textContent = 'Install';
                installBtn.disabled = false;
            }
        });
    }

    // Wire unpublish button
    const unpubBtn = card.querySelector('.skill-mkt-unpublish');
    if (unpubBtn) {
        unpubBtn.addEventListener('click', () => {
            window.showConfirmation(
                'Unpublish Skill',
                `<p>Unpublish <strong>"${skill.name}"</strong> from the marketplace?</p>`,
                async () => {
                    unpubBtn.disabled = true;
                    unpubBtn.textContent = 'Removing...';
                    try {
                        const res = await fetch(`/api/v1/marketplace/skills/${skill.id}`, {
                            method: 'DELETE',
                            headers: _authHeaders(),
                        });
                        const data = await res.json();
                        if (res.ok) {
                            _notify('success', data.message || 'Skill unpublished');
                            _loadMktSkills();
                        } else {
                            _notify('error', data.error || 'Unpublish failed');
                            unpubBtn.textContent = 'Unpublish';
                            unpubBtn.disabled = false;
                        }
                    } catch (err) {
                        _notify('error', 'Unpublish failed: ' + err.message);
                        unpubBtn.textContent = 'Unpublish';
                        unpubBtn.disabled = false;
                    }
                }
            );
        });
    }

    // Wire rate button
    const rateBtn = card.querySelector('.skill-mkt-rate');
    if (rateBtn) {
        rateBtn.addEventListener('click', () => _openRateModal(skill));
    }

    return card;
}

async function _loadMktSkills() {
    const grid = document.getElementById('skill-mkt-grid');
    const loading = document.getElementById('skill-mkt-loading');
    const empty = document.getElementById('skill-mkt-empty');
    if (!grid) return;

    grid.innerHTML = '';
    if (loading) loading.classList.remove('hidden');
    if (empty) empty.classList.add('hidden');

    try {
        const params = new URLSearchParams({
            page: _mktPage,
            per_page: 12,
            sort_by: _mktSort,
        });
        if (_mktSearch) params.append('search', _mktSearch);

        const res = await fetch(`/api/v1/marketplace/skills?${params}`, { headers: _authHeaders() });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        const skills = data.skills || [];
        _mktTotalPages = data.total_pages || 1;

        if (loading) loading.classList.add('hidden');

        if (skills.length === 0) {
            if (empty) {
                empty.classList.remove('hidden');
                empty.textContent = _mktSearch ? 'No skills match your search.' : 'No skills published yet.';
            }
        } else {
            for (const s of skills) {
                grid.appendChild(_createMktSkillCard(s));
            }
        }

        // Update pagination
        _updateMktPagination(data);
    } catch (err) {
        if (loading) loading.classList.add('hidden');
        grid.innerHTML = `<p style="color:#f87171; font-size:13px; grid-column:1/-1; text-align:center;">Failed to load marketplace: ${_escHtml(err.message)}</p>`;
    }
}

function _updateMktPagination(data) {
    const pagination = document.getElementById('skill-mkt-pagination');
    const prevBtn = document.getElementById('skill-mkt-prev');
    const nextBtn = document.getElementById('skill-mkt-next');
    const info = document.getElementById('skill-mkt-page-info');
    if (!pagination) return;

    if ((data.total_pages || 1) > 1) {
        pagination.classList.remove('hidden');
        if (prevBtn) prevBtn.disabled = _mktPage <= 1;
        if (nextBtn) nextBtn.disabled = _mktPage >= data.total_pages;
        if (info) info.textContent = `Page ${_mktPage} of ${data.total_pages} (${data.total_count || 0} total)`;
    } else {
        pagination.classList.add('hidden');
    }
}

function _showSkillMarketplace() {
    // Remove existing overlay if any
    const existing = document.getElementById('skill-mkt-overlay');
    if (existing) existing.remove();

    _mktPage = 1;
    _mktSearch = '';
    _mktSort = 'recent';

    const overlay = document.createElement('div');
    overlay.id = 'skill-mkt-overlay';
    overlay.style.cssText = 'position:fixed; inset:0; z-index:9999; background:rgba(0,0,0,0.6); backdrop-filter:blur(4px); display:flex; align-items:center; justify-content:center; opacity:0; transition:opacity 0.2s;';

    const modal = document.createElement('div');
    modal.style.cssText = 'width:90vw; max-width:960px; max-height:85vh; background:var(--card-bg, #1e293b); border:1px solid var(--border-primary, rgba(148,163,184,0.2)); border-radius:16px; display:flex; flex-direction:column; transform:scale(0.95); opacity:0; transition:transform 0.25s cubic-bezier(0.16,1,0.3,1), opacity 0.2s;';

    // Header
    const header = document.createElement('div');
    header.style.cssText = 'padding:20px 24px 16px; border-bottom:1px solid rgba(148,163,184,0.1); display:flex; align-items:center; justify-content:space-between; flex-shrink:0;';
    header.innerHTML = `
        <div style="display:flex; align-items:center; gap:10px;">
            <svg style="width:22px; height:22px; color:#34d399;" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z"/>
            </svg>
            <h2 style="font-size:1.125rem; font-weight:600; color:var(--text-primary); margin:0;">Skill Marketplace</h2>
        </div>
        <button id="skill-mkt-close" style="padding:6px; border-radius:8px; background:transparent; border:none; color:#9ca3af; cursor:pointer; transition:color 0.2s;" title="Close">
            <svg style="width:20px; height:20px;" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
        </button>
    `;

    // Toolbar: search + sort
    const toolbar = document.createElement('div');
    toolbar.style.cssText = 'padding:12px 24px; display:flex; align-items:center; gap:8px; flex-shrink:0;';
    toolbar.innerHTML = `
        <div style="flex:1; display:flex; align-items:center; gap:8px;">
            <input id="skill-mkt-search" type="text" placeholder="Search skills..." style="flex:1; padding:6px 12px; font-size:13px; border-radius:8px; background:rgba(255,255,255,0.05); border:1px solid rgba(148,163,184,0.2); color:var(--text-primary); outline:none; transition:border-color 0.2s;" />
            <button id="skill-mkt-search-btn" style="padding:6px 14px; font-size:12px; font-weight:500; border-radius:8px; background:rgba(16,185,129,0.1); color:#34d399; border:1px solid rgba(16,185,129,0.2); cursor:pointer; transition:background 0.2s;">Search</button>
        </div>
        <select id="skill-mkt-sort" style="padding:6px 10px; font-size:12px; border-radius:8px; background:rgba(255,255,255,0.05); border:1px solid rgba(148,163,184,0.2); color:var(--text-primary); cursor:pointer;">
            <option value="recent">Most Recent</option>
            <option value="rating">Top Rated</option>
            <option value="installs">Most Installs</option>
            <option value="downloads">Most Downloads</option>
            <option value="name">Name A-Z</option>
        </select>
    `;

    // Content
    const content = document.createElement('div');
    content.style.cssText = 'flex:1; overflow-y:auto; padding:16px 24px;';
    content.innerHTML = `
        <div id="skill-mkt-loading" style="text-align:center; padding:40px 0; color:#9ca3af; font-size:13px;">Loading marketplace...</div>
        <div id="skill-mkt-empty" class="hidden" style="text-align:center; padding:40px 0; color:#9ca3af; font-size:13px;"></div>
        <div id="skill-mkt-grid" style="display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); gap:12px;"></div>
    `;

    // Pagination
    const pagination = document.createElement('div');
    pagination.id = 'skill-mkt-pagination';
    pagination.className = 'hidden';
    pagination.style.cssText = 'padding:12px 24px 16px; border-top:1px solid rgba(148,163,184,0.1); display:flex; align-items:center; justify-content:center; gap:12px; flex-shrink:0;';
    pagination.innerHTML = `
        <button id="skill-mkt-prev" style="padding:4px 12px; font-size:12px; border-radius:6px; background:rgba(255,255,255,0.05); border:1px solid rgba(148,163,184,0.2); color:var(--text-primary); cursor:pointer;">Prev</button>
        <span id="skill-mkt-page-info" style="font-size:12px; color:#9ca3af;">Page 1 of 1</span>
        <button id="skill-mkt-next" style="padding:4px 12px; font-size:12px; border-radius:6px; background:rgba(255,255,255,0.05); border:1px solid rgba(148,163,184,0.2); color:var(--text-primary); cursor:pointer;">Next</button>
    `;

    modal.append(header, toolbar, content, pagination);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Animate in
    requestAnimationFrame(() => {
        overlay.style.opacity = '1';
        modal.style.transform = 'scale(1)';
        modal.style.opacity = '1';
    });

    // Close handlers
    const close = () => {
        overlay.style.opacity = '0';
        modal.style.transform = 'scale(0.95)';
        modal.style.opacity = '0';
        setTimeout(() => overlay.remove(), 200);
    };
    overlay.querySelector('#skill-mkt-close').addEventListener('click', close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

    // Search
    const searchInput = overlay.querySelector('#skill-mkt-search');
    const searchBtn = overlay.querySelector('#skill-mkt-search-btn');
    searchBtn.addEventListener('click', () => {
        _mktPage = 1;
        _mktSearch = searchInput.value.trim();
        _loadMktSkills();
    });
    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            _mktPage = 1;
            _mktSearch = searchInput.value.trim();
            _loadMktSkills();
        }
    });

    // Sort
    overlay.querySelector('#skill-mkt-sort').addEventListener('change', (e) => {
        _mktPage = 1;
        _mktSort = e.target.value;
        _loadMktSkills();
    });

    // Pagination
    overlay.querySelector('#skill-mkt-prev').addEventListener('click', () => {
        if (_mktPage > 1) { _mktPage--; _loadMktSkills(); }
    });
    overlay.querySelector('#skill-mkt-next').addEventListener('click', () => {
        if (_mktPage < _mktTotalPages) { _mktPage++; _loadMktSkills(); }
    });

    // Initial load
    _loadMktSkills();
}

// ── Rating Modal ─────────────────────────────────────────────────────────────

function _openRateModal(skill) {
    const existing = document.getElementById('skill-rate-overlay');
    if (existing) existing.remove();

    let selectedRating = 0;

    const overlay = document.createElement('div');
    overlay.id = 'skill-rate-overlay';
    overlay.style.cssText = 'position:fixed; inset:0; z-index:10000; background:rgba(0,0,0,0.6); backdrop-filter:blur(4px); display:flex; align-items:center; justify-content:center; opacity:0; transition:opacity 0.2s;';

    const modal = document.createElement('div');
    modal.style.cssText = 'width:90vw; max-width:420px; background:var(--card-bg, #1e293b); border:1px solid var(--border-primary, rgba(148,163,184,0.2)); border-radius:16px; padding:24px; transform:scale(0.95); opacity:0; transition:transform 0.25s cubic-bezier(0.16,1,0.3,1), opacity 0.2s;';

    modal.innerHTML = `
        <h3 style="font-size:1rem; font-weight:600; color:var(--text-primary); margin:0 0 4px 0;">Rate Skill</h3>
        <p style="font-size:13px; color:#9ca3af; margin:0 0 16px 0;">${_escHtml(skill.name)}</p>

        <div id="skill-rate-stars" style="display:flex; gap:6px; justify-content:center; margin-bottom:16px; cursor:pointer;">
            ${Array.from({ length: 5 }, (_, i) => `
                <svg data-star="${i + 1}" style="width:32px; height:32px; color:#4b5563; transition:color 0.15s; cursor:pointer;" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/>
                </svg>
            `).join('')}
        </div>

        <textarea id="skill-rate-comment" placeholder="Leave a comment (optional)..." rows="3" style="width:100%; padding:8px 12px; font-size:13px; border-radius:8px; background:rgba(255,255,255,0.05); border:1px solid rgba(148,163,184,0.2); color:var(--text-primary); resize:vertical; outline:none; margin-bottom:16px;"></textarea>

        <div style="display:flex; gap:8px; justify-content:flex-end;">
            <button id="skill-rate-cancel" style="padding:6px 16px; font-size:13px; border-radius:8px; background:rgba(255,255,255,0.05); border:1px solid rgba(148,163,184,0.2); color:#9ca3af; cursor:pointer;">Cancel</button>
            <button id="skill-rate-submit" style="padding:6px 16px; font-size:13px; font-weight:500; border-radius:8px; background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.3); color:#34d399; cursor:pointer;">Submit</button>
        </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Animate in
    requestAnimationFrame(() => {
        overlay.style.opacity = '1';
        modal.style.transform = 'scale(1)';
        modal.style.opacity = '1';
    });

    const close = () => {
        overlay.style.opacity = '0';
        modal.style.transform = 'scale(0.95)';
        modal.style.opacity = '0';
        setTimeout(() => overlay.remove(), 200);
    };

    // Star interaction
    const starsContainer = modal.querySelector('#skill-rate-stars');
    const stars = starsContainer.querySelectorAll('svg');
    const updateStars = (rating) => {
        stars.forEach((s, idx) => {
            s.style.color = idx < rating ? '#facc15' : '#4b5563';
        });
    };
    starsContainer.addEventListener('click', (e) => {
        const star = e.target.closest('svg[data-star]');
        if (star) {
            selectedRating = parseInt(star.dataset.star);
            updateStars(selectedRating);
        }
    });
    starsContainer.addEventListener('mouseover', (e) => {
        const star = e.target.closest('svg[data-star]');
        if (star) updateStars(parseInt(star.dataset.star));
    });
    starsContainer.addEventListener('mouseleave', () => {
        updateStars(selectedRating);
    });

    // Close
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    modal.querySelector('#skill-rate-cancel').addEventListener('click', close);

    // Submit
    modal.querySelector('#skill-rate-submit').addEventListener('click', async () => {
        if (selectedRating < 1) {
            _notify('error', 'Please select a rating');
            return;
        }
        const submitBtn = modal.querySelector('#skill-rate-submit');
        submitBtn.disabled = true;
        submitBtn.textContent = 'Submitting...';

        try {
            const body = { rating: selectedRating };
            const comment = modal.querySelector('#skill-rate-comment').value.trim();
            if (comment) body.comment = comment;

            const res = await fetch(`/api/v1/marketplace/skills/${skill.id}/rate`, {
                method: 'POST',
                headers: _authHeaders(),
                body: JSON.stringify(body),
            });
            const data = await res.json();
            if (res.ok) {
                _notify('success', 'Rating submitted');
                close();
                _loadMktSkills();
            } else {
                _notify('error', data.error || 'Rating failed');
                submitBtn.textContent = 'Submit';
                submitBtn.disabled = false;
            }
        } catch (err) {
            _notify('error', 'Rating failed: ' + err.message);
            submitBtn.textContent = 'Submit';
            submitBtn.disabled = false;
        }
    });
}

// ── Public API ───────────────────────────────────────────────────────────────

export async function loadSkills() {
    const container = document.getElementById('skills-grid');
    if (!container) return;

    try {
        await _refreshSkillData();
    } catch (err) {
        console.error('[Skills] Load failed:', err);
        container.innerHTML = `
            <div class="text-center py-8" style="grid-column: 1 / -1;">
                <p class="text-red-400 text-sm">Failed to load skills.</p>
                <p class="text-gray-500 text-xs mt-1">${err.message}</p>
            </div>
        `;
    }
}

export function initializeSkillHandlers() {
    // Filters
    setupSkillFilters();

    // Search
    const searchInput = document.getElementById('skill-search');
    if (searchInput) {
        const handler = (val) => {
            _searchQuery = (val || '').trim();
            renderSkillGrid();
        };
        window._skillSearchHandler = handler;
        searchInput.addEventListener('input', (e) => handler(e.target.value));
    }

    // Create button — opens skill editor dialog
    const createBtn = document.getElementById('create-skill-btn');
    if (createBtn) {
        createBtn.addEventListener('click', () => {
            if (window.openSkillEditor) {
                window.openSkillEditor();
            } else {
                _notify('info', 'Skill editor coming soon');
            }
        });
    }

    // Import button
    const importBtn = document.getElementById('import-skill-btn');
    if (importBtn) {
        importBtn.addEventListener('click', () => handleImportSkill());
    }

    // Edit buttons on cards — wired dynamically in _createSkillCard
    // (uses window.openSkillEditor)

    // Marketplace button
    const mktBtn = document.getElementById('browse-skill-marketplace-btn');
    if (mktBtn) {
        mktBtn.addEventListener('click', () => _showSkillMarketplace());
    }

    // Reload button
    const reloadBtn = document.getElementById('reload-skills-btn');
    if (reloadBtn) {
        reloadBtn.addEventListener('click', async () => {
            try {
                reloadBtn.disabled = true;
                reloadBtn.style.opacity = '0.5';
                await _reloadSkillsAPI();
                await loadSkills();
                if (window.loadActivatedSkills) window.loadActivatedSkills();
                _notify('success', 'Skills reloaded from disk');
            } catch (err) {
                _notify('error', `Reload failed: ${err.message}`);
            } finally {
                reloadBtn.disabled = false;
                reloadBtn.style.opacity = '1';
            }
        });
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// SKILL EDITOR DIALOG — Citizen / Intermediate / Expert progressive disclosure
// ══════════════════════════════════════════════════════════════════════════════

const EMERALD = '#34d399';
const EMERALD_LIGHT = '#34d399';
const EMERALD_BG = 'rgba(52, 211, 153, 0.15)';
const EMERALD_BORDER = 'rgba(52, 211, 153, 0.3)';
const EMERALD_GLOW = '0 0 0 3px rgba(16,185,129,0.12)';
const SPRING_EASE = 'cubic-bezier(0.16, 1, 0.3, 1)';

function _slugify(text) {
    return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function _parseParamBlocks(content) {
    const paramRegex = /<!-- param:(\w+) -->\n?([\s\S]*?)<!-- \/param:\1 -->/g;
    const params = [];
    let match;
    while ((match = paramRegex.exec(content)) !== null) {
        params.push({ name: match[1], content: match[2].trim() });
    }
    const baseContent = content.replace(paramRegex, '').trim();
    return { baseContent, params };
}

function _serializeParamBlocks(baseContent, params) {
    let result = baseContent;
    for (const p of params) {
        if (p.name && p.content) {
            result += `\n\n<!-- param:${p.name} -->\n${p.content}\n<!-- /param:${p.name} -->`;
        }
    }
    return result;
}

function _buildContentFromState(editorState) {
    if (editorState.level === 'expert') return editorState.rawContent;
    return _serializeParamBlocks(editorState.instructions, editorState.params);
}

function _buildManifestFromState(editorState) {
    const manifest = {
        name: editorState.skillId,
        version: '1.0.0',
        description: editorState.description || (editorState.instructions || '').split('\n')[0].replace(/^#\s*/, '').substring(0, 100),
        author: 'User',
        tags: editorState.tags,
        keywords: [],
        main_file: `${editorState.skillId}.md`,
        last_updated: new Date().toISOString().split('T')[0],
    };
    if (editorState.injectionTarget !== 'system_prompt' || editorState.params.length > 0) {
        manifest.uderia = {};
        if (editorState.injectionTarget !== 'system_prompt') {
            manifest.uderia.injection_target = editorState.injectionTarget;
        }
        if (editorState.params.length > 0) {
            manifest.uderia.allowed_params = editorState.params.map(p => p.name);
            manifest.uderia.param_descriptions = {};
            for (const p of editorState.params) {
                if (p.description) manifest.uderia.param_descriptions[p.name] = p.description;
            }
        }
    }
    return manifest;
}

function _estimateTokens(text) {
    return Math.ceil((text || '').length / 4);
}

/** Render simple markdown to HTML for preview. */
function _renderMarkdownPreview(md) {
    let html = md
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/^### (.+)$/gm, '<h3 style="font-size:0.85rem;font-weight:600;color:#fff;margin:12px 0 4px;">$1</h3>')
        .replace(/^## (.+)$/gm, '<h2 style="font-size:0.95rem;font-weight:700;color:#fff;margin:16px 0 6px;">$1</h2>')
        .replace(/^# (.+)$/gm, '<h1 style="font-size:1.1rem;font-weight:700;color:#fff;margin:18px 0 8px;">$1</h1>')
        .replace(/\*\*(.+?)\*\*/g, '<strong style="color:#fff;">$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/`([^`]+)`/g, `<code style="color:${EMERALD_LIGHT};background:rgba(0,0,0,0.3);padding:1px 5px;border-radius:3px;font-size:0.72rem;">$1</code>`)
        .replace(/^- (.+)$/gm, '<li style="margin-left:16px;padding-left:4px;list-style:disc;">$1</li>')
        .replace(/^(\d+)\. (.+)$/gm, '<li style="margin-left:16px;padding-left:4px;list-style:decimal;">$1. $2</li>')
        .replace(/\n{2,}/g, '<br><br>')
        .replace(/\n/g, '<br>');
    // Highlight param blocks
    html = html.replace(/&lt;!-- param:(\w+) --&gt;/g,
        `<div style="margin-top:8px;padding:4px 8px;border-radius:4px;font-size:10px;font-family:monospace;background:${EMERALD_BG};border-left:2px solid ${EMERALD};color:${EMERALD_LIGHT};">param: $1</div>`);
    html = html.replace(/&lt;!-- \/param:(\w+) --&gt;/g,
        `<div style="margin-bottom:8px;padding:4px 8px;border-radius:4px;font-size:10px;font-family:monospace;background:${EMERALD_BG};border-left:2px solid ${EMERALD};color:${EMERALD_LIGHT};">/param: $1</div>`);
    return html;
}

/**
 * Open the Skill Editor Dialog.
 * @param {Object|null} existingSkill - If editing, pass { skill_id, content, manifest, is_builtin }
 */
function openSkillEditor(existingSkill = null) {
    const isNew = !existingSkill;

    const editorState = {
        level: 'citizen',
        skillId: existingSkill?.skill_id || '',
        description: existingSkill?.manifest?.description || '',
        instructions: '',
        rawContent: existingSkill?.content || '',
        rawManifest: existingSkill?.manifest ? JSON.stringify(existingSkill.manifest, null, 2) : '{}',
        injectionTarget: existingSkill?.manifest?.uderia?.injection_target || 'system_prompt',
        tags: existingSkill?.manifest?.tags || [],
        params: [],
        isBuiltin: existingSkill?.is_builtin || false,
    };

    if (existingSkill?.content) {
        const parsed = _parseParamBlocks(existingSkill.content);
        editorState.instructions = parsed.baseContent;
        editorState.params = parsed.params.map(p => ({
            name: p.name,
            content: p.content,
            description: existingSkill?.manifest?.uderia?.param_descriptions?.[p.name] || '',
        }));
    }

    if (existingSkill) {
        if (editorState.params.length > 0 || editorState.injectionTarget !== 'system_prompt') {
            editorState.level = 'intermediate';
        }
    }

    let hasChanges = false;
    let overlay, editorPanel;
    let _tokenUpdateTimer = null;

    // ── Build overlay with animation ──
    overlay = document.createElement('div');
    overlay.className = 'fixed inset-0 z-50 flex items-center justify-center';
    overlay.style.cssText = `background: rgba(0,0,0,0.8); backdrop-filter: blur(6px); opacity: 0; transition: opacity 200ms ease;`;

    editorPanel = document.createElement('div');
    editorPanel.className = 'glass-panel rounded-xl flex flex-col mx-4 my-4';
    editorPanel.style.cssText = `border: 1px solid ${EMERALD_BORDER}; width: calc(100vw - 3rem); height: calc(100vh - 3rem); max-width: 1200px; animation: skillEditorIn 300ms ${SPRING_EASE} forwards;`;

    function _updateTokenEstimate() {
        const content = _buildContentFromState(editorState);
        const tokens = _estimateTokens(content);
        const el = editorPanel.querySelector('#skill-token-estimate');
        if (el) el.textContent = `~${tokens.toLocaleString()} tokens`;
    }

    function _scheduleTokenUpdate() {
        clearTimeout(_tokenUpdateTimer);
        _tokenUpdateTimer = setTimeout(() => {
            _syncStateFromDOM();
            _updateTokenEstimate();
        }, 300);
    }

    // ── Render function ──
    function render() {
        editorPanel.innerHTML = '';

        // ── Header ──
        const header = document.createElement('div');
        header.className = 'flex items-center justify-between px-5 py-3 flex-shrink-0';
        header.style.cssText = 'border-bottom: 1px solid rgba(148,163,184,0.08); background: rgba(0,0,0,0.05);';

        const badgeText = editorState.skillId ? `!${editorState.skillId}` : 'New Skill';
        const statusBadges = [
            editorState.isBuiltin ? '<span class="inline-flex items-center px-1.5 py-0.5 text-[10px] rounded" style="background:rgba(148,163,184,0.08);color:#94a3b8;border:1px solid rgba(148,163,184,0.15);">built-in</span>' : '',
            isNew ? '<span class="inline-flex items-center px-1.5 py-0.5 text-[10px] rounded" style="background:rgba(34,197,94,0.08);color:#22c55e;border:1px solid rgba(34,197,94,0.15);">new</span>' : '',
        ].filter(Boolean).join(' ');

        header.innerHTML = `
            <div class="flex items-center gap-3">
                <span id="skill-editor-badge" class="inline-flex items-center gap-1.5 px-2.5 py-1 text-sm font-semibold rounded-md" style="background:${EMERALD_BG};border:1px solid ${EMERALD_BORDER};color:${EMERALD};font-family:'JetBrains Mono',monospace;">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                    ${badgeText}
                </span>
                ${statusBadges}
            </div>
            <div class="flex items-center gap-3">
                <span id="skill-editor-dirty" class="inline-flex items-center gap-1.5 text-[10px] transition-opacity" style="color:#fbbf24;opacity:${hasChanges ? '1' : '0'};">
                    <span style="width:5px;height:5px;border-radius:50%;background:#fbbf24;display:inline-block;"></span>
                    Unsaved changes
                </span>
                <span id="skill-editor-status" class="text-[10px] font-medium" style="color:transparent;"></span>
                <button id="skill-editor-save" class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-all duration-200"
                    style="background:${EMERALD_BG};border:1px solid ${EMERALD_BORDER};color:${EMERALD};opacity:${hasChanges ? '1' : '0.4'};cursor:${hasChanges ? 'pointer' : 'default'};" ${hasChanges ? '' : 'disabled'}>
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
                    </svg>
                    <span id="skill-save-label">${isNew ? 'Create' : 'Save'}</span>
                </button>
                <button class="text-gray-500 hover:text-white transition-colors p-1.5 rounded-md hover:bg-white/5 skill-editor-close" title="Close (Esc)">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>`;
        editorPanel.appendChild(header);

        // ── Level selector (segmented control) ──
        const levelBar = document.createElement('div');
        levelBar.className = 'flex items-center px-5 py-2 flex-shrink-0';
        levelBar.style.cssText = 'border-bottom: 1px solid rgba(148,163,184,0.06); background: rgba(0,0,0,0.03);';

        const segmented = document.createElement('div');
        segmented.className = 'inline-flex rounded-lg p-0.5';
        segmented.style.cssText = 'background: rgba(0,0,0,0.2); border: 1px solid rgba(148,163,184,0.06);';

        const levels = [
            { id: 'citizen', label: 'Citizen', hint: 'Quick' },
            { id: 'intermediate', label: 'Intermediate', hint: 'Guided' },
            { id: 'expert', label: 'Expert', hint: 'Full Control' },
        ];
        segmented.innerHTML = levels.map(l => {
            const active = l.id === editorState.level;
            return `<button data-level="${l.id}" class="px-4 py-1.5 rounded-md text-xs font-medium transition-all duration-200" style="${active
                ? `background:${EMERALD_BG};color:${EMERALD};border:1px solid ${EMERALD_BORDER};box-shadow:${EMERALD_GLOW};`
                : 'background:transparent;color:#6b7280;border:1px solid transparent;'}">${l.label} <span class="text-[10px] ${active ? '' : 'opacity-50'}">${l.hint}</span></button>`;
        }).join('');
        levelBar.appendChild(segmented);
        editorPanel.appendChild(levelBar);

        // ── Body (level-specific) ──
        const body = document.createElement('div');
        if (editorState.level === 'expert') {
            body.className = 'flex-1 flex min-h-0';
            body.style.cssText = 'overflow: hidden; padding: 0;';
        } else {
            body.className = 'flex-1 overflow-y-auto px-5 py-4';
        }

        if (editorState.level === 'citizen') {
            _renderCitizenLevel(body, editorState);
        } else if (editorState.level === 'intermediate') {
            _renderIntermediateLevel(body, editorState);
        } else {
            _renderExpertLevel(body, editorState);
        }
        editorPanel.appendChild(body);

        // ── Footer ──
        const footer = document.createElement('div');
        footer.className = 'flex items-center justify-between px-5 py-2 flex-shrink-0';
        footer.style.cssText = 'border-top: 1px solid rgba(148,163,184,0.08); background: rgba(0,0,0,0.08);';
        const content = _buildContentFromState(editorState);
        const tokens = _estimateTokens(content);
        footer.innerHTML = `
            <span class="text-[10px] text-gray-500 font-mono" id="skill-token-estimate">~${tokens.toLocaleString()} tokens</span>
            <div class="flex items-center gap-3">
                <button class="text-[11px] px-3 py-1 rounded-md transition-colors skill-editor-close" style="color:var(--text-muted);border:1px solid var(--border-subtle);background:transparent;">Cancel</button>
                <button id="skill-editor-save-footer" class="text-[11px] px-3 py-1 rounded-md font-medium transition-all duration-200" style="background:${EMERALD_BG};border:1px solid ${EMERALD_BORDER};color:${EMERALD};opacity:${hasChanges ? '1' : '0.4'};" ${hasChanges ? '' : 'disabled'}>${isNew ? 'Create Skill' : 'Save Skill'}</button>
            </div>`;
        editorPanel.appendChild(footer);

        // ── Wire events ──
        _wireEditorEvents();
    }

    function _markDirty() {
        hasChanges = true;
        const saveBtn = editorPanel.querySelector('#skill-editor-save');
        const saveFooter = editorPanel.querySelector('#skill-editor-save-footer');
        const dirtyEl = editorPanel.querySelector('#skill-editor-dirty');
        if (saveBtn) { saveBtn.disabled = false; saveBtn.style.opacity = '1'; saveBtn.style.cursor = 'pointer'; }
        if (saveFooter) { saveFooter.disabled = false; saveFooter.style.opacity = '1'; }
        if (dirtyEl) dirtyEl.style.opacity = '1';
        _scheduleTokenUpdate();
    }

    function _wireEditorEvents() {
        // Level switcher
        editorPanel.querySelectorAll('[data-level]').forEach(btn => {
            btn.addEventListener('click', () => {
                const newLevel = btn.dataset.level;
                if (newLevel === editorState.level) return;
                _syncStateFromDOM();
                if (newLevel === 'expert') {
                    editorState.rawContent = _buildContentFromState(editorState);
                    editorState.rawManifest = JSON.stringify(_buildManifestFromState(editorState), null, 2);
                }
                if (editorState.level === 'expert' && newLevel !== 'expert') {
                    const parsed = _parseParamBlocks(editorState.rawContent);
                    editorState.instructions = parsed.baseContent;
                    editorState.params = parsed.params.map(p => ({ name: p.name, content: p.content, description: '' }));
                    try {
                        const m = JSON.parse(editorState.rawManifest);
                        editorState.description = m.description || editorState.description;
                        editorState.tags = m.tags || editorState.tags;
                        editorState.injectionTarget = m.uderia?.injection_target || 'system_prompt';
                        if (m.uderia?.param_descriptions) {
                            for (const p of editorState.params) p.description = m.uderia.param_descriptions[p.name] || '';
                        }
                    } catch { /* ignore */ }
                }
                editorState.level = newLevel;
                render();
            });
        });

        // Close buttons
        editorPanel.querySelectorAll('.skill-editor-close').forEach(btn => {
            btn.addEventListener('click', closeEditor);
        });

        // Save buttons (header + footer)
        editorPanel.querySelector('#skill-editor-save')?.addEventListener('click', handleSave);
        editorPanel.querySelector('#skill-editor-save-footer')?.addEventListener('click', handleSave);

        // Input change tracking
        editorPanel.querySelectorAll('input, textarea, select').forEach(el => {
            el.addEventListener('input', _markDirty);
            el.addEventListener('change', _markDirty);
        });

        // Ctrl+S / Cmd+S on all textareas
        editorPanel.querySelectorAll('textarea').forEach(ta => {
            ta.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                    e.preventDefault();
                    handleSave();
                }
            });
        });
    }

    function _syncStateFromDOM() {
        if (editorState.level === 'citizen') {
            const nameEl = editorPanel.querySelector('#skill-ed-name');
            const instrEl = editorPanel.querySelector('#skill-ed-instructions');
            if (nameEl) editorState.skillId = _slugify(nameEl.value);
            if (instrEl) editorState.instructions = instrEl.value;
        } else if (editorState.level === 'intermediate') {
            const nameEl = editorPanel.querySelector('#skill-ed-name');
            const descEl = editorPanel.querySelector('#skill-ed-description');
            const instrEl = editorPanel.querySelector('#skill-ed-instructions');
            const targetEl = editorPanel.querySelector('input[name="skill-injection-target"]:checked');
            if (nameEl) editorState.skillId = _slugify(nameEl.value);
            if (descEl) editorState.description = descEl.value;
            if (instrEl) editorState.instructions = instrEl.value;
            if (targetEl) editorState.injectionTarget = targetEl.value;
            const paramEls = editorPanel.querySelectorAll('[data-param-index]');
            const params = [];
            paramEls.forEach(el => {
                const ni = el.querySelector('.param-name');
                const di = el.querySelector('.param-desc');
                const ci = el.querySelector('.param-content');
                if (ni && ni.value.trim()) params.push({ name: ni.value.trim(), description: di?.value || '', content: ci?.value || '' });
            });
            editorState.params = params;
            _syncTagsFromDOM();
        } else if (editorState.level === 'expert') {
            const c = editorPanel.querySelector('#skill-ed-raw-content');
            const m = editorPanel.querySelector('#skill-ed-raw-manifest');
            if (c) editorState.rawContent = c.value;
            if (m) editorState.rawManifest = m.value;
        }
    }

    function _syncTagsFromDOM() {
        const tagEls = editorPanel.querySelectorAll('.skill-tag-chip');
        editorState.tags = Array.from(tagEls).map(el => el.dataset.tag).filter(Boolean);
    }

    async function handleSave() {
        _syncStateFromDOM();
        const skillId = editorState.skillId;
        if (!skillId) { _notify('error', 'Please enter a skill name'); return; }

        const saveBtn = editorPanel.querySelector('#skill-editor-save');
        const saveFooter = editorPanel.querySelector('#skill-editor-save-footer');
        const statusEl = editorPanel.querySelector('#skill-editor-status');
        const labelEl = editorPanel.querySelector('#skill-save-label');

        try {
            if (saveBtn) { saveBtn.disabled = true; saveBtn.style.opacity = '0.6'; }
            if (saveFooter) { saveFooter.disabled = true; saveFooter.style.opacity = '0.6'; saveFooter.textContent = 'Saving...'; }
            if (labelEl) labelEl.textContent = 'Saving...';
            if (statusEl) { statusEl.textContent = ''; statusEl.style.color = EMERALD; }

            const content = _buildContentFromState(editorState);
            let manifest;
            if (editorState.level === 'expert') {
                try { manifest = JSON.parse(editorState.rawManifest); } catch { manifest = _buildManifestFromState(editorState); }
            } else {
                manifest = _buildManifestFromState(editorState);
            }

            const resp = await fetch(`/api/v1/skills/${skillId}`, {
                method: 'PUT',
                headers: _authHeaders(),
                body: JSON.stringify({ content, manifest }),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || `Save failed: ${resp.status}`);

            hasChanges = false;
            if (statusEl) { statusEl.textContent = 'Saved'; statusEl.style.color = '#22c55e'; setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 3000); }
            if (labelEl) labelEl.textContent = 'Saved!';
            if (saveFooter) saveFooter.textContent = 'Saved!';
            const dirtyEl = editorPanel.querySelector('#skill-editor-dirty');
            if (dirtyEl) dirtyEl.style.opacity = '0';

            setTimeout(() => {
                if (labelEl) labelEl.textContent = isNew ? 'Create' : 'Save';
                if (saveFooter) saveFooter.textContent = isNew ? 'Create Skill' : 'Save Skill';
                if (saveBtn) { saveBtn.style.opacity = '0.4'; saveBtn.style.cursor = 'default'; }
                if (saveFooter) saveFooter.style.opacity = '0.4';
            }, 2000);

            // Update badge
            const badge = editorPanel.querySelector('#skill-editor-badge');
            if (badge) badge.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg> !${skillId}`;

            _notify('success', `Skill !${skillId} saved`);
            await loadSkills();
            if (window.loadActivatedSkills) window.loadActivatedSkills();

            // Auto-close modal after creating a new skill (brief delay to show "Saved!" feedback)
            if (isNew) {
                setTimeout(() => closeEditor(), 600);
            }
        } catch (err) {
            _notify('error', err.message);
            if (statusEl) { statusEl.textContent = 'Save failed'; statusEl.style.color = '#ef4444'; }
            if (labelEl) labelEl.textContent = isNew ? 'Create' : 'Save';
            if (saveFooter) saveFooter.textContent = isNew ? 'Create Skill' : 'Save Skill';
        } finally {
            if (hasChanges) {
                if (saveBtn) { saveBtn.disabled = false; saveBtn.style.opacity = '1'; saveBtn.style.cursor = 'pointer'; }
                if (saveFooter) { saveFooter.disabled = false; saveFooter.style.opacity = '1'; }
            }
        }
    }

    function closeEditor() {
        const doClose = () => {
            // Animate out
            overlay.style.opacity = '0';
            editorPanel.style.transform = 'scale(0.97)';
            editorPanel.style.opacity = '0';
            editorPanel.style.transition = `all 150ms ${SPRING_EASE}`;
            setTimeout(() => {
                overlay.remove();
                document.removeEventListener('keydown', escHandler);
            }, 160);
        };
        if (hasChanges) {
            window.showConfirmation(
                'Unsaved Changes',
                '<p>You have unsaved changes. Close anyway?</p>',
                doClose
            );
            return;
        }
        doClose();
    }

    const escHandler = (e) => { if (e.key === 'Escape') closeEditor(); };
    document.addEventListener('keydown', escHandler);

    overlay.appendChild(editorPanel);
    document.body.appendChild(overlay);

    // Trigger entrance animation
    requestAnimationFrame(() => { overlay.style.opacity = '1'; });

    render();
}

// ── Citizen Level ────────────────────────────────────────────────────────────

function _renderCitizenLevel(container, state) {
    container.innerHTML = `
        <div class="space-y-6 max-w-2xl mx-auto">
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2" style="color:${EMERALD};">Skill Name</label>
                <input type="text" id="skill-ed-name" value="${state.skillId}" maxlength="50"
                    placeholder="sql-expert"
                    class="w-full text-white rounded-lg px-3 py-2.5 text-sm font-mono transition-all duration-200"
                    style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.12);caret-color:${EMERALD};outline:none;"
                    ${state.isBuiltin ? 'readonly' : ''}>
                <p class="text-[11px] mt-1.5" style="color:#6b7280;">Users invoke with <span id="skill-ed-trigger-preview" style="color:${EMERALD};font-family:'JetBrains Mono',monospace;font-weight:600;">!${state.skillId || 'name'}</span></p>
            </div>

            <div>
                <div class="flex items-center justify-between mb-2">
                    <label class="block text-xs font-semibold uppercase tracking-wider" style="color:${EMERALD};">Instructions</label>
                    <span id="skill-ed-citizen-tokens" class="text-[10px] font-mono" style="color:#6b7280;">~${_estimateTokens(state.instructions)} tokens</span>
                </div>
                <textarea id="skill-ed-instructions" rows="18"
                    placeholder="You are an expert SQL developer. Follow these best practices:&#10;&#10;- Always use explicit JOINs&#10;- Use meaningful aliases&#10;- Include WHERE clauses to limit results"
                    class="w-full text-white rounded-lg px-4 py-3 text-sm resize-y transition-all duration-200"
                    style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.12);font-family:'JetBrains Mono','Fira Code',monospace;line-height:1.7;min-height:300px;caret-color:${EMERALD};outline:none;tab-size:4;-moz-tab-size:4;">${state.instructions}</textarea>
                <p class="text-[11px] mt-1.5" style="color:#6b7280;">What you write is what gets injected into the LLM prompt. Supports plain text or markdown.</p>
            </div>
        </div>`;

    // Focus glow on inputs
    container.querySelectorAll('input, textarea').forEach(el => {
        el.addEventListener('focus', () => { el.style.borderColor = EMERALD_BORDER; el.style.boxShadow = EMERALD_GLOW; });
        el.addEventListener('blur', () => { el.style.borderColor = 'rgba(148,163,184,0.12)'; el.style.boxShadow = 'none'; });
    });

    // Tab key → 4 spaces in textarea
    const instrEl = container.querySelector('#skill-ed-instructions');
    if (instrEl) {
        instrEl.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                e.preventDefault();
                const s = instrEl.selectionStart;
                instrEl.value = instrEl.value.substring(0, s) + '    ' + instrEl.value.substring(instrEl.selectionEnd);
                instrEl.selectionStart = instrEl.selectionEnd = s + 4;
                instrEl.dispatchEvent(new Event('input'));
            }
        });
        // Live token count
        instrEl.addEventListener('input', () => {
            const tokenEl = container.querySelector('#skill-ed-citizen-tokens');
            if (tokenEl) tokenEl.textContent = `~${_estimateTokens(instrEl.value)} tokens`;
        });
    }

    // Live slug + trigger preview
    const nameEl = container.querySelector('#skill-ed-name');
    if (nameEl) {
        nameEl.addEventListener('input', () => {
            const slug = _slugify(nameEl.value);
            state.skillId = slug;
            const preview = container.querySelector('#skill-ed-trigger-preview');
            if (preview) preview.textContent = `!${slug || 'name'}`;
            // Update header badge
            const badge = document.querySelector('#skill-editor-badge');
            if (badge) badge.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg> !${slug || 'New Skill'}`;
        });
    }
}

// ── Intermediate Level ───────────────────────────────────────────────────────

function _renderIntermediateLevel(container, state) {
    const tagsHtml = state.tags.map(t =>
        `<span class="skill-tag-chip inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs transition-all duration-150" data-tag="${t}" style="background:${EMERALD_BG};border:1px solid ${EMERALD_BORDER};color:${EMERALD_LIGHT};">
            ${t} <button class="remove-tag hover:text-white cursor-pointer" data-tag="${t}" style="font-size:14px;line-height:1;">&times;</button>
        </span>`
    ).join(' ');

    const paramsHtml = state.params.map((p, i) => `
        <div class="rounded-lg p-3 space-y-2 transition-all duration-200" data-param-index="${i}" style="background:rgba(0,0,0,0.15);border:1px solid rgba(148,163,184,0.08);border-left:3px solid ${EMERALD_BORDER};">
            <div class="flex items-center gap-2">
                <input type="text" class="param-name text-white rounded-md px-2.5 py-1.5 text-xs font-mono flex-1 transition-all duration-200" value="${p.name}" placeholder="param-name"
                    style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.1);caret-color:${EMERALD};outline:none;">
                <input type="text" class="param-desc text-gray-300 rounded-md px-2.5 py-1.5 text-xs flex-[2] transition-all duration-200" value="${p.description}" placeholder="Description (optional)"
                    style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.1);caret-color:${EMERALD};outline:none;">
                <button class="remove-param p-1 rounded transition-colors hover:bg-red-500/10" data-idx="${i}" title="Remove parameter">
                    <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="#ef4444" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
                </button>
            </div>
            <textarea class="param-content w-full text-white rounded-md px-2.5 py-1.5 text-xs font-mono resize-y transition-all duration-200" rows="3" placeholder="Additional instructions when !${state.skillId}:${p.name || 'param'} is used..."
                style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.1);line-height:1.6;caret-color:${EMERALD};outline:none;">${p.content}</textarea>
        </div>
    `).join('');

    const isSysPrompt = state.injectionTarget === 'system_prompt';

    container.innerHTML = `
        <div class="space-y-6 max-w-3xl mx-auto">
            <!-- Name + Description -->
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-xs font-semibold uppercase tracking-wider mb-2" style="color:${EMERALD};">Skill Name</label>
                    <input type="text" id="skill-ed-name" value="${state.skillId}" maxlength="50"
                        class="w-full text-white rounded-lg px-3 py-2.5 text-sm font-mono transition-all duration-200"
                        style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.12);caret-color:${EMERALD};outline:none;"
                        ${state.isBuiltin ? 'readonly' : ''}>
                </div>
                <div>
                    <label class="block text-xs font-semibold uppercase tracking-wider mb-2" style="color:${EMERALD};">Description</label>
                    <input type="text" id="skill-ed-description" value="${state.description}" maxlength="200"
                        placeholder="SQL best practices and expert guidance"
                        class="w-full text-white rounded-lg px-3 py-2.5 text-sm transition-all duration-200"
                        style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.12);caret-color:${EMERALD};outline:none;">
                </div>
            </div>

            <!-- Injection Target (segmented control) -->
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2" style="color:${EMERALD};">Injection Target</label>
                <div class="inline-flex rounded-lg p-0.5" style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.08);">
                    <label class="flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer transition-all duration-200" id="target-system-label"
                        style="${isSysPrompt ? `background:${EMERALD_BG};border:1px solid ${EMERALD_BORDER};` : 'background:transparent;border:1px solid transparent;'}">
                        <input type="radio" name="skill-injection-target" value="system_prompt" ${isSysPrompt ? 'checked' : ''} class="hidden">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" style="color:${isSysPrompt ? EMERALD : '#6b7280'};"><path stroke-linecap="round" stroke-linejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
                        <div>
                            <span class="text-xs font-medium" style="color:${isSysPrompt ? EMERALD : '#9ca3af'};">System Prompt</span>
                            <p class="text-[10px]" style="color:${isSysPrompt ? EMERALD_LIGHT : '#6b7280'};">Shapes how the LLM thinks</p>
                        </div>
                    </label>
                    <label class="flex items-center gap-2 px-4 py-2 rounded-md cursor-pointer transition-all duration-200" id="target-context-label"
                        style="${!isSysPrompt ? `background:${EMERALD_BG};border:1px solid ${EMERALD_BORDER};` : 'background:transparent;border:1px solid transparent;'}">
                        <input type="radio" name="skill-injection-target" value="user_context" ${!isSysPrompt ? 'checked' : ''} class="hidden">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" style="color:${!isSysPrompt ? EMERALD : '#6b7280'};"><path stroke-linecap="round" stroke-linejoin="round" d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z"/></svg>
                        <div>
                            <span class="text-xs font-medium" style="color:${!isSysPrompt ? EMERALD : '#9ca3af'};">User Context</span>
                            <p class="text-[10px]" style="color:${!isSysPrompt ? EMERALD_LIGHT : '#6b7280'};">Adds background info to query</p>
                        </div>
                    </label>
                </div>
            </div>

            <!-- Tags -->
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2" style="color:${EMERALD};">Tags</label>
                <div class="flex flex-wrap items-center gap-1.5 mb-2 min-h-[28px]" id="skill-ed-tags">
                    ${tagsHtml}
                </div>
                <div class="flex gap-2 items-center">
                    <input type="text" id="skill-ed-tag-input" placeholder="Add tag..." maxlength="30"
                        class="text-white rounded-md px-2.5 py-1.5 text-xs w-36 transition-all duration-200"
                        style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.1);caret-color:${EMERALD};outline:none;">
                    <button id="skill-ed-tag-add" class="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md font-medium transition-all duration-150"
                        style="background:${EMERALD_BG};color:${EMERALD};border:1px solid ${EMERALD_BORDER};">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
                        Add
                    </button>
                </div>
            </div>

            <!-- Instructions -->
            <div>
                <div class="flex items-center justify-between mb-2">
                    <label class="block text-xs font-semibold uppercase tracking-wider" style="color:${EMERALD};">Instructions</label>
                    <span id="skill-ed-int-tokens" class="text-[10px] font-mono" style="color:#6b7280;">~${_estimateTokens(state.instructions)} tokens</span>
                </div>
                <textarea id="skill-ed-instructions" rows="10"
                    placeholder="You are an expert SQL developer..."
                    class="w-full text-white rounded-lg px-4 py-3 text-sm resize-y transition-all duration-200"
                    style="background:rgba(0,0,0,0.2);border:1px solid rgba(148,163,184,0.12);font-family:'JetBrains Mono','Fira Code',monospace;line-height:1.7;min-height:150px;caret-color:${EMERALD};outline:none;tab-size:4;-moz-tab-size:4;">${state.instructions}</textarea>
            </div>

            <!-- Parameters -->
            <div>
                <div class="flex items-center justify-between mb-2">
                    <label class="text-xs font-semibold uppercase tracking-wider" style="color:${EMERALD};">Parameters <span class="text-[10px] font-normal normal-case" style="color:#6b7280;">(optional)</span></label>
                    <button id="skill-ed-add-param" class="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md font-medium transition-all duration-150"
                        style="background:${EMERALD_BG};color:${EMERALD};border:1px solid ${EMERALD_BORDER};">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
                        Add Param
                    </button>
                </div>
                <div id="skill-ed-params" class="space-y-2">
                    ${paramsHtml}
                </div>
                ${state.params.length === 0
                    ? `<p class="text-[11px] mt-2" style="color:#6b7280;">No parameters defined. Users trigger with <span style="color:${EMERALD};font-family:'JetBrains Mono',monospace;font-weight:600;">!${state.skillId || 'name'}</span> only.</p>`
                    : `<p class="text-[11px] mt-2" style="color:#6b7280;">Users trigger with <span style="color:${EMERALD};font-family:'JetBrains Mono',monospace;font-weight:600;">!${state.skillId || 'name'}:param</span> to include param-specific content.</p>`
                }
            </div>
        </div>`;

    // Focus glow on all inputs/textareas
    container.querySelectorAll('input[type="text"], textarea').forEach(el => {
        el.addEventListener('focus', () => { el.style.borderColor = EMERALD_BORDER; el.style.boxShadow = EMERALD_GLOW; });
        el.addEventListener('blur', () => { el.style.borderColor = 'rgba(148,163,184,0.12)'; el.style.boxShadow = 'none'; });
    });

    // Injection target segmented control
    container.querySelectorAll('input[name="skill-injection-target"]').forEach(radio => {
        radio.addEventListener('change', () => {
            state.injectionTarget = radio.value;
            // Re-render to update visual state
            _renderIntermediateLevel(container, state);
        });
    });

    // Tab → 4 spaces in instructions
    const instrEl = container.querySelector('#skill-ed-instructions');
    if (instrEl) {
        instrEl.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                e.preventDefault();
                const s = instrEl.selectionStart;
                instrEl.value = instrEl.value.substring(0, s) + '    ' + instrEl.value.substring(instrEl.selectionEnd);
                instrEl.selectionStart = instrEl.selectionEnd = s + 4;
                instrEl.dispatchEvent(new Event('input'));
            }
        });
        instrEl.addEventListener('input', () => {
            const tokenEl = container.querySelector('#skill-ed-int-tokens');
            if (tokenEl) tokenEl.textContent = `~${_estimateTokens(instrEl.value)} tokens`;
        });
    }

    // Wire tag add
    const tagAddBtn = container.querySelector('#skill-ed-tag-add');
    const tagInput = container.querySelector('#skill-ed-tag-input');
    if (tagAddBtn && tagInput) {
        const addTag = () => {
            const tag = tagInput.value.trim().toLowerCase().replace(/[^a-z0-9-]/g, '');
            if (tag && !state.tags.includes(tag)) {
                state.tags.push(tag);
                tagInput.value = '';
                const tagsContainer = container.querySelector('#skill-ed-tags');
                const chip = document.createElement('span');
                chip.className = 'skill-tag-chip inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs transition-all duration-150';
                chip.dataset.tag = tag;
                chip.style.cssText = `background:${EMERALD_BG};border:1px solid ${EMERALD_BORDER};color:${EMERALD_LIGHT};animation:skillEditorIn 200ms ease forwards;`;
                chip.innerHTML = `${tag} <button class="remove-tag hover:text-white cursor-pointer" data-tag="${tag}" style="font-size:14px;line-height:1;">&times;</button>`;
                tagsContainer.appendChild(chip);
            }
        };
        tagAddBtn.addEventListener('click', addTag);
        tagInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addTag(); } });
        // Focus glow
        tagInput.addEventListener('focus', () => { tagInput.style.borderColor = EMERALD_BORDER; tagInput.style.boxShadow = EMERALD_GLOW; });
        tagInput.addEventListener('blur', () => { tagInput.style.borderColor = 'rgba(148,163,184,0.1)'; tagInput.style.boxShadow = 'none'; });
    }

    // Wire tag remove (delegated)
    container.addEventListener('click', (e) => {
        if (e.target.classList.contains('remove-tag')) {
            const tag = e.target.dataset.tag;
            state.tags = state.tags.filter(t => t !== tag);
            const chip = e.target.closest('.skill-tag-chip');
            if (chip) { chip.style.opacity = '0'; chip.style.transform = 'scale(0.8)'; setTimeout(() => chip.remove(), 150); }
        }
    });

    // Wire param add
    const addParamBtn = container.querySelector('#skill-ed-add-param');
    if (addParamBtn) {
        addParamBtn.addEventListener('click', () => {
            state.params.push({ name: '', description: '', content: '' });
            _renderIntermediateLevel(container, state);
        });
    }

    // Wire param remove
    container.querySelectorAll('.remove-param').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.idx);
            state.params.splice(idx, 1);
            _renderIntermediateLevel(container, state);
        });
    });

    // Wire param input focus glow
    container.querySelectorAll('.param-name, .param-desc, .param-content').forEach(el => {
        el.addEventListener('focus', () => { el.style.borderColor = EMERALD_BORDER; el.style.boxShadow = EMERALD_GLOW; });
        el.addEventListener('blur', () => { el.style.borderColor = 'rgba(148,163,184,0.1)'; el.style.boxShadow = 'none'; });
    });

    // Live slug preview + header badge update
    const nameEl = container.querySelector('#skill-ed-name');
    if (nameEl) {
        nameEl.addEventListener('input', () => {
            state.skillId = _slugify(nameEl.value);
            const badge = document.querySelector('#skill-editor-badge');
            if (badge) badge.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg> !${state.skillId || 'New Skill'}`;
        });
    }
}

// ── Expert Level ─────────────────────────────────────────────────────────────

function _buildLineNumbers(text) {
    const count = (text.match(/\n/g) || []).length + 1;
    const lines = [];
    for (let i = 1; i <= count; i++) lines.push(i);
    return lines.map(n => `<span style="display:block;text-align:right;color:#4b5563;user-select:none;">${n}</span>`).join('');
}

function _renderExpertLevel(container, state) {
    container.innerHTML = '';

    // Left pane
    const leftPane = document.createElement('div');
    leftPane.className = 'flex flex-col flex-1 min-w-0';
    leftPane.style.borderRight = '1px solid rgba(148,163,184,0.08)';

    // Tab bar
    const tabBar = document.createElement('div');
    tabBar.className = 'flex items-center gap-0 flex-shrink-0';
    tabBar.style.cssText = 'border-bottom: 1px solid rgba(148,163,184,0.08); background: rgba(0,0,0,0.1);';
    tabBar.innerHTML = `
        <button class="expert-tab px-4 py-2 text-xs font-medium transition-all duration-150" data-tab="content" style="color:${EMERALD};border-bottom:2px solid ${EMERALD};">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 inline mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>Content
        </button>
        <button class="expert-tab px-4 py-2 text-xs font-medium text-gray-500 hover:text-gray-300 transition-all duration-150" data-tab="manifest" style="border-bottom:2px solid transparent;">
            <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3 inline mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>Manifest
        </button>`;
    leftPane.appendChild(tabBar);

    // File path bar
    const pathBar = document.createElement('div');
    pathBar.className = 'flex items-center gap-2 px-4 py-1 text-[10px] flex-shrink-0';
    pathBar.style.cssText = 'background:rgba(0,0,0,0.15);border-bottom:1px solid rgba(148,163,184,0.06);';
    pathBar.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="#6b7280" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
        <span id="expert-file-path" class="text-gray-500 font-mono">~/.tda/skills/${state.skillId}/${state.skillId}.md</span>`;
    leftPane.appendChild(pathBar);

    // Editor wrapper (line numbers + textarea)
    const editorWrapper = document.createElement('div');
    editorWrapper.className = 'flex-1 flex relative overflow-hidden';
    editorWrapper.style.background = 'rgba(0,0,0,0.2)';

    // Line number gutter
    const gutter = document.createElement('div');
    gutter.id = 'skill-ed-gutter';
    gutter.className = 'flex-shrink-0 overflow-hidden select-none';
    gutter.style.cssText = `width:48px;padding:12px 8px 12px 0;font-family:"JetBrains Mono","Fira Code",monospace;font-size:0.75rem;line-height:1.6;background:rgba(0,0,0,0.1);border-right:1px solid rgba(148,163,184,0.06);text-align:right;`;
    gutter.innerHTML = _buildLineNumbers(state.rawContent);
    editorWrapper.appendChild(gutter);

    // Textarea container (for content + manifest)
    const taContainer = document.createElement('div');
    taContainer.className = 'flex-1 relative overflow-hidden';

    const contentArea = document.createElement('textarea');
    contentArea.id = 'skill-ed-raw-content';
    contentArea.className = 'absolute inset-0 w-full h-full resize-none';
    contentArea.style.cssText = `padding:12px 16px;font-family:"JetBrains Mono","Fira Code",monospace;font-size:0.75rem;line-height:1.6;background:transparent;color:rgba(209,213,219,0.9);caret-color:${EMERALD};border:none;white-space:pre;tab-size:4;-moz-tab-size:4;outline:none;overflow-y:auto;`;
    contentArea.value = state.rawContent;
    contentArea.spellcheck = false;

    const manifestArea = document.createElement('textarea');
    manifestArea.id = 'skill-ed-raw-manifest';
    manifestArea.className = 'absolute inset-0 w-full h-full resize-none hidden';
    manifestArea.style.cssText = `padding:12px 16px;font-family:"JetBrains Mono","Fira Code",monospace;font-size:0.75rem;line-height:1.6;background:transparent;color:rgba(209,213,219,0.9);caret-color:${EMERALD};border:none;white-space:pre;tab-size:4;-moz-tab-size:4;outline:none;overflow-y:auto;`;
    manifestArea.value = state.rawManifest;
    manifestArea.spellcheck = false;

    taContainer.appendChild(contentArea);
    taContainer.appendChild(manifestArea);
    editorWrapper.appendChild(taContainer);
    leftPane.appendChild(editorWrapper);

    // Token estimate bar at bottom of left pane
    const tokenBar = document.createElement('div');
    tokenBar.className = 'flex items-center justify-between px-4 py-1 text-[10px] flex-shrink-0';
    tokenBar.style.cssText = 'border-top:1px solid rgba(148,163,184,0.06);background:rgba(0,0,0,0.1);';
    const baseTokens = _estimateTokens(state.rawContent);
    tokenBar.innerHTML = `
        <span class="font-mono" style="color:#6b7280;" id="expert-token-display">~${baseTokens.toLocaleString()} tokens</span>
        <span class="font-mono" style="color:#4b5563;" id="expert-line-count">${(state.rawContent.match(/\n/g) || []).length + 1} lines</span>`;
    leftPane.appendChild(tokenBar);

    // Right pane: Live preview
    const rightPane = document.createElement('div');
    rightPane.className = 'flex flex-col';
    rightPane.style.cssText = 'width:380px;flex-shrink:0;';

    const previewHeader = document.createElement('div');
    previewHeader.className = 'flex items-center gap-2 px-4 py-2 flex-shrink-0';
    previewHeader.style.cssText = `border-bottom:1px solid rgba(148,163,184,0.08);background:rgba(0,0,0,0.1);`;
    previewHeader.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="${EMERALD}" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
        <span class="text-xs font-medium" style="color:${EMERALD};">Live Preview</span>`;
    rightPane.appendChild(previewHeader);

    const previewBody = document.createElement('div');
    previewBody.id = 'skill-ed-preview';
    previewBody.className = 'flex-1 overflow-y-auto p-4 max-w-none';
    previewBody.style.cssText = 'font-size:0.8rem;line-height:1.7;color:#d1d5db;';
    rightPane.appendChild(previewBody);

    container.appendChild(leftPane);
    container.appendChild(rightPane);

    // ── Tab handling ──
    [contentArea, manifestArea].forEach(ta => {
        ta.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                e.preventDefault();
                const s = ta.selectionStart;
                ta.value = ta.value.substring(0, s) + '    ' + ta.value.substring(ta.selectionEnd);
                ta.selectionStart = ta.selectionEnd = s + 4;
                ta.dispatchEvent(new Event('input'));
            }
        });
    });

    // ── Scroll sync: textarea → gutter ──
    let activeTextarea = contentArea;
    contentArea.addEventListener('scroll', () => { gutter.scrollTop = contentArea.scrollTop; });
    manifestArea.addEventListener('scroll', () => { gutter.scrollTop = manifestArea.scrollTop; });

    // ── Tab switching ──
    tabBar.querySelectorAll('.expert-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            tabBar.querySelectorAll('.expert-tab').forEach(b => {
                b.style.color = '#6b7280';
                b.style.borderBottomColor = 'transparent';
            });
            btn.style.color = EMERALD;
            btn.style.borderBottomColor = EMERALD;
            const pathEl = leftPane.querySelector('#expert-file-path');
            if (tab === 'content') {
                contentArea.classList.remove('hidden');
                manifestArea.classList.add('hidden');
                activeTextarea = contentArea;
                if (pathEl) pathEl.textContent = `~/.tda/skills/${state.skillId}/${state.skillId}.md`;
                gutter.innerHTML = _buildLineNumbers(contentArea.value);
                updateTokenDisplay(contentArea.value);
            } else {
                contentArea.classList.add('hidden');
                manifestArea.classList.remove('hidden');
                activeTextarea = manifestArea;
                if (pathEl) pathEl.textContent = `~/.tda/skills/${state.skillId}/skill.json`;
                gutter.innerHTML = _buildLineNumbers(manifestArea.value);
                updateTokenDisplay(manifestArea.value);
            }
            gutter.scrollTop = activeTextarea.scrollTop;
        });
    });

    // ── Live updates ──
    function updateTokenDisplay(text) {
        const tokenEl = leftPane.querySelector('#expert-token-display');
        const lineEl = leftPane.querySelector('#expert-line-count');
        if (tokenEl) tokenEl.textContent = `~${_estimateTokens(text).toLocaleString()} tokens`;
        if (lineEl) lineEl.textContent = `${(text.match(/\n/g) || []).length + 1} lines`;
    }

    let previewTimer = null;
    function updatePreview() {
        previewBody.innerHTML = _renderMarkdownPreview(contentArea.value);
    }

    contentArea.addEventListener('input', () => {
        gutter.innerHTML = _buildLineNumbers(contentArea.value);
        updateTokenDisplay(contentArea.value);
        clearTimeout(previewTimer);
        previewTimer = setTimeout(updatePreview, 200);
    });

    manifestArea.addEventListener('input', () => {
        gutter.innerHTML = _buildLineNumbers(manifestArea.value);
        updateTokenDisplay(manifestArea.value);
    });

    // Initial preview
    updatePreview();
}

// Expose globally
window.openSkillEditor = openSkillEditor;
