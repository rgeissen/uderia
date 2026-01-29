/**
 * utils.js
 * * This module contains utility and helper functions used across the application.
 * These functions perform common tasks like clipboard operations, chart rendering, and user privilege checks.
 */

import { state } from './state.js';
import { promptEditorStatus } from './domElements.js';

export function isPrivilegedUser() {
    // ... (no changes in this function) ...
    const privilegedTiers = ['Prompt Engineer', 'Enterprise'];
    const userTier = state.appConfig.license_info?.tier;
    return privilegedTiers.includes(userTier);
}

export function getSystemPrompts() {
    // ... (no changes in this function) ...
    if (!isPrivilegedUser()) return {};

    try {
        const prompts = localStorage.getItem('userSystemPrompts');
        return prompts ? JSON.parse(prompts) : {};
    } catch (e) {
        console.error("Could not parse system prompts from localStorage", e);
        return {};
    }
}

export function getNormalizedModelId(modelId) {
    // ... (no changes in this function) ...
    if (!modelId) return '';
    if (modelId.startsWith('arn:aws:bedrock:')) {
        const parts = modelId.split('/');
        const modelPart = parts[parts.length - 1];
        return modelPart.replace(/^(eu|us|apac)\./, '');
    }
    return modelId;
}

export function getPromptStorageKey(provider, model) {
    // ... (no changes in this function) ...
    const normalizedModel = getNormalizedModelId(model);
    return `${provider}-${normalizedModel}`;
}

export function saveSystemPromptForModel(provider, model, promptText, isCustom) {
    // ... (no changes in this function) ...
    if (!isPrivilegedUser()) return;

    const prompts = getSystemPrompts();
    const key = getPromptStorageKey(provider, model);
    prompts[key] = { prompt: promptText, isCustom: isCustom };
    localStorage.setItem('userSystemPrompts', JSON.stringify(prompts));
}

export function getSystemPromptForModel(provider, model) {
    // ... (no changes in this function) ...
    if (!isPrivilegedUser()) return null;

    const prompts = getSystemPrompts();
    const key = getPromptStorageKey(provider, model);
    return prompts[key]?.prompt || null;
}

export function isPromptCustomForModel(provider, model) {
    // ... (no changes in this function) ...
    if (!isPrivilegedUser()) return false;

    const prompts = getSystemPrompts();
    const key = getPromptStorageKey(provider, model);
    return prompts[key]?.isCustom || false;
}

