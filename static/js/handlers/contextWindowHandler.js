/**
 * Context Window Type management handler.
 *
 * Manages context window types in the Setup panel:
 *   - Card rendering for each type
 *   - Create/edit modal with module composition editor
 *   - Delete confirmation with profile dependency check
 *   - Module listing and purge actions
 *
 * Follows the exact same patterns as LLM Configuration management
 * in configurationHandler.js.
 */

import { showConfirmation, escapeHtml } from '../ui.js';
import { showAppBanner } from '../bannerSystem.js';

function showNotification(type, message) {
    showAppBanner(message, type);
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let contextWindowTypes = [];
let installedModules = [];

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

export async function loadContextWindowTypes() {
    const token = localStorage.getItem('tda_auth_token');
    try {
        const [typesRes, modulesRes] = await Promise.all([
            fetch('/api/v1/context-window-types', {
                headers: { 'Authorization': `Bearer ${token}` }
            }),
            fetch('/api/v1/context-window/modules', {
                headers: { 'Authorization': `Bearer ${token}` }
            })
        ]);

        if (typesRes.ok) {
            const data = await typesRes.json();
            contextWindowTypes = data.context_window_types || [];
        }
        if (modulesRes.ok) {
            const data = await modulesRes.json();
            installedModules = data.modules || [];
        }
    } catch (err) {
        console.error('Failed to load context window data:', err);
    }
}

export function getContextWindowTypes() {
    return contextWindowTypes;
}

// ---------------------------------------------------------------------------
// Card rendering
// ---------------------------------------------------------------------------

export function renderContextWindowTypes() {
    const container = document.getElementById('context-window-types-container');
    if (!container) return;

    if (contextWindowTypes.length === 0) {
        container.innerHTML = `
            <div class="col-span-full text-center text-gray-400 py-8">
                <p class="text-lg mb-2">No context window types configured</p>
                <p class="text-sm">Click "+ Add Type" to create your first context window type.</p>
            </div>`;
        return;
    }

    container.innerHTML = contextWindowTypes.map(cwt => {
        const modules = cwt.modules || {};
        const activeCount = Object.values(modules).filter(m => m.active).length;
        const totalCount = Object.keys(modules).length;
        const isDefault = cwt.is_default;

        // Build module bar visualization
        const barSegments = Object.entries(modules)
            .filter(([, m]) => m.active)
            .sort((a, b) => (b[1].priority || 0) - (a[1].priority || 0))
            .map(([id, m]) => {
                const pct = m.target_pct || 0;
                const color = getModuleColor(id);
                return `<div class="h-2 rounded-sm" style="width:${pct}%;background:${color}" title="${id}: ${pct}%"></div>`;
            }).join('');

        const defaultBadge = isDefault
            ? '<span class="inline-flex items-center px-2 py-0.5 text-xs font-medium bg-blue-500 text-white rounded-full">Default</span>'
            : '';

        return `
            <div class="bg-gradient-to-br from-white/10 to-white/5 border-2 border-white/10 rounded-xl p-5 hover:border-white/20 transition-all duration-200" data-cwt-id="${cwt.id}">
                <div class="flex flex-col gap-3">
                    <div class="flex items-start justify-between">
                        <h4 class="text-lg font-bold text-white">${escapeHtml(cwt.name)}</h4>
                        ${defaultBadge}
                    </div>
                    <p class="text-sm text-gray-400 line-clamp-2">${escapeHtml(cwt.description || '')}</p>
                    <div class="space-y-2">
                        <div class="flex items-center gap-2 text-sm">
                            <span class="font-semibold text-gray-300">Modules:</span>
                            <span class="text-gray-400">${activeCount}/${totalCount} active</span>
                        </div>
                        <div class="flex items-center gap-2 text-sm">
                            <span class="font-semibold text-gray-300">Output Reserve:</span>
                            <span class="text-gray-400">${cwt.output_reserve_pct || 12}%</span>
                        </div>
                        <div class="flex gap-0.5 w-full rounded overflow-hidden bg-white/5 h-2">
                            ${barSegments}
                        </div>
                    </div>
                    <div class="flex items-center gap-2 pt-2 border-t border-white/10">
                        <button type="button" data-action="edit-cwt" data-cwt-id="${cwt.id}" class="flex-1 card-btn card-btn--neutral">Edit</button>
                        <button type="button" data-action="duplicate-cwt" data-cwt-id="${cwt.id}" class="card-btn card-btn--info">Duplicate</button>
                        <button type="button" data-action="delete-cwt" data-cwt-id="${cwt.id}" class="card-btn card-btn--danger" ${isDefault ? 'disabled title="Cannot delete default type"' : ''}>Delete</button>
                    </div>
                </div>
            </div>`;
    }).join('');

    attachContextWindowTypeListeners();
}

export function renderInstalledModules() {
    const container = document.getElementById('context-modules-container');
    if (!container) return;

    if (installedModules.length === 0) {
        container.innerHTML = `<div class="col-span-full text-center text-gray-400 py-4">No context modules installed.</div>`;
        return;
    }

    container.innerHTML = installedModules.map(mod => {
        const capsules = mod.capabilities || {};
        const badges = [];
        if (capsules.condensable) badges.push('<span class="text-xs px-1.5 py-0.5 rounded bg-yellow-500/20 text-yellow-300">Condensable</span>');
        if (capsules.purgeable) badges.push('<span class="text-xs px-1.5 py-0.5 rounded bg-red-500/20 text-red-300">Purgeable</span>');
        if (mod.applicability?.required) badges.push('<span class="text-xs px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-300">Required</span>');

        const color = getModuleColor(mod.module_id);

        return `
            <div class="bg-white/5 border border-white/10 rounded-lg p-3 hover:border-white/20 transition-colors">
                <div class="flex items-center gap-2 mb-1">
                    <div class="w-3 h-3 rounded-sm" style="background:${color}"></div>
                    <span class="font-semibold text-white text-sm">${escapeHtml(mod.display_name)}</span>
                    <span class="text-xs text-gray-500">${mod.source}</span>
                </div>
                <p class="text-xs text-gray-400 mb-2">${escapeHtml(mod.description || '')}</p>
                <div class="flex items-center gap-1 flex-wrap">
                    ${badges.join('')}
                    <span class="text-xs text-gray-500 ml-auto">P${mod.defaults?.priority || 50}</span>
                </div>
            </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------

function attachContextWindowTypeListeners() {
    const container = document.getElementById('context-window-types-container');
    if (!container) return;

    container.querySelectorAll('[data-action="edit-cwt"]').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.cwtId;
            showContextWindowTypeModal(id);
        });
    });

    container.querySelectorAll('[data-action="duplicate-cwt"]').forEach(btn => {
        btn.addEventListener('click', () => duplicateContextWindowType(btn.dataset.cwtId));
    });

    container.querySelectorAll('[data-action="delete-cwt"]').forEach(btn => {
        btn.addEventListener('click', () => deleteContextWindowType(btn.dataset.cwtId));
    });
}

// ---------------------------------------------------------------------------
// Create / Edit modal
// ---------------------------------------------------------------------------

export function showContextWindowTypeModal(typeId = null) {
    const existing = typeId ? contextWindowTypes.find(t => t.id === typeId) : null;
    const isEdit = !!existing;

    const allModules = installedModules.length > 0
        ? installedModules
        : [
            { module_id: 'system_prompt', display_name: 'System Prompt', defaults: { priority: 95, target_pct: 10, min_pct: 5, max_pct: 15 }, applicability: { required: true } },
            { module_id: 'tool_definitions', display_name: 'Tool Definitions', defaults: { priority: 85, target_pct: 22, min_pct: 0, max_pct: 40 } },
            { module_id: 'conversation_history', display_name: 'Conversation History', defaults: { priority: 80, target_pct: 22, min_pct: 10, max_pct: 60 }, applicability: { required: true } },
            { module_id: 'rag_context', display_name: 'RAG Cases', defaults: { priority: 75, target_pct: 15, min_pct: 0, max_pct: 30 } },
            { module_id: 'knowledge_context', display_name: 'Knowledge Documents', defaults: { priority: 70, target_pct: 10, min_pct: 0, max_pct: 25 } },
            { module_id: 'plan_hydration', display_name: 'Plan Hydration', defaults: { priority: 65, target_pct: 8, min_pct: 0, max_pct: 15 } },
            { module_id: 'document_context', display_name: 'Uploaded Documents', defaults: { priority: 60, target_pct: 5, min_pct: 0, max_pct: 15 } },
            { module_id: 'component_instructions', display_name: 'Component Instructions', defaults: { priority: 55, target_pct: 4, min_pct: 0, max_pct: 10 } },
            { module_id: 'workflow_history', display_name: 'Workflow History', defaults: { priority: 50, target_pct: 4, min_pct: 0, max_pct: 10 } },
        ];

    // Build module rows
    const moduleRows = allModules.map(mod => {
        const modConfig = existing?.modules?.[mod.module_id] || {};
        const active = modConfig.active !== undefined ? modConfig.active : true;
        const targetPct = modConfig.target_pct !== undefined ? modConfig.target_pct : (mod.defaults?.target_pct || 5);
        const minPct = modConfig.min_pct !== undefined ? modConfig.min_pct : (mod.defaults?.min_pct || 0);
        const maxPct = modConfig.max_pct !== undefined ? modConfig.max_pct : (mod.defaults?.max_pct || 15);
        const priority = modConfig.priority !== undefined ? modConfig.priority : (mod.defaults?.priority || 50);
        const isRequired = mod.applicability?.required || false;
        const color = getModuleColor(mod.module_id);

        return `
            <div class="py-2 px-3 rounded-lg bg-white/5 border border-white/10" data-module-id="${mod.module_id}">
                <div class="flex items-center gap-3">
                    <input type="checkbox" class="cwt-module-active rounded" ${active ? 'checked' : ''} ${isRequired ? 'disabled checked' : ''}>
                    <div class="w-3 h-3 rounded-sm flex-shrink-0" style="background:${color}"></div>
                    <span class="text-sm text-white flex-shrink-0 w-36 truncate" title="${mod.display_name}">${escapeHtml(mod.display_name)}</span>
                    ${isRequired ? '<span class="text-xs text-blue-400">Required</span>' : ''}
                    <div class="flex items-center gap-2 ml-auto">
                        <label class="text-xs text-gray-400">Target:</label>
                        <input type="number" class="cwt-module-target w-12 text-xs p-1 bg-gray-700 border border-gray-600 rounded text-center text-white" value="${targetPct}" min="${minPct}" max="${maxPct}">
                        <span class="text-xs text-gray-500">%</span>
                        <label class="text-xs text-gray-400 ml-2">P:</label>
                        <input type="number" class="cwt-module-priority w-12 text-xs p-1 bg-gray-700 border border-gray-600 rounded text-center text-white" value="${priority}" min="1" max="100">
                    </div>
                </div>
                <div class="flex items-center gap-2 mt-1 pl-12">
                    <label class="text-xs text-gray-500">Min:</label>
                    <input type="number" class="cwt-module-min w-10 text-xs p-0.5 bg-gray-800 border border-gray-700 rounded text-center text-gray-300" value="${minPct}" min="0" max="100">
                    <span class="text-xs text-gray-600">%</span>
                    <label class="text-xs text-gray-500 ml-1">Max:</label>
                    <input type="number" class="cwt-module-max w-10 text-xs p-0.5 bg-gray-800 border border-gray-700 rounded text-center text-gray-300" value="${maxPct}" min="0" max="100">
                    <span class="text-xs text-gray-600">%</span>
                </div>
            </div>`;
    }).join('');

    // Build condensation order section
    const condensationOrderHTML = buildCondensationOrderSection(allModules, existing);

    // Build dynamic adjustments section
    const adjustmentsHTML = buildDynamicAdjustmentsSection(existing?.dynamic_adjustments || [], allModules);

    const modalHTML = `
        <div id="cwt-modal" class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
            <div class="glass-panel rounded-xl p-6 max-w-3xl w-full mx-4 max-h-[90vh] overflow-y-auto">
                <h3 class="text-xl font-bold text-white mb-4">${isEdit ? 'Edit' : 'Create'} Context Window Type</h3>

                <div id="cwt-modal-error" class="hidden mb-4 p-3 bg-red-500/20 border border-red-500 rounded-md text-red-300 text-sm"></div>

                <div class="space-y-4">
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-300 mb-1">Name</label>
                            <input type="text" id="cwt-modal-name" value="${existing ? escapeHtml(existing.name) : ''}"
                                placeholder="e.g., Balanced" class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none text-white">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-300 mb-1">Output Reserve %</label>
                            <input type="number" id="cwt-modal-reserve" value="${existing?.output_reserve_pct || 12}"
                                min="5" max="30" class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none text-white">
                        </div>
                    </div>

                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-1">Description</label>
                        <input type="text" id="cwt-modal-desc" value="${existing ? escapeHtml(existing.description || '') : ''}"
                            placeholder="Short description of this type"
                            class="w-full p-2 bg-gray-700 border border-gray-600 rounded-md focus:ring-2 focus:ring-[#F15F22] focus:border-[#F15F22] outline-none text-white">
                    </div>

                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-2">Module Composition</label>
                        <div id="cwt-budget-bar" class="flex gap-0.5 w-full h-4 rounded overflow-hidden bg-white/5 mb-1"></div>
                        <div id="cwt-budget-text" class="text-xs text-gray-400 mb-3">Total: 0%</div>
                        <div class="space-y-2" id="cwt-modal-modules">
                            ${moduleRows}
                        </div>
                    </div>

                    <div>
                        <label class="block text-sm font-medium text-gray-300 mb-2">Condensation Order</label>
                        <p class="text-xs text-gray-500 mb-2">When over budget, modules are condensed top-to-bottom. Drag to reorder.</p>
                        <div class="space-y-1" id="cwt-condensation-list">
                            ${condensationOrderHTML}
                        </div>
                    </div>

                    <div>
                        <div class="flex items-center justify-between mb-2">
                            <label class="block text-sm font-medium text-gray-300">Dynamic Adjustments</label>
                            <button type="button" id="cwt-add-rule-btn" class="text-xs px-2 py-1 bg-white/10 hover:bg-white/20 text-gray-300 rounded transition-colors">+ Add Rule</button>
                        </div>
                        <p class="text-xs text-gray-500 mb-2">Rules that adjust module budgets based on runtime conditions.</p>
                        <div class="space-y-2" id="cwt-adjustments-list">
                            ${adjustmentsHTML}
                        </div>
                    </div>

                    <div class="flex gap-3 pt-4">
                        <button id="cwt-modal-cancel" class="flex-1 card-btn card-btn--neutral">Cancel</button>
                        <button id="cwt-modal-save" class="flex-1 card-btn card-btn--primary">${isEdit ? 'Update' : 'Create'}</button>
                    </div>
                </div>
            </div>
        </div>`;

    document.body.insertAdjacentHTML('beforeend', modalHTML);

    const modal = document.getElementById('cwt-modal');
    modal.querySelector('#cwt-modal-cancel').addEventListener('click', () => modal.remove());
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
    modal.querySelector('#cwt-modal-save').addEventListener('click', () => saveContextWindowType(typeId, modal));

    // --- Budget summary bar: update on any target/active/reserve change ---
    const budgetHandler = () => updateBudgetSummary(modal);
    modal.querySelectorAll('.cwt-module-target').forEach(el => el.addEventListener('input', budgetHandler));
    modal.querySelectorAll('.cwt-module-active').forEach(el => el.addEventListener('change', (e) => {
        budgetHandler();
        rebuildCondensationOrder(modal);
    }));
    modal.querySelector('#cwt-modal-reserve')?.addEventListener('input', budgetHandler);
    budgetHandler(); // initial render

    // --- Condensation order: up/down buttons ---
    modal.querySelector('#cwt-condensation-list')?.addEventListener('click', (e) => {
        const btn = e.target.closest('[data-cond-dir]');
        if (btn) moveCondensationItem(btn);
    });

    // --- Dynamic adjustments: add/remove/action-type-change ---
    modal.querySelector('#cwt-add-rule-btn')?.addEventListener('click', () => {
        addDynamicAdjustmentRule(modal.querySelector('#cwt-adjustments-list'), allModules);
    });
    modal.querySelector('#cwt-adjustments-list')?.addEventListener('click', (e) => {
        if (e.target.closest('.cwt-rule-delete')) {
            e.target.closest('.cwt-rule-row')?.remove();
        }
    });
    modal.querySelector('#cwt-adjustments-list')?.addEventListener('change', (e) => {
        if (e.target.classList.contains('cwt-rule-action-type')) {
            onActionTypeChange(e.target.closest('.cwt-rule-row'));
        }
    });
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

async function saveContextWindowType(existingId, modal) {
    const name = modal.querySelector('#cwt-modal-name').value.trim();
    const description = modal.querySelector('#cwt-modal-desc').value.trim();
    const outputReservePct = parseInt(modal.querySelector('#cwt-modal-reserve').value) || 12;
    const errorDiv = modal.querySelector('#cwt-modal-error');

    if (!name) {
        errorDiv.textContent = 'Name is required';
        errorDiv.classList.remove('hidden');
        return;
    }

    // Build modules config from form
    const modules = {};
    modal.querySelectorAll('#cwt-modal-modules [data-module-id]').forEach(row => {
        const moduleId = row.dataset.moduleId;
        const active = row.querySelector('.cwt-module-active').checked;
        const targetPct = parseInt(row.querySelector('.cwt-module-target').value) || 0;
        const priority = parseInt(row.querySelector('.cwt-module-priority').value) || 50;
        const minPct = parseInt(row.querySelector('.cwt-module-min')?.value) || 0;
        const maxPct = parseInt(row.querySelector('.cwt-module-max')?.value) || 100;

        modules[moduleId] = { active, target_pct: targetPct, min_pct: minPct, max_pct: maxPct, priority };
    });

    // Read condensation order from the reorderable list
    const condensationOrder = [];
    modal.querySelectorAll('#cwt-condensation-list [data-cond-module-id]').forEach(el => {
        condensationOrder.push(el.dataset.condModuleId);
    });

    // Build dynamic adjustments from the rules editor
    const dynamicAdjustments = [];
    modal.querySelectorAll('.cwt-rule-row').forEach(row => {
        const condition = row.querySelector('.cwt-rule-condition')?.value;
        const actionType = row.querySelector('.cwt-rule-action-type')?.value;
        const targetModule = row.querySelector('.cwt-rule-target-module')?.value;
        if (!condition || !actionType) return;

        const rule = { condition, action: {} };
        if (actionType === 'force_full') {
            rule.action.force_full = targetModule;
        } else if (actionType === 'transfer') {
            rule.action.transfer = targetModule;
            rule.action.to = row.querySelector('.cwt-rule-to-module')?.value || '';
        } else if (actionType === 'reduce') {
            rule.action.reduce = targetModule;
            rule.action.by_pct = parseInt(row.querySelector('.cwt-rule-by-pct')?.value) || 50;
        } else if (actionType === 'condense') {
            rule.action.condense = targetModule;
        }
        dynamicAdjustments.push(rule);
    });

    const payload = {
        name,
        description,
        output_reserve_pct: outputReservePct,
        modules,
        condensation_order: condensationOrder,
        dynamic_adjustments: dynamicAdjustments,
    };

    if (!existingId) {
        payload.id = `cwt-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        payload.is_default = false;
    }

    const token = localStorage.getItem('tda_auth_token');
    const url = existingId
        ? `/api/v1/context-window-types/${existingId}`
        : '/api/v1/context-window-types';
    const method = existingId ? 'PUT' : 'POST';

    try {
        const response = await fetch(url, {
            method,
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            modal.remove();
            await loadContextWindowTypes();
            renderContextWindowTypes();
            showNotification('success', `Context window type ${existingId ? 'updated' : 'created'} successfully`);
        } else {
            const err = await response.json();
            errorDiv.textContent = err.message || 'Failed to save';
            errorDiv.classList.remove('hidden');
        }
    } catch (err) {
        errorDiv.textContent = err.message || 'Network error';
        errorDiv.classList.remove('hidden');
    }
}

// ---------------------------------------------------------------------------
// Duplicate
// ---------------------------------------------------------------------------

async function duplicateContextWindowType(typeId) {
    const original = contextWindowTypes.find(t => t.id === typeId);
    if (!original) return;

    const duplicate = JSON.parse(JSON.stringify(original));
    duplicate.id = `cwt-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    duplicate.name = `${original.name} (Copy)`;
    duplicate.is_default = false;

    const token = localStorage.getItem('tda_auth_token');
    try {
        const response = await fetch('/api/v1/context-window-types', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(duplicate)
        });

        if (response.ok) {
            await loadContextWindowTypes();
            renderContextWindowTypes();
            showNotification('success', `Duplicated "${original.name}"`);
        } else {
            const err = await response.json();
            showNotification('error', err.message || 'Failed to duplicate');
        }
    } catch (err) {
        showNotification('error', err.message || 'Network error');
    }
}

// ---------------------------------------------------------------------------
// Delete
// ---------------------------------------------------------------------------

async function deleteContextWindowType(typeId) {
    const cwt = contextWindowTypes.find(t => t.id === typeId);
    if (!cwt) return;

    showConfirmation(
        'Delete Context Window Type',
        `Are you sure you want to delete "${escapeHtml(cwt.name)}"? Profiles using this type will fall back to the default.`,
        async () => {
            const token = localStorage.getItem('tda_auth_token');
            try {
                const response = await fetch(`/api/v1/context-window-types/${typeId}`, {
                    method: 'DELETE',
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (response.ok) {
                    contextWindowTypes = contextWindowTypes.filter(t => t.id !== typeId);
                    renderContextWindowTypes();
                    showNotification('success', `Deleted "${cwt.name}"`);
                } else {
                    const err = await response.json();
                    showNotification('error', err.message || 'Failed to delete');
                }
            } catch (err) {
                showNotification('error', err.message || 'Network error');
            }
        }
    );
}

// ---------------------------------------------------------------------------
// Profile dropdown helper
// ---------------------------------------------------------------------------

/**
 * Populate a <select> element with context window type options.
 * Call this when rendering the profile create/edit modal.
 */
export function populateContextWindowTypeDropdown(selectElement, selectedId) {
    if (!selectElement) return;

    selectElement.innerHTML = contextWindowTypes
        .map(cwt => {
            const isSelected = cwt.id === selectedId;
            const defaultLabel = cwt.is_default ? ' (Default)' : '';
            return `<option value="${cwt.id}" ${isSelected ? 'selected' : ''}>${escapeHtml(cwt.name)}${defaultLabel}</option>`;
        })
        .join('');
}

// ---------------------------------------------------------------------------
// Utilization Analytics (P5)
// ---------------------------------------------------------------------------

async function loadAnalyticsSessions() {
    const select = document.getElementById('cw-analytics-session-select');
    if (!select) return;

    const token = localStorage.getItem('tda_auth_token');
    try {
        const res = await fetch('/api/v1/sessions?limit=50', {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!res.ok) return;
        const data = await res.json();
        const sessions = data.sessions || [];

        select.innerHTML = '<option value="">Select a session...</option>' +
            sessions.map(s => {
                const name = s.name || s.id?.slice(0, 12) || 'Untitled';
                return `<option value="${s.id}">${escapeHtml(name)}</option>`;
            }).join('');

        select.addEventListener('change', () => {
            if (select.value) loadSessionContextAnalytics(select.value);
        });
    } catch (err) {
        console.error('Failed to load analytics sessions:', err);
    }
}

async function loadSessionContextAnalytics(sessionId) {
    const container = document.getElementById('cw-analytics-content');
    if (!container) return;

    container.innerHTML = '<p class="text-sm text-gray-400">Loading analytics...</p>';

    const token = localStorage.getItem('tda_auth_token');
    try {
        const res = await fetch(`/api/v1/sessions/${sessionId}/context-analytics`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (!res.ok) {
            container.innerHTML = '<p class="text-sm text-red-400">Failed to load analytics.</p>';
            return;
        }
        const data = await res.json();
        renderContextAnalytics(container, data);
    } catch (err) {
        container.innerHTML = `<p class="text-sm text-red-400">Error: ${escapeHtml(err.message)}</p>`;
    }
}

export function renderContextAnalytics(container, data) {
    const { turns, aggregates, context_window_type } = data;

    if (!turns || turns.length === 0) {
        container.innerHTML = '<p class="text-sm text-gray-500">No context window data available for this session. Run queries with the context window manager enabled to see analytics.</p>';
        return;
    }

    const typeName = context_window_type?.name || 'Unknown';

    // --- Section A: Summary Cards ---
    const utilColor = aggregates.avg_utilization_pct > 80 ? 'text-red-400' :
                      aggregates.avg_utilization_pct > 50 ? 'text-yellow-400' : 'text-emerald-400';
    const peakColor = aggregates.max_utilization_pct > 80 ? 'text-red-400' :
                      aggregates.max_utilization_pct > 50 ? 'text-yellow-400' : 'text-emerald-400';

    const summaryCards = `
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <div class="bg-white/5 border border-white/10 rounded-lg p-4 text-center">
                <div class="text-2xl font-bold ${utilColor}">${aggregates.avg_utilization_pct}%</div>
                <div class="text-xs text-gray-400 mt-1">Avg Utilization</div>
            </div>
            <div class="bg-white/5 border border-white/10 rounded-lg p-4 text-center">
                <div class="text-2xl font-bold ${peakColor}">${aggregates.max_utilization_pct}%</div>
                <div class="text-xs text-gray-400 mt-1">Peak Utilization</div>
            </div>
            <div class="bg-white/5 border border-white/10 rounded-lg p-4 text-center">
                <div class="text-2xl font-bold text-white">${aggregates.total_condensations}</div>
                <div class="text-xs text-gray-400 mt-1">Condensations</div>
            </div>
            <div class="bg-white/5 border border-white/10 rounded-lg p-4 text-center">
                <div class="text-2xl font-bold text-white">${turns.length}</div>
                <div class="text-xs text-gray-400 mt-1">Turns Analyzed</div>
            </div>
        </div>`;

    // --- Section B: Utilization Over Turns (stacked bar chart) ---
    const barsHTML = renderUtilizationBars(turns);

    // --- Section C: Module Utilization Table ---
    const tableHTML = renderModuleUtilizationTable(aggregates);

    // --- Section D: Adjustments & Condensation Log ---
    const logHTML = renderAdjustmentLog(aggregates);

    container.innerHTML = `
        <div class="mb-3">
            <span class="text-xs text-gray-500">Context Window Type:</span>
            <span class="text-xs text-white font-medium ml-1">${escapeHtml(typeName)}</span>
        </div>
        ${summaryCards}
        <div class="mb-6">
            <h4 class="text-sm font-semibold text-gray-300 mb-3">Utilization Per Turn</h4>
            ${barsHTML}
        </div>
        <div class="mb-6">
            <h4 class="text-sm font-semibold text-gray-300 mb-3">Module Utilization Summary</h4>
            ${tableHTML}
        </div>
        ${logHTML}`;
}

export function renderUtilizationBars(turns) {
    if (turns.length === 0) return '';

    // Normalize bars relative to the peak turn so even low-utilization sessions
    // produce visible bars (the tallest turn fills the container height).
    const maxUsed = Math.max(...turns.map(t => t.budget.used || 0), 1);

    const bars = turns.map(t => {
        const modules = t.modules || [];
        const totalUsed = t.budget.used || 0;
        const available = t.budget.available || 1;
        const utilPct = t.budget.utilization_pct || 0;

        // Scale the overall bar height relative to the peak turn
        const barHeightPct = (totalUsed / maxUsed) * 100;

        // Build module segments — each proportional to its share of this turn's usage
        const segments = modules
            .filter(m => m.used > 0)
            .sort((a, b) => (b.used || 0) - (a.used || 0))
            .map(m => {
                const segPct = totalUsed > 0 ? (m.used / totalUsed) * barHeightPct : 0;
                const color = getModuleColor(m.module_id);
                const allocK = m.allocated ? `${(m.allocated / 1000).toFixed(1)}K alloc` : '';
                const utilStr = m.utilization_pct != null ? ` · ${m.utilization_pct.toFixed(0)}% util` : '';
                const condensedStr = m.condensed ? ' · condensed' : '';
                const segTitle = `${m.module_id}: ${(m.used / 1000).toFixed(1)}K used${allocK ? ` / ${allocK}` : ''}${utilStr}${condensedStr}`;
                return `<div style="height:${Math.max(segPct, 1)}%;background:${color}" title="${segTitle}"></div>`;
            }).join('');

        return `
            <div class="flex-1 flex flex-col-reverse min-w-[16px] h-full" title="Turn ${t.turn_number}: ${utilPct}% (${(totalUsed / 1000).toFixed(1)}K/${(available / 1000).toFixed(0)}K)">
                ${segments}
            </div>`;
    }).join('');

    // Y-axis label showing the peak value
    const peakK = (maxUsed / 1000).toFixed(1);

    const turnLabels = turns.map(t =>
        `<div class="flex-1 text-center text-xs text-gray-500 min-w-[16px]">${t.turn_number}</div>`
    ).join('');

    return `
        <div class="bg-white/5 rounded-lg p-3">
            <div class="flex gap-0.5 h-36 mb-1 relative">
                <div class="absolute top-0 right-1 text-[10px] text-gray-500">${peakK}K</div>
                ${bars}
            </div>
            <div class="flex gap-0.5">
                ${turnLabels}
            </div>
        </div>`;
}

export function renderModuleUtilizationTable(aggregates) {
    const modUtil = aggregates.module_avg_utilization || {};
    const modCond = aggregates.module_condensation_count || {};
    const modMeta = aggregates.module_metadata || {};

    const entries = Object.entries(modUtil)
        .sort((a, b) => b[1] - a[1]);

    if (entries.length === 0) return '<p class="text-xs text-gray-500">No module data.</p>';

    const rows = entries.map(([mid, avgUtil]) => {
        const condensed = modCond[mid] || 0;
        const color = getModuleColor(mid);
        const utilClass = avgUtil > 80 ? 'text-yellow-400' : avgUtil < 10 ? 'text-gray-500' : 'text-white';

        // Build insights from module metadata
        const meta = modMeta[mid] || {};
        const insights = [];
        if (meta.mode?.frequency) {
            const freqs = Object.entries(meta.mode.frequency);
            insights.push(freqs.map(([k, v]) => `${k}: ${v}x`).join(', '));
        }
        if (meta.tool_count?.avg != null) {
            insights.push(`${meta.tool_count.avg} tools avg`);
        }
        if (meta.turn_count?.avg != null) {
            insights.push(`${meta.turn_count.avg} turns avg`);
        }
        if (meta.component_count?.avg != null) {
            insights.push(`${meta.component_count.avg} components avg`);
        }
        const insightText = insights.length > 0
            ? `<span class="text-[10px] text-gray-500">${escapeHtml(insights.join(' · '))}</span>`
            : '';

        return `
            <tr class="border-b border-white/5">
                <td class="py-1.5 px-2">
                    <div class="flex items-center gap-2">
                        <div class="w-2.5 h-2.5 rounded-sm flex-shrink-0" style="background:${color}"></div>
                        <div>
                            <span class="text-xs text-gray-300">${escapeHtml(mid)}</span>
                            ${insightText ? `<div>${insightText}</div>` : ''}
                        </div>
                    </div>
                </td>
                <td class="py-1.5 px-2 text-xs ${utilClass} text-right">${avgUtil}%</td>
                <td class="py-1.5 px-2 text-xs text-gray-400 text-right">${condensed}</td>
            </tr>`;
    }).join('');

    return `
        <div class="bg-white/5 rounded-lg overflow-hidden">
            <table class="w-full">
                <thead>
                    <tr class="border-b border-white/10">
                        <th class="py-1.5 px-2 text-left text-xs text-gray-500 font-medium">Module</th>
                        <th class="py-1.5 px-2 text-right text-xs text-gray-500 font-medium">Avg Util %</th>
                        <th class="py-1.5 px-2 text-right text-xs text-gray-500 font-medium">Condensed</th>
                    </tr>
                </thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
}

export function renderAdjustmentLog(aggregates) {
    const freq = aggregates.adjustment_frequency || {};
    const entries = Object.entries(freq);

    if (entries.length === 0) return '';

    const items = entries
        .sort((a, b) => b[1] - a[1])
        .map(([condition, count]) => {
            const label = ADJUSTMENT_CONDITIONS.find(c => c.value === condition)?.label || condition;
            return `<span class="text-xs px-2 py-1 rounded bg-white/5 text-gray-300">${escapeHtml(label)}: <span class="text-white font-medium">${count}x</span></span>`;
        }).join('');

    return `
        <div>
            <h4 class="text-sm font-semibold text-gray-300 mb-2">Dynamic Adjustments Fired</h4>
            <div class="flex flex-wrap gap-2">${items}</div>
        </div>`;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

export function initContextWindowTab() {
    const addBtn = document.getElementById('add-context-window-type-btn');
    if (addBtn) {
        addBtn.addEventListener('click', () => showContextWindowTypeModal());
    }

    renderContextWindowTypes();
    renderInstalledModules();
    loadAnalyticsSessions();
}

// ---------------------------------------------------------------------------
// Budget summary bar
// ---------------------------------------------------------------------------

function updateBudgetSummary(modal) {
    const bar = modal.querySelector('#cwt-budget-bar');
    const text = modal.querySelector('#cwt-budget-text');
    if (!bar || !text) return;

    const reserve = parseInt(modal.querySelector('#cwt-modal-reserve')?.value) || 12;
    let total = 0;
    const segments = [];

    modal.querySelectorAll('#cwt-modal-modules [data-module-id]').forEach(row => {
        const active = row.querySelector('.cwt-module-active')?.checked;
        if (!active) return;
        const moduleId = row.dataset.moduleId;
        const pct = parseInt(row.querySelector('.cwt-module-target')?.value) || 0;
        total += pct;
        if (pct > 0) {
            segments.push(`<div class="h-full rounded-sm" style="width:${pct}%;background:${getModuleColor(moduleId)}" title="${moduleId}: ${pct}%"></div>`);
        }
    });

    bar.innerHTML = segments.join('');
    const available = 100 - reserve;
    const overBudget = total > available;
    text.innerHTML = `Total: <span class="${overBudget ? 'text-red-400 font-semibold' : 'text-white'}">${total}%</span> / ${available}% available (${reserve}% reserved)`;
}

// ---------------------------------------------------------------------------
// Condensation order
// ---------------------------------------------------------------------------

function buildCondensationOrderSection(allModules, existing) {
    // Determine order: use existing condensation_order if editing, else priority ascending
    const existingOrder = existing?.condensation_order || [];
    const activeModuleIds = allModules
        .filter(mod => {
            const cfg = existing?.modules?.[mod.module_id];
            return cfg ? cfg.active : true;
        })
        .map(mod => mod.module_id);

    // Build ordered list: start with existingOrder entries that are active, then append any new active modules
    const ordered = [];
    for (const id of existingOrder) {
        if (activeModuleIds.includes(id)) ordered.push(id);
    }
    for (const id of activeModuleIds) {
        if (!ordered.includes(id)) ordered.push(id);
    }

    return ordered.map((id, i) => {
        const mod = allModules.find(m => m.module_id === id);
        const name = mod?.display_name || id;
        const color = getModuleColor(id);
        return `
            <div class="flex items-center gap-2 py-1 px-2 rounded bg-white/5" data-cond-module-id="${id}">
                <span class="text-xs text-gray-500 w-5 text-right">${i + 1}.</span>
                <div class="w-2.5 h-2.5 rounded-sm flex-shrink-0" style="background:${color}"></div>
                <span class="text-xs text-gray-300 flex-1">${escapeHtml(name)}</span>
                <button type="button" data-cond-dir="up" class="text-xs text-gray-500 hover:text-white px-1 ${i === 0 ? 'invisible' : ''}" title="Move up">&uarr;</button>
                <button type="button" data-cond-dir="down" class="text-xs text-gray-500 hover:text-white px-1 ${i === ordered.length - 1 ? 'invisible' : ''}" title="Move down">&darr;</button>
            </div>`;
    }).join('');
}

function rebuildCondensationOrder(modal) {
    const list = modal.querySelector('#cwt-condensation-list');
    if (!list) return;

    // Get currently active module IDs from the modules section
    const activeIds = [];
    modal.querySelectorAll('#cwt-modal-modules [data-module-id]').forEach(row => {
        if (row.querySelector('.cwt-module-active')?.checked) {
            activeIds.push(row.dataset.moduleId);
        }
    });

    // Preserve existing order for modules still active
    const currentOrder = [];
    list.querySelectorAll('[data-cond-module-id]').forEach(el => {
        const id = el.dataset.condModuleId;
        if (activeIds.includes(id)) currentOrder.push(id);
    });
    // Append newly activated modules at end
    for (const id of activeIds) {
        if (!currentOrder.includes(id)) currentOrder.push(id);
    }

    const allMods = installedModules.length > 0 ? installedModules : [];
    list.innerHTML = currentOrder.map((id, i) => {
        const mod = allMods.find(m => m.module_id === id);
        const name = mod?.display_name || id;
        const color = getModuleColor(id);
        return `
            <div class="flex items-center gap-2 py-1 px-2 rounded bg-white/5" data-cond-module-id="${id}">
                <span class="text-xs text-gray-500 w-5 text-right">${i + 1}.</span>
                <div class="w-2.5 h-2.5 rounded-sm flex-shrink-0" style="background:${color}"></div>
                <span class="text-xs text-gray-300 flex-1">${escapeHtml(name)}</span>
                <button type="button" data-cond-dir="up" class="text-xs text-gray-500 hover:text-white px-1 ${i === 0 ? 'invisible' : ''}" title="Move up">&uarr;</button>
                <button type="button" data-cond-dir="down" class="text-xs text-gray-500 hover:text-white px-1 ${i === currentOrder.length - 1 ? 'invisible' : ''}" title="Move down">&darr;</button>
            </div>`;
    }).join('');
}

function moveCondensationItem(btn) {
    const dir = btn.dataset.condDir;
    const item = btn.closest('[data-cond-module-id]');
    const list = item?.parentElement;
    if (!item || !list) return;

    if (dir === 'up' && item.previousElementSibling) {
        list.insertBefore(item, item.previousElementSibling);
    } else if (dir === 'down' && item.nextElementSibling) {
        list.insertBefore(item.nextElementSibling, item);
    }

    // Renumber and update arrow visibility
    const items = list.querySelectorAll('[data-cond-module-id]');
    items.forEach((el, i) => {
        el.querySelector('.text-gray-500.w-5').textContent = `${i + 1}.`;
        const upBtn = el.querySelector('[data-cond-dir="up"]');
        const downBtn = el.querySelector('[data-cond-dir="down"]');
        upBtn?.classList.toggle('invisible', i === 0);
        downBtn?.classList.toggle('invisible', i === items.length - 1);
    });
}

// ---------------------------------------------------------------------------
// Dynamic adjustments editor
// ---------------------------------------------------------------------------

const ADJUSTMENT_CONDITIONS = [
    { value: 'first_turn', label: 'First Turn' },
    { value: 'no_documents_attached', label: 'No Documents' },
    { value: 'long_conversation', label: 'Long Conversation' },
    { value: 'high_confidence_rag', label: 'High Confidence RAG' },
];

const ADJUSTMENT_ACTIONS = [
    { value: 'force_full', label: 'Force Full' },
    { value: 'transfer', label: 'Transfer' },
    { value: 'reduce', label: 'Reduce' },
    { value: 'condense', label: 'Condense' },
];

function buildDynamicAdjustmentsSection(existingRules, allModules) {
    if (!existingRules || existingRules.length === 0) {
        return '<p class="text-xs text-gray-500 italic">No rules configured. Click + Add Rule to add one.</p>';
    }
    return existingRules.map(rule => buildRuleRowHTML(rule, allModules)).join('');
}

function buildRuleRowHTML(rule, allModules) {
    const action = rule.action || {};
    let actionType = '', targetModule = '', toModule = '', byPct = 50;

    if (action.force_full) { actionType = 'force_full'; targetModule = action.force_full; }
    else if (action.transfer) { actionType = 'transfer'; targetModule = action.transfer; toModule = action.to || ''; }
    else if (action.reduce) { actionType = 'reduce'; targetModule = action.reduce; byPct = action.by_pct || 50; }
    else if (action.condense) { actionType = 'condense'; targetModule = action.condense; }

    const condOpts = ADJUSTMENT_CONDITIONS.map(c =>
        `<option value="${c.value}" ${c.value === rule.condition ? 'selected' : ''}>${c.label}</option>`
    ).join('');

    const actOpts = ADJUSTMENT_ACTIONS.map(a =>
        `<option value="${a.value}" ${a.value === actionType ? 'selected' : ''}>${a.label}</option>`
    ).join('');

    const modOpts = allModules.map(m =>
        `<option value="${m.module_id}" ${m.module_id === targetModule ? 'selected' : ''}>${escapeHtml(m.display_name)}</option>`
    ).join('');

    const toModOpts = allModules.map(m =>
        `<option value="${m.module_id}" ${m.module_id === toModule ? 'selected' : ''}>${escapeHtml(m.display_name)}</option>`
    ).join('');

    const showTransfer = actionType === 'transfer' ? '' : 'hidden';
    const showReduce = actionType === 'reduce' ? '' : 'hidden';

    return `
        <div class="cwt-rule-row flex items-center gap-2 py-2 px-3 rounded-lg bg-white/5 border border-white/10">
            <select class="cwt-rule-condition text-xs p-1 bg-gray-700 border border-gray-600 rounded text-white">${condOpts}</select>
            <span class="text-xs text-gray-500">&rarr;</span>
            <select class="cwt-rule-action-type text-xs p-1 bg-gray-700 border border-gray-600 rounded text-white">${actOpts}</select>
            <select class="cwt-rule-target-module text-xs p-1 bg-gray-700 border border-gray-600 rounded text-white">${modOpts}</select>
            <select class="cwt-rule-to-module text-xs p-1 bg-gray-700 border border-gray-600 rounded text-white ${showTransfer}" title="Transfer to">${toModOpts}</select>
            <div class="cwt-rule-reduce-pct flex items-center gap-1 ${showReduce}">
                <input type="number" class="cwt-rule-by-pct w-12 text-xs p-1 bg-gray-700 border border-gray-600 rounded text-center text-white" value="${byPct}" min="1" max="100">
                <span class="text-xs text-gray-500">%</span>
            </div>
            <button type="button" class="cwt-rule-delete text-xs text-red-400 hover:text-red-300 ml-auto px-1" title="Remove rule">&times;</button>
        </div>`;
}

function addDynamicAdjustmentRule(container, allModules) {
    if (!container) return;
    // Remove the "no rules" placeholder if present
    const placeholder = container.querySelector('p.italic');
    if (placeholder) placeholder.remove();

    const defaultRule = { condition: 'first_turn', action: { force_full: 'tool_definitions' } };
    container.insertAdjacentHTML('beforeend', buildRuleRowHTML(defaultRule, allModules));
}

function onActionTypeChange(ruleRow) {
    if (!ruleRow) return;
    const actionType = ruleRow.querySelector('.cwt-rule-action-type')?.value;
    const toSelect = ruleRow.querySelector('.cwt-rule-to-module');
    const reducePct = ruleRow.querySelector('.cwt-rule-reduce-pct');

    toSelect?.classList.toggle('hidden', actionType !== 'transfer');
    reducePct?.classList.toggle('hidden', actionType !== 'reduce');
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MODULE_COLORS = {
    system_prompt: '#6366f1',         // Indigo
    tool_definitions: '#f59e0b',      // Amber
    conversation_history: '#10b981',  // Emerald
    rag_context: '#3b82f6',           // Blue
    knowledge_context: '#8b5cf6',     // Violet
    plan_hydration: '#ec4899',        // Pink
    document_context: '#14b8a6',      // Teal
    component_instructions: '#f97316', // Orange
    workflow_history: '#64748b',       // Slate
};

function getModuleColor(moduleId) {
    return MODULE_COLORS[moduleId] || '#6b7280';
}
