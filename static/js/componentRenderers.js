/**
 * Component Renderer Registry
 *
 * Maps component_id → renderer function for the Generative UI Component system.
 * Handles CDN dependency loading and dynamic renderer registration.
 *
 * Built-in renderers (like chart/renderChart) are pre-registered.
 * Third-party renderers are loaded dynamically from /v1/components/<id>/renderer.
 */

import { renderChart } from './utils.js';
import { renderCanvas } from '/api/v1/components/canvas/renderer';
import { renderKnowledgeGraph } from '/api/v1/components/knowledge_graph/renderer';

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

/** @type {Map<string, Function>} component_id → render function */
const _renderers = new Map();

/** @type {Set<string>} CDN URLs already loaded */
const _loadedDeps = new Set();

/** @type {Map<string, Promise>} CDN URLs currently loading */
const _loadingDeps = new Map();

// ---------------------------------------------------------------------------
// Built-in registration
// ---------------------------------------------------------------------------

// Chart uses the existing renderChart from utils.js (G2Plot already loaded via CDN in index.html)
_renderers.set('chart', renderChart);

// Canvas — interactive code/document workspace with CodeMirror 6
_renderers.set('canvas', renderCanvas);

// Knowledge Graph — D3.js force-directed graph visualization
_renderers.set('knowledge_graph', renderKnowledgeGraph);

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Render a component into a DOM container.
 *
 * @param {string} componentId - e.g., 'chart', 'code_editor'
 * @param {string} containerId - DOM element ID to render into
 * @param {object} payload - ComponentRenderPayload.spec from the backend
 * @returns {any} Return value from the renderer (e.g., G2Plot instance), or null
 */
export function renderComponent(componentId, containerId, payload) {
    const renderer = _renderers.get(componentId);
    if (!renderer) {
        console.warn(`[ComponentRenderers] No renderer registered for '${componentId}'`);
        const container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = `<div class="p-4 text-yellow-400 text-sm">Unknown component: ${componentId}</div>`;
        }
        return null;
    }

    try {
        return renderer(containerId, payload);
    } catch (err) {
        console.error(`[ComponentRenderers] Error rendering '${componentId}':`, err);
        const container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = `<div class="p-4 text-red-400 text-sm">Render error: ${err.message}</div>`;
        }
        return null;
    }
}

/**
 * Register a component renderer.
 *
 * @param {string} componentId
 * @param {Function} renderer - fn(containerId, payload) => any
 */
export function registerComponent(componentId, renderer) {
    _renderers.set(componentId, renderer);
}

/**
 * Check if a renderer is registered for a component.
 */
export function hasRenderer(componentId) {
    return _renderers.has(componentId);
}

/**
 * Load a CDN dependency and return a Promise that resolves when loaded.
 *
 * @param {string} url - CDN URL to load
 * @param {string} globalName - Expected global variable name (e.g., 'G2Plot')
 * @returns {Promise<void>}
 */
export function loadCDNDependency(url, globalName) {
    // Already loaded
    if (_loadedDeps.has(url) || (globalName && window[globalName])) {
        _loadedDeps.add(url);
        return Promise.resolve();
    }

    // Currently loading
    if (_loadingDeps.has(url)) {
        return _loadingDeps.get(url);
    }

    const promise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = url;
        script.async = true;
        script.onload = () => {
            _loadedDeps.add(url);
            _loadingDeps.delete(url);
            resolve();
        };
        script.onerror = () => {
            _loadingDeps.delete(url);
            reject(new Error(`Failed to load CDN: ${url}`));
        };
        document.head.appendChild(script);
    });

    _loadingDeps.set(url, promise);
    return promise;
}

/**
 * Dynamically register a third-party component from its manifest.
 * Loads CDN dependencies, then fetches and evaluates the renderer JS.
 *
 * @param {object} manifest - Frontend manifest object from GET /v1/components/manifest
 *   { component_id, renderer_file, renderer_export, cdn_dependencies }
 * @returns {Promise<void>}
 */
export async function registerFromManifest(manifest) {
    const { component_id, renderer_export, cdn_dependencies } = manifest;

    if (_renderers.has(component_id)) return; // Already registered

    // Load CDN dependencies first
    if (cdn_dependencies && cdn_dependencies.length > 0) {
        await Promise.all(
            cdn_dependencies.map(dep => loadCDNDependency(dep.url, dep.global))
        );
    }

    // Fetch the renderer JS module from the component API
    try {
        const module = await import(`/api/v1/components/${component_id}/renderer`);
        const renderer = module[renderer_export || 'default'];
        if (typeof renderer === 'function') {
            _renderers.set(component_id, renderer);
            console.log(`[ComponentRenderers] Registered '${component_id}' from manifest`);
        } else {
            console.error(`[ComponentRenderers] Export '${renderer_export}' not found in renderer for '${component_id}'`);
        }
    } catch (err) {
        console.error(`[ComponentRenderers] Failed to load renderer for '${component_id}':`, err);
    }
}