export async function getDefaultSystemPrompt(provider, model) {
    // ... (no changes in this function) ...
    if (!isPrivilegedUser()) return null;

    const key = getPromptStorageKey(provider, model);
    if (state.defaultPromptsCache[key]) {
        return state.defaultPromptsCache[key];
    }

    try {
        const token = localStorage.getItem('tda_auth_token');
        const res = await fetch(`/system_prompt/${provider}/${getNormalizedModelId(model)}`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        if (!res.ok) {
            throw new Error(`Failed to fetch default prompt: ${res.statusText}`);
        }
        const data = await res.json();
        if (data.system_prompt) {
            state.defaultPromptsCache[key] = data.system_prompt;
            return data.system_prompt;
        }
        throw new Error("Server response did not contain a system_prompt.");
    } catch (e) {
        console.error(`Error getting default system prompt for ${key}:`, e);
        promptEditorStatus.textContent = 'Error fetching default prompt.';
        promptEditorStatus.className = 'text-sm text-red-400';
        return null;
    }
}

/**
 * Copies text content from a code block associated with the clicked button
 * to the clipboard using the document.execCommand method for better
 * compatibility in restricted environments.
 * @param {HTMLButtonElement} button - The button element that was clicked.
 */
export function copyToClipboard(button) {
    // ... (no changes in this function) ...
    const codeBlock = button.closest('.sql-code-block')?.querySelector('code');
    if (!codeBlock) {
        console.error('Could not find code block to copy from.');
        return;
    }
    const textToCopy = codeBlock.innerText;

    const textarea = document.createElement('textarea');
    textarea.value = textToCopy;
    textarea.style.position = 'fixed'; // Prevent scrolling to bottom of page in MS Edge.
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    textarea.setSelectionRange(0, 99999); // For mobile devices

    let success = false;
    try {
        success = document.execCommand('copy');
        if (!success) {
            throw new Error('document.execCommand returned false');
        }
    } catch (err) {
        console.error('Fallback copy failed: ', err);
        // Optionally provide user feedback about the failure
        if (window.showAppBanner) {
            window.showAppBanner('Failed to copy text. Please try copying manually.', 'error');
        }
    }

    document.body.removeChild(textarea);

    if (success) {
        const originalContent = button.innerHTML;
        // Keep the SVG icon, just change the text
        const textNode = button.childNodes[button.childNodes.length - 1];
        if (textNode && textNode.nodeType === Node.TEXT_NODE) {
            textNode.textContent = ' Copied!';
        } else {
             button.textContent = 'Copied!'; // Fallback if structure changes
        }
        button.classList.add('copied');
        setTimeout(() => {
            button.innerHTML = originalContent; // Restore original HTML (including SVG)
            button.classList.remove('copied');
        }, 2000);
    }
}

/**
 * Copies table data (formatted as TSV) associated with the clicked button
 * to the clipboard using the document.execCommand method.
 * @param {HTMLButtonElement} button - The button element that was clicked.
 */
export function copyTableToClipboard(button) {
    // ... (no changes in this function) ...
    const dataStr = button.dataset.table;
    if (!dataStr) {
        console.error("No data-table attribute found on the button.");
        return;
    }

    let tsvContent = '';
    try {
        const data = JSON.parse(dataStr);
        if (!Array.isArray(data) || data.length === 0 || typeof data[0] !== 'object') {
            return;
        }

        const headers = Object.keys(data[0]);
        tsvContent = headers.join('\t') + '\n'; // Header row

        data.forEach(row => {
            const values = headers.map(header => {
                let value = row[header] === null || row[header] === undefined ? '' : String(row[header]);
                // Sanitize value for TSV: remove tabs and newlines within cells
                value = value.replace(/[\t\n\r]/g, ' ');
                return value;
            });
            tsvContent += values.join('\t') + '\n'; // Data row
        });

    } catch (e) {
        console.error("Failed to parse or process table data for copying:", e);
        if (window.showAppBanner) {
            window.showAppBanner('Failed to process table data for copying.', 'error');
        }
        return;
    }

    const textarea = document.createElement('textarea');
    textarea.value = tsvContent;
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    document.body.appendChild(textarea);
    textarea.select();
    textarea.setSelectionRange(0, 99999);

    let success = false;
    try {
        success = document.execCommand('copy');
         if (!success) {
            throw new Error('document.execCommand returned false');
        }
    } catch (err) {
        console.error('Fallback table copy failed: ', err);
        if (window.showAppBanner) {
            window.showAppBanner('Failed to copy table. Please try copying manually.', 'error');
        }
    }

    document.body.removeChild(textarea);

    if (success) {
        const originalContent = button.innerHTML;
        const textNode = button.childNodes[button.childNodes.length - 1];
         if (textNode && textNode.nodeType === Node.TEXT_NODE) {
            textNode.textContent = ' Copied!';
        } else {
             button.textContent = 'Copied!';
        }
        button.classList.add('copied');
        setTimeout(() => {
            button.innerHTML = originalContent;
            button.classList.remove('copied');
        }, 2000);
    }
}


export function renderChart(containerId, spec) {
    // ... (no changes in this function) ...
    try {
        const chartSpec = typeof spec === 'string' ? JSON.parse(spec) : spec;
        if (!chartSpec || !chartSpec.type || !chartSpec.options) {
             throw new Error("Invalid chart specification provided.");
        }
        if (typeof G2Plot === 'undefined' || !G2Plot[chartSpec.type]) {
             throw new Error(`Chart type "${chartSpec.type}" is not supported or G2Plot is not loaded.`);
        }
        const plot = new G2Plot[chartSpec.type](containerId, chartSpec.options);
        plot.render();
    } catch (e) {
        console.error("Failed to render chart:", e);
        const container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = `<div class="p-4 text-red-400">Error rendering chart: ${e.message}</div>`;
        }
    }
}


