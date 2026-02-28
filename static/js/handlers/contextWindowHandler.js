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
            <div class="flex items-center gap-3 py-2 px-3 rounded-lg bg-white/5 border border-white/10" data-module-id="${mod.module_id}">
                <input type="checkbox" class="cwt-module-active rounded" ${active ? 'checked' : ''} ${isRequired ? 'disabled checked' : ''}>
                <div class="w-3 h-3 rounded-sm flex-shrink-0" style="background:${color}"></div>
                <span class="text-sm text-white flex-shrink-0 w-40 truncate" title="${mod.display_name}">${escapeHtml(mod.display_name)}</span>
                ${isRequired ? '<span class="text-xs text-blue-400">Required</span>' : ''}
                <div class="flex items-center gap-2 ml-auto">
                    <label class="text-xs text-gray-400">Target:</label>
                    <input type="number" class="cwt-module-target w-12 text-xs p-1 bg-gray-700 border border-gray-600 rounded text-center text-white" value="${targetPct}" min="${minPct}" max="${maxPct}">
                    <span class="text-xs text-gray-500">%</span>
                    <label class="text-xs text-gray-400 ml-2">P:</label>
                    <input type="number" class="cwt-module-priority w-12 text-xs p-1 bg-gray-700 border border-gray-600 rounded text-center text-white" value="${priority}" min="1" max="100">
                </div>
            </div>`;
    }).join('');

    const modalHTML = `
        <div id="cwt-modal" class="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
            <div class="glass-panel rounded-xl p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
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
                        <label class="block text-sm font-medium text-gray-300 mb-3">Module Composition</label>
                        <div class="space-y-2" id="cwt-modal-modules">
                            ${moduleRows}
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
    const condensationOrder = [];
    modal.querySelectorAll('[data-module-id]').forEach(row => {
        const moduleId = row.dataset.moduleId;
        const active = row.querySelector('.cwt-module-active').checked;
        const targetPct = parseInt(row.querySelector('.cwt-module-target').value) || 0;
        const priority = parseInt(row.querySelector('.cwt-module-priority').value) || 50;

        // Use installed module defaults for min/max
        const modDef = installedModules.find(m => m.module_id === moduleId);
        const minPct = modDef?.defaults?.min_pct || 0;
        const maxPct = modDef?.defaults?.max_pct || 15;

        modules[moduleId] = { active, target_pct: targetPct, min_pct: minPct, max_pct: maxPct, priority };

        if (active) condensationOrder.push(moduleId);
    });

    // Sort condensation order by priority (lowest first)
    condensationOrder.sort((a, b) => (modules[a].priority || 0) - (modules[b].priority || 0));

    const payload = {
        name,
        description,
        output_reserve_pct: outputReservePct,
        modules,
        condensation_order: condensationOrder,
        dynamic_adjustments: existingId
            ? (contextWindowTypes.find(t => t.id === existingId)?.dynamic_adjustments || [])
            : [],
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
// Init
// ---------------------------------------------------------------------------

export function initContextWindowTab() {
    const addBtn = document.getElementById('add-context-window-type-btn');
    if (addBtn) {
        addBtn.addEventListener('click', () => showContextWindowTypeModal());
    }

    renderContextWindowTypes();
    renderInstalledModules();
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