export function setupPanelToggle(button, panel, checkbox, collapseIcon, expandIcon, windowDefaults = {}) {
    // Generate a unique storage key based on panel ID
    const storageKey = panel.id ? `panelState_${panel.id}` : null;
    
    // Determine panel-specific settings from windowDefaults
    let panelVisible = true;
    let defaultMode = 'collapsed';
    let userCanToggle = true;
    
    if (panel.id === 'session-history-panel') {
        panelVisible = windowDefaults.session_history_visible !== false;
        defaultMode = windowDefaults.session_history_default_mode || 'collapsed';
        userCanToggle = windowDefaults.session_history_user_can_toggle !== false;
    } else if (panel.id === 'tool-header') {
        panelVisible = windowDefaults.resources_visible !== false;
        defaultMode = windowDefaults.resources_default_mode || 'collapsed';
        userCanToggle = windowDefaults.resources_user_can_toggle !== false;
    } else if (panel.id === 'status-window') {
        panelVisible = windowDefaults.status_visible !== false;
        defaultMode = windowDefaults.status_default_mode || 'collapsed';
        userCanToggle = windowDefaults.status_user_can_toggle !== false;
    }
    
    // If panel not visible, hide it completely and disable controls
    if (!panelVisible) {
        panel.style.display = 'none';
        if (button) button.style.display = 'none';
        if (checkbox) {
            const checkboxContainer = checkbox.closest('.toggle-container');
            if (checkboxContainer) checkboxContainer.style.display = 'none';
        }
        return; // Exit early
    }
    
    // Panel is visible - ensure it's shown (remove inline display:none)
    panel.style.display = 'block';

    // Determine icon behavior based on panel location
    // Status panel (right side): swapped icons (collapsed shows <<, expanded shows >>)
    // History (left) and Header (top): standard icons (collapsed shows >>/v, expanded shows <</^)
    const useSwappedIcons = panel.id === 'status-window';

    const toggle = (isOpen, saveState = true) => {
        const isCollapsed = !isOpen;
        panel.classList.toggle('collapsed', isCollapsed);

        // Get current icon elements (in case button was cloned)
        const currentCollapseIcon = collapseIcon?.id ? document.getElementById(collapseIcon.id) : collapseIcon;
        const currentExpandIcon = expandIcon?.id ? document.getElementById(expandIcon.id) : expandIcon;
        const currentCheckbox = checkbox?.id ? document.getElementById(checkbox.id) : checkbox;

        // Icon logic based on panel location
        if (useSwappedIcons) {
            // Status panel: collapsed shows collapse icon, expanded shows expand icon
            if (currentCollapseIcon) currentCollapseIcon.classList.toggle('hidden', !isCollapsed);
            if (currentExpandIcon) currentExpandIcon.classList.toggle('hidden', isCollapsed);
        } else {
            // History and Header panels: collapsed shows expand icon, expanded shows collapse icon
            if (currentCollapseIcon) currentCollapseIcon.classList.toggle('hidden', isCollapsed);
            if (currentExpandIcon) currentExpandIcon.classList.toggle('hidden', !isCollapsed);
        }
        if (currentCheckbox) currentCheckbox.checked = isOpen;
        
        // Save state to localStorage only if user can toggle
        if (saveState && storageKey && userCanToggle) {
            try {
                localStorage.setItem(storageKey, isOpen ? 'open' : 'collapsed');
            } catch (e) {
                console.warn('Failed to save panel state:', e);
            }
        }
    };

    // Apply initial panel state
    if (storageKey) {
        try {
            const defaultExpanded = defaultMode === 'expanded';
            
            if (userCanToggle) {
                // User can toggle - check for saved preference first
                const savedState = localStorage.getItem(storageKey);
                if (savedState !== null) {
                    // User has a saved preference - use it
                    const isOpen = savedState === 'open';
                    toggle(isOpen, false);
                } else {
                    // No saved preference - use admin default
                    toggle(defaultExpanded, false);
                }
            } else {
                // User cannot toggle - always use admin default and clear any saved state
                localStorage.removeItem(storageKey);
                toggle(defaultExpanded, false);
            }
        } catch (e) {
            console.warn('Failed to restore panel state:', e);
        }
    }

    // Configure controls based on userCanToggle
    if (!userCanToggle) {
        // Disable the toggle button and checkbox - panels are locked
        if (button) {
            button.style.display = 'none';
        }
        if (checkbox) {
            const checkboxContainer = checkbox.closest('.toggle-container');
            if (checkboxContainer) {
                checkboxContainer.style.display = 'none';
            }
        }
    } else {
        // Show controls and enable toggling
        if (button) {
            button.style.display = 'flex';  // Buttons are flex containers
            button.style.pointerEvents = 'auto';  // Ensure button is clickable
            button.style.cursor = 'pointer';  // Ensure cursor shows it's clickable
            button.disabled = false;  // Ensure button is not disabled
            
            // Remove any existing click listeners to prevent duplicates
            const newButton = button.cloneNode(true);
            if (button.parentNode) {
                button.parentNode.replaceChild(newButton, button);
            }
            // Note: Elements may not have parent nodes during initialization - this is expected
            
            
            // Add fresh event listener to the new button
            newButton.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                toggle(panel.classList.contains('collapsed'));
            });
        }
        if (checkbox) {
            const checkboxContainer = checkbox.closest('.toggle-container');
            if (checkboxContainer) {
                checkboxContainer.style.display = 'flex';
            }
            
            // Remove any existing change listeners and add fresh one
            const newCheckbox = checkbox.cloneNode(true);
            if (checkbox.parentNode) {
                checkbox.parentNode.replaceChild(newCheckbox, checkbox);
            }
            // Note: Elements may not have parent nodes during initialization - this is expected
            
            
            newCheckbox.addEventListener('change', () => toggle(newCheckbox.checked));
        }
    }
}

/**
 * Classifies a user's spoken confirmation as 'yes', 'no', or 'unknown'.
 * @param {string} text - The transcribed text from the user.
 * @returns {'yes' | 'no' | 'unknown'}
 */
export function classifyConfirmation(text) {
    // ... (no changes in this function) ...
    const affirmativeRegex = /\b(yes|yeah|yep|sure|ok|okay|please|do it|go ahead)\b/i;
    const negativeRegex = /\b(no|nope|don't|stop|cancel)\b/i;

    const lowerText = text.toLowerCase().trim();

    if (affirmativeRegex.test(lowerText)) {
        return 'yes';
    }
    if (negativeRegex.test(lowerText)) {
        return 'no';
    }
    return 'unknown';
}

// --- MODIFICATION START: Remove global assignments ---
// window.copyToClipboard = copyToClipboard; // REMOVED
// window.copyTableToClipboard = copyTableToClipboard; // REMOVED
// --- MODIFICATION END ---

