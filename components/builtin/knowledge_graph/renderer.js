/**
 * Knowledge Graph Component Renderer
 *
 * Premium D3.js v7 force-directed graph visualization with progressive display:
 *   (A) Inline compact — small graph preview in chat message
 *   (B) Split screen  — side panel with full interactive graph + toolbar
 *   (C) Full screen   — graph takes over entire viewport
 *
 * Follows the Canvas component's display pattern.
 *
 * @param {string} containerId - DOM element ID to render into
 * @param {object|string} payload - ComponentRenderPayload.spec from backend
 *   Expected: { nodes, links, title, center_entity, depth, entity_type_colors }
 */

// ─── Default Colors (matches handler.py ENTITY_TYPE_COLORS) ───────────
// Hardcoded fallback ensures correct colors even if the backend dict
// is lost or truncated during JSON → HTML attribute → JSON round-trip.
const DEFAULT_ENTITY_COLORS = {
    database: '#3b82f6',         // blue
    table: '#22c55e',            // green
    column: '#a3e635',           // lime
    foreign_key: '#f59e0b',      // amber
    business_concept: '#8b5cf6', // violet
    taxonomy: '#ec4899',         // pink
    metric: '#06b6d4',           // cyan
    domain: '#f97316',           // orange
};

// ─── State ─────────────────────────────────────────────────────────────
let _stylesInjected = false;
let _isKGFullscreen = false;
let _activeSpec = null;  // Current spec displayed in split panel

// ─── Live Animation State ──────────────────────────────────────────────
let _graphState = null;          // D3 refs: { nodeGroups, linkGroup, linkLines, links, nodes, simulation, svg, g, zoom, defs, colors, width, height }
let _activeAnimations = new Map(); // nodeId -> { timeoutId }
let _userZoomOverride = false;   // Set when user manually pans/zooms; cleared on next event
let _autozoomDebounce = null;    // Timeout ID for debounced auto-zoom

// ─── Entry Point ────────────────────────────────────────────────────────

export function renderKnowledgeGraph(containerId, payload) {
    injectStyles();

    const spec = typeof payload === 'string' ? JSON.parse(payload) : payload;
    const container = document.getElementById(containerId);
    if (!container || !spec || !spec.nodes) return null;

    // If called from inside the split panel, render full
    if (containerId.startsWith('kg-split-')) {
        return renderKGFull(containerId, spec);
    }

    // Default: render compact inline preview
    return renderKGInlineCompact(container, spec);
}


// ═══════════════════════════════════════════════════════════════════════
// MODE A: Inline Compact Preview
// ═══════════════════════════════════════════════════════════════════════

function renderKGInlineCompact(container, spec) {
    container.innerHTML = '';
    const nodes = spec.nodes || [];
    const links = spec.links || [];
    const colors = { ...DEFAULT_ENTITY_COLORS, ...(spec.entity_type_colors || {}) };
    const title = spec.title || 'Knowledge Graph';

    const wrapper = document.createElement('div');
    wrapper.className = 'kg-inline-compact';

    // Header
    const header = document.createElement('div');
    header.className = 'kg-inline-compact-header';
    header.innerHTML = `
        <div class="kg-inline-compact-title">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0">
                <circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/>
                <line x1="12" y1="8" x2="5" y2="16"/><line x1="12" y1="8" x2="19" y2="16"/>
            </svg>
            <span>${_escapeHtml(title)}</span>
        </div>
        <span class="kg-inline-compact-badge">${nodes.length} nodes &middot; ${links.length} edges</span>
    `;
    wrapper.appendChild(header);

    // Mini graph preview
    const graphArea = document.createElement('div');
    graphArea.className = 'kg-inline-compact-graph';
    wrapper.appendChild(graphArea);

    // Render a simplified mini graph
    _renderMiniGraph(graphArea, spec);

    // Footer with "Open in Graph" button
    const footer = document.createElement('div');
    footer.className = 'kg-inline-compact-footer';

    const openBtn = document.createElement('button');
    openBtn.className = 'kg-inline-open-btn';
    openBtn.textContent = 'Open in Graph \u2192';
    openBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openKGSplitPanel(spec);
        openBtn.textContent = 'Expanded in side panel \u2192';
        openBtn.classList.add('kg-inline-open-btn--active');
    });
    footer.appendChild(openBtn);
    wrapper.appendChild(footer);

    container.appendChild(wrapper);
    return null;
}


function _renderMiniGraph(container, spec) {
    const nodes = JSON.parse(JSON.stringify(spec.nodes || []));
    const links = JSON.parse(JSON.stringify(spec.links || []));
    const colors = { ...DEFAULT_ENTITY_COLORS, ...(spec.entity_type_colors || {}) };

    if (nodes.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted, #6b7280);text-align:center;padding:2rem;font-size:13px">Empty graph</p>';
        return;
    }

    const fallbackColor = _themeColor('--text-muted', '#6b7280');
    const width = container.clientWidth || 500;
    const height = 200;

    const svg = d3.select(container)
        .append('svg')
        .attr('width', '100%')
        .attr('height', height)
        .attr('viewBox', `0 0 ${width} ${height}`)
        .style('font-family', "'Inter', system-ui, sans-serif");

    const g = svg.append('g');

    // Simple zoom (no controls)
    svg.call(d3.zoom().scaleExtent([0.3, 3]).on('zoom', (e) => g.attr('transform', e.transform)));

    // Force simulation (compact, fewer iterations)
    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(60))
        .force('charge', d3.forceManyBody().strength(-150))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(25))
        .alphaDecay(0.05);

    // Edges (simplified)
    const linkLines = g.selectAll('.kg-mini-link')
        .data(links)
        .join('line')
        .attr('class', 'kg-mini-link')
        .attr('stroke-width', 1)
        .attr('stroke-opacity', 0.4);

    // Nodes (simplified circles)
    const nodeCircles = g.selectAll('.kg-mini-node')
        .data(nodes)
        .join('circle')
        .attr('class', 'kg-mini-node')
        .attr('r', d => d.is_center ? 8 : 5 + (d.importance || 0) * 10)
        .attr('fill', d => colors[d.type] || fallbackColor)
        .attr('fill-opacity', 0.7)
        .attr('stroke', d => colors[d.type] || fallbackColor)
        .attr('stroke-width', d => d.is_center ? 2 : 1);

    // Labels for larger graphs only on center/important nodes
    if (nodes.length <= 20) {
        g.selectAll('.kg-mini-label')
            .data(nodes)
            .join('text')
            .attr('class', 'kg-mini-label')
            .text(d => d.name.length > 12 ? d.name.slice(0, 10) + '\u2026' : d.name)
            .attr('font-size', '8px')
            .attr('dx', 10)
            .attr('dy', 3)
            .style('pointer-events', 'none');
    }

    simulation.on('tick', () => {
        linkLines.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                 .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
        nodeCircles.attr('cx', d => d.x).attr('cy', d => d.y);
        g.selectAll('.kg-mini-label').attr('x', d => d.x).attr('y', d => d.y);
    });

    // Stop simulation after settling
    setTimeout(() => simulation.stop(), 3000);
}


// ═══════════════════════════════════════════════════════════════════════
// MODE B: Split Screen Panel
// ═══════════════════════════════════════════════════════════════════════

export function openKGSplitPanel(spec) {
    const panel = document.getElementById('kg-split-panel');
    if (!panel) return;

    // Mutual exclusion: close canvas split panel if open
    const canvasPanel = document.getElementById('canvas-split-panel');
    if (canvasPanel && canvasPanel.classList.contains('canvas-split--open')) {
        // Dispatch event for canvas to clean up its state
        window.dispatchEvent(new CustomEvent('kg-requesting-split', { detail: {} }));
        canvasPanel.classList.remove('canvas-split--open');
        setTimeout(() => {
            if (!canvasPanel.classList.contains('canvas-split--open')) {
                canvasPanel.style.display = 'none';
                const cc = document.getElementById('canvas-split-content');
                if (cc) cc.innerHTML = '';
            }
        }, 350);
    }

    _activeSpec = spec;

    // Update title
    const titleEl = document.getElementById('kg-split-title');
    if (titleEl) titleEl.textContent = spec.title || 'Knowledge Graph';

    // Clear previous content
    const contentArea = document.getElementById('kg-split-content');
    if (contentArea) contentArea.innerHTML = '';

    // Show panel with animation
    panel.style.display = 'flex';
    panel.offsetHeight; // Force reflow
    panel.classList.add('kg-split--open');

    // Create render target
    const renderTarget = document.createElement('div');
    renderTarget.id = `kg-split-render-${Date.now()}`;
    renderTarget.style.cssText = 'flex:1;display:flex;flex-direction:column;min-height:0;';
    contentArea.appendChild(renderTarget);

    // Render full graph into split panel
    renderKGFull(renderTarget.id, spec);

    // Wire up header buttons
    const fsBtn = document.getElementById('kg-split-fullscreen');
    if (fsBtn) fsBtn.onclick = toggleKGFullscreen;
    const closeBtn = document.getElementById('kg-split-close');
    if (closeBtn) closeBtn.onclick = closeKGSplitPanel;
}


export function closeKGSplitPanel() {
    const panel = document.getElementById('kg-split-panel');
    if (!panel) return;

    // Exit fullscreen if active
    if (_isKGFullscreen) {
        _isKGFullscreen = false;
        const mainArea = document.getElementById('main-content-area');
        if (mainArea) mainArea.classList.remove('kg-fullscreen');
        document.documentElement.style.removeProperty('--kg-fullscreen-top');
        _updateFullscreenIcon(false);
    }

    _activeSpec = null;
    _clearAllAnimations();
    _graphState = null;

    // Reset inline buttons
    document.querySelectorAll('.kg-inline-open-btn--active').forEach(btn => {
        btn.textContent = 'Open in Graph \u2192';
        btn.classList.remove('kg-inline-open-btn--active');
    });

    panel.classList.remove('kg-split--open');

    const onTransitionEnd = () => {
        panel.removeEventListener('transitionend', onTransitionEnd);
        if (!panel.classList.contains('kg-split--open')) {
            panel.style.display = 'none';
            const contentArea = document.getElementById('kg-split-content');
            if (contentArea) contentArea.innerHTML = '';
        }
    };
    panel.addEventListener('transitionend', onTransitionEnd);
}


// ═══════════════════════════════════════════════════════════════════════
// MODE C: Fullscreen
// ═══════════════════════════════════════════════════════════════════════

function toggleKGFullscreen() {
    const mainArea = document.getElementById('main-content-area');
    if (!mainArea) return;

    _isKGFullscreen = !_isKGFullscreen;

    if (_isKGFullscreen) {
        const topNav = document.querySelector('body > nav');
        const topOffset = topNav ? topNav.offsetHeight : 0;
        document.documentElement.style.setProperty('--kg-fullscreen-top', topOffset + 'px');
        mainArea.classList.add('kg-fullscreen');
    } else {
        mainArea.classList.remove('kg-fullscreen');
        document.documentElement.style.removeProperty('--kg-fullscreen-top');
    }

    _updateFullscreenIcon(_isKGFullscreen);
}


function _updateFullscreenIcon(isFullscreen) {
    const fsBtn = document.getElementById('kg-split-fullscreen');
    if (!fsBtn) return;
    fsBtn.title = isFullscreen ? 'Exit fullscreen' : 'Fullscreen graph';
    // The SVG already works for both states (expand arrows)
}


// ═══════════════════════════════════════════════════════════════════════
// FULL INTERACTIVE GRAPH (used by split panel and fullscreen)
// ═══════════════════════════════════════════════════════════════════════

function renderKGFull(containerId, spec) {
    const container = document.getElementById(containerId);
    if (!container || !spec || !spec.nodes) return null;

    // Clear any previous animation state (prevents stale refs when switching between split panel and inspect)
    _clearAllAnimations();

    container.innerHTML = '';
    container.style.display = 'flex';
    container.style.flexDirection = 'column';
    container.style.minHeight = '0';

    const nodes = JSON.parse(JSON.stringify(spec.nodes));
    const links = JSON.parse(JSON.stringify(spec.links || []));
    const colors = { ...DEFAULT_ENTITY_COLORS, ...(spec.entity_type_colors || {}) };
    const title = spec.title || 'Knowledge Graph';

    if (nodes.length === 0) {
        container.innerHTML = '<p style="color:var(--text-muted, #9ca3af);text-align:center;padding:2rem">No entities in graph</p>';
        return null;
    }

    // ─── Toolbar ───────────────────────────────────────────────────
    const toolbar = _buildToolbar(nodes, links, colors);
    container.appendChild(toolbar);

    // ─── Graph Container ───────────────────────────────────────────
    const graphContainer = document.createElement('div');
    graphContainer.style.cssText = `flex:1;position:relative;background:var(--bg-secondary, rgba(0,0,0,0.3));border-radius:0 0 8px 8px;overflow:hidden;min-height:0;`;
    container.appendChild(graphContainer);

    // Wait for layout so dimensions are available
    requestAnimationFrame(() => {
        const width = graphContainer.clientWidth || 800;
        const height = graphContainer.clientHeight || 600;
        _renderFullGraph(graphContainer, nodes, links, colors, width, height, toolbar);
    });

    return { container };
}


function _buildToolbar(nodes, links, colors) {
    const toolbar = document.createElement('div');
    toolbar.className = 'kg-toolbar';

    // Direct callbacks — registered by _renderFullGraph (no CustomEvent needed)
    toolbar._onFilter = null;
    toolbar._onZoomFit = null;
    toolbar._onExportPNG = null;

    // ── Search ──
    const searchWrap = document.createElement('div');
    searchWrap.className = 'kg-toolbar-search';
    searchWrap.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0;opacity:0.5">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
    `;
    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.placeholder = 'Search entities...';
    searchInput.className = 'kg-toolbar-search-input';
    searchWrap.appendChild(searchInput);
    toolbar.appendChild(searchWrap);

    // ── Stats badge ──
    const stats = document.createElement('span');
    stats.className = 'kg-toolbar-stats';
    stats.textContent = `${nodes.length} nodes \u00b7 ${links.length} edges`;
    toolbar.appendChild(stats);

    // ── Spacer ──
    const spacer = document.createElement('div');
    spacer.style.flex = '1';
    toolbar.appendChild(spacer);

    // ── Filter pills ──
    const types = [...new Set(nodes.map(n => n.type))];
    if (types.length > 1) {
        const filterWrap = document.createElement('div');
        filterWrap.className = 'kg-toolbar-filters';

        const hiddenTypes = new Set();
        types.forEach(type => {
            const pill = document.createElement('button');
            pill.className = 'kg-toolbar-filter-pill';
            const typeColor = colors[type] || _themeColor('--text-muted', '#6b7280');
            pill.style.borderColor = typeColor + '60';
            pill.style.background = typeColor + '20';
            pill.style.color = typeColor;
            pill.textContent = type;
            pill.dataset.entityType = type;
            pill.addEventListener('click', () => {
                if (hiddenTypes.has(type)) {
                    hiddenTypes.delete(type);
                    pill.style.opacity = '1';
                } else {
                    hiddenTypes.add(type);
                    pill.style.opacity = '0.3';
                }
                // Direct callback — no DOM event propagation dependency
                if (toolbar._onFilter) toolbar._onFilter(hiddenTypes);
            });
            filterWrap.appendChild(pill);
        });
        toolbar.appendChild(filterWrap);
    }

    // ── Zoom fit button ──
    const fitBtn = _makeToolbarButton('\u229e', 'Zoom to fit');
    fitBtn.addEventListener('click', () => {
        if (toolbar._onZoomFit) toolbar._onZoomFit();
    });
    toolbar.appendChild(fitBtn);

    // ── Export PNG button ──
    const exportBtn = _makeToolbarButton('\u2913', 'Export as PNG');
    exportBtn.addEventListener('click', () => {
        if (toolbar._onExportPNG) toolbar._onExportPNG();
    });
    toolbar.appendChild(exportBtn);

    // Store search input ref for graph to wire up
    toolbar._searchInput = searchInput;

    return toolbar;
}


function _renderFullGraph(container, nodes, links, colors, width, height, toolbar) {
    const fallbackColor = _themeColor('--text-muted', '#6b7280');

    // ─── SVG Setup ───────────────────────────────────────────────────
    const svg = d3.select(container)
        .append('svg')
        .attr('width', '100%')
        .attr('height', '100%')
        .attr('viewBox', `0 0 ${width} ${height}`)
        .style('font-family', "'Inter', system-ui, sans-serif");

    // ─── Defs: Filters, Gradients, Markers ───────────────────────────
    const defs = svg.append('defs');

    // Drop shadow filter
    const shadow = defs.append('filter').attr('id', 'kg-shadow').attr('x', '-40%').attr('y', '-40%').attr('width', '180%').attr('height', '180%');
    shadow.append('feDropShadow').attr('dx', 0).attr('dy', 2).attr('stdDeviation', 4).attr('flood-color', 'rgba(0,0,0,0.5)');

    // Glow filter (per entity type)
    Object.entries(colors).forEach(([type, color]) => {
        const glow = defs.append('filter').attr('id', `kg-glow-${type}`).attr('x', '-50%').attr('y', '-50%').attr('width', '200%').attr('height', '200%');
        glow.append('feGaussianBlur').attr('in', 'SourceGraphic').attr('stdDeviation', 6).attr('result', 'blur');
        glow.append('feFlood').attr('flood-color', color).attr('flood-opacity', 0.4).attr('result', 'color');
        glow.append('feComposite').attr('in', 'color').attr('in2', 'blur').attr('operator', 'in').attr('result', 'glow');
        const merge = glow.append('feMerge');
        merge.append('feMergeNode').attr('in', 'glow');
        merge.append('feMergeNode').attr('in', 'SourceGraphic');
    });

    // Activity glow filter (warm amber — shared for live execution animations)
    const actGlow = defs.append('filter').attr('id', 'kg-activity-glow').attr('x', '-60%').attr('y', '-60%').attr('width', '220%').attr('height', '220%');
    actGlow.append('feGaussianBlur').attr('in', 'SourceGraphic').attr('stdDeviation', 8).attr('result', 'blur');
    actGlow.append('feFlood').attr('flood-color', '#F15F22').attr('flood-opacity', 0.5).attr('result', 'color');
    actGlow.append('feComposite').attr('in', 'color').attr('in2', 'blur').attr('operator', 'in').attr('result', 'glow');
    const actMerge = actGlow.append('feMerge');
    actMerge.append('feMergeNode').attr('in', 'glow');
    actMerge.append('feMergeNode').attr('in', 'SourceGraphic');

    // Pulse animation for center entity
    defs.append('style').text(`
        @keyframes kg-pulse { 0%, 100% { opacity: 0.6; } 50% { opacity: 0.15; } }
        .kg-center-ring { animation: kg-pulse 2s ease-in-out infinite; }
        .kg-node-label { pointer-events: none; user-select: none; }
        .kg-edge-label { pointer-events: none; user-select: none; }
    `);

    // Gradient for each link (source color -> target color)
    links.forEach((link, i) => {
        const sourceType = nodes[typeof link.source === 'object' ? link.source.index : link.source]?.type;
        const targetType = nodes[typeof link.target === 'object' ? link.target.index : link.target]?.type;
        const grad = defs.append('linearGradient').attr('id', `kg-grad-${i}`).attr('gradientUnits', 'userSpaceOnUse');
        grad.append('stop').attr('offset', '0%').attr('stop-color', colors[sourceType] || fallbackColor);
        grad.append('stop').attr('offset', '100%').attr('stop-color', colors[targetType] || fallbackColor);
    });

    // Arrowhead marker
    defs.append('marker')
        .attr('id', 'kg-arrow')
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 28).attr('refY', 0)
        .attr('markerWidth', 6).attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-4L8,0L0,4');

    // ─── Zoom ────────────────────────────────────────────────────────
    const g = svg.append('g');

    const zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => {
            g.attr('transform', event.transform);
            // Detect user-initiated zoom/pan (sourceEvent is truthy for mouse/touch)
            if (event.sourceEvent) _userZoomOverride = true;
        });
    svg.call(zoom);

    // ─── Force Simulation ────────────────────────────────────────────
    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(120))
        .force('charge', d3.forceManyBody().strength(-350))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collision', d3.forceCollide().radius(45));

    // ─── Edges ───────────────────────────────────────────────────────
    const linkGroup = g.selectAll('.kg-link')
        .data(links)
        .join('g')
        .attr('class', 'kg-link');

    linkGroup.append('line')
        .attr('stroke', (d, i) => `url(#kg-grad-${i})`)
        .attr('stroke-width', 1.5)
        .attr('stroke-opacity', 0.5)
        .attr('marker-end', 'url(#kg-arrow)')
        .attr('stroke-dasharray', function() { return this.getTotalLength ? this.getTotalLength() : 200; })
        .attr('stroke-dashoffset', function() { return this.getTotalLength ? this.getTotalLength() : 200; })
        .transition()
        .delay((d, i) => 300 + i * 30)
        .duration(600)
        .attr('stroke-dashoffset', 0);

    const linkLines = linkGroup.select('line');

    // Edge labels (fill + opacity via CSS .kg-edge-label for theme compliance)
    linkGroup.append('text')
        .attr('class', 'kg-edge-label')
        .text(d => d.type)
        .attr('font-size', '9px')
        .attr('text-anchor', 'middle')
        .attr('dy', -6);

    // ─── Nodes ───────────────────────────────────────────────────────
    const nodeGroup = g.selectAll('.kg-node')
        .data(nodes)
        .join('g')
        .attr('class', 'kg-node')
        .style('cursor', 'pointer')
        .style('opacity', 0)
        .transition()
        .delay((d, i) => i * 40)
        .duration(400)
        .style('opacity', 1);

    const nodeGroups = g.selectAll('.kg-node');

    // Center entity pulse ring
    nodeGroups.filter(d => d.is_center)
        .append('circle')
        .attr('class', 'kg-center-ring')
        .attr('r', 24)
        .attr('fill', 'none')
        .attr('stroke', d => colors[d.type] || fallbackColor)
        .attr('stroke-width', 2);

    // Node: rounded rectangle card
    const nodeW = 24, nodeH = 24;
    nodeGroups.append('rect')
        .attr('x', -nodeW / 2).attr('y', -nodeH / 2)
        .attr('width', nodeW).attr('height', nodeH)
        .attr('rx', 8).attr('ry', 8)
        .attr('fill', d => (colors[d.type] || fallbackColor) + '30')
        .attr('stroke', d => colors[d.type] || fallbackColor)
        .attr('stroke-width', 1.5)
        .attr('filter', 'url(#kg-shadow)');

    // Node: type indicator dot
    nodeGroups.append('circle')
        .attr('cx', 0).attr('cy', 0)
        .attr('r', d => 5 + (d.importance || 0) * 15)
        .attr('fill', d => colors[d.type] || fallbackColor);

    // Node: label (fill via CSS .kg-node-name for theme compliance)
    nodeGroups.append('text')
        .attr('class', 'kg-node-label kg-node-name')
        .text(d => d.name.length > 18 ? d.name.slice(0, 16) + '\u2026' : d.name)
        .attr('font-size', '11px')
        .attr('dx', nodeW / 2 + 6).attr('dy', 4)
        .attr('font-weight', d => d.is_center ? '600' : '400');

    // Node: type badge
    nodeGroups.append('text')
        .attr('class', 'kg-node-label')
        .text(d => d.type)
        .attr('font-size', '8px')
        .attr('fill', d => colors[d.type] || fallbackColor)
        .attr('dx', nodeW / 2 + 6).attr('dy', 16);

    // ─── Interaction: Hover Glow ─────────────────────────────────────
    nodeGroups
        .on('mouseenter', function(event, d) {
            d3.select(this).select('rect').attr('filter', `url(#kg-glow-${d.type})`);
            linkGroup.select('text').style('opacity', l => (l.source === d || l.target === d) ? 0.9 : 0.15);
            linkLines.attr('stroke-opacity', l => (l.source === d || l.target === d) ? 0.9 : 0.15);
        })
        .on('mouseleave', function() {
            d3.select(this).select('rect').attr('filter', 'url(#kg-shadow)');
            linkGroup.select('text').style('opacity', null);  // CSS controls base opacity
            linkLines.attr('stroke-opacity', 0.5);
        });

    // ─── Interaction: Click Focus ────────────────────────────────────
    let focusedNode = null;

    nodeGroups.on('click', function(event, d) {
        event.stopPropagation();
        if (focusedNode === d) {
            focusedNode = null;
            nodeGroups.style('opacity', 1);
            linkLines.attr('stroke-opacity', 0.5);
            linkGroup.select('text').style('opacity', null);
        } else {
            focusedNode = d;
            const connected = new Set([d.id]);
            links.forEach(l => {
                const sid = typeof l.source === 'object' ? l.source.id : l.source;
                const tid = typeof l.target === 'object' ? l.target.id : l.target;
                if (sid === d.id) connected.add(tid);
                if (tid === d.id) connected.add(sid);
            });
            nodeGroups.style('opacity', n => connected.has(n.id) ? 1 : 0.15);
            linkLines.attr('stroke-opacity', l => {
                const sid = typeof l.source === 'object' ? l.source.id : l.source;
                const tid = typeof l.target === 'object' ? l.target.id : l.target;
                return (sid === d.id || tid === d.id) ? 0.9 : 0.05;
            });
            linkGroup.select('text').style('opacity', l => {
                const sid = typeof l.source === 'object' ? l.source.id : l.source;
                const tid = typeof l.target === 'object' ? l.target.id : l.target;
                return (sid === d.id || tid === d.id) ? 0.9 : 0.05;
            });
        }
    });

    svg.on('click', () => {
        focusedNode = null;
        nodeGroups.style('opacity', 1);
        linkLines.attr('stroke-opacity', 0.5);
        linkGroup.select('text').style('opacity', null);
    });

    // ─── Interaction: Drag ───────────────────────────────────────────
    nodeGroups.call(d3.drag()
        .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null; d.fy = null;
        })
    );

    // ─── Tooltip ─────────────────────────────────────────────────────
    const tooltip = d3.select(container)
        .append('div')
        .attr('class', 'kg-tooltip');

    nodeGroups
        .on('mouseenter.tooltip', function(event, d) {
            const props = d.properties || {};
            const typeColor = colors[d.type] || '';
            let html = `<div style="font-weight:600;${typeColor ? `color:${typeColor}` : ''}">${_escapeHtml(d.name)}</div>`;
            html += `<div style="color:var(--text-muted, #9ca3af);font-size:11px;margin-bottom:4px">${_escapeHtml(d.type)}</div>`;
            if (props.description) html += `<div>${_escapeHtml(props.description)}</div>`;
            if (props.data_type) html += `<div style="color:var(--text-muted, #9ca3af)">Type: ${_escapeHtml(props.data_type)}</div>`;
            if (props.business_meaning) html += `<div style="color:#a78bfa">Business: ${_escapeHtml(props.business_meaning)}</div>`;
            tooltip.html(html).style('display', 'block');
        })
        .on('mousemove.tooltip', function(event) {
            const rect = container.getBoundingClientRect();
            tooltip
                .style('left', (event.clientX - rect.left + 12) + 'px')
                .style('top', (event.clientY - rect.top - 10) + 'px');
        })
        .on('mouseleave.tooltip', function() {
            tooltip.style('display', 'none');
        });

    // ─── Tick Update ─────────────────────────────────────────────────
    simulation.on('tick', () => {
        linkGroup.select('line')
            .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y);

        linkGroup.select('text')
            .attr('x', d => (d.source.x + d.target.x) / 2)
            .attr('y', d => (d.source.y + d.target.y) / 2);

        links.forEach((d, i) => {
            const grad = defs.select(`#kg-grad-${i}`);
            if (grad.size()) {
                grad.attr('x1', d.source.x).attr('y1', d.source.y)
                    .attr('x2', d.target.x).attr('y2', d.target.y);
            }
        });

        nodeGroups.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // ─── Legend (in-graph overlay) ────────────────────────────────────
    _renderLegend(container, colors, nodes);

    // ─── Toolbar Event Wiring (direct callbacks — no DOM events) ────
    // Search
    if (toolbar && toolbar._searchInput) {
        toolbar._searchInput.oninput = () => {
            const q = toolbar._searchInput.value.toLowerCase();
            if (!q) { nodeGroups.style('opacity', 1); return; }
            nodeGroups.style('opacity', d => d.name.toLowerCase().includes(q) ? 1 : 0.12);
        };
    }

    // Filter — direct callback from toolbar pills
    if (toolbar) {
        toolbar._onFilter = (hiddenTypes) => {
            nodeGroups.style('display', d => hiddenTypes.has(d.type) ? 'none' : null);
            g.selectAll('.kg-link').style('display', l => {
                const sType = (typeof l.source === 'object' ? l.source : nodes[l.source])?.type;
                const tType = (typeof l.target === 'object' ? l.target : nodes[l.target])?.type;
                return (hiddenTypes.has(sType) || hiddenTypes.has(tType)) ? 'none' : null;
            });
        };

        // Zoom fit
        toolbar._onZoomFit = () => {
            svg.transition().duration(500).call(
                zoom.transform,
                d3.zoomIdentity.translate(width / 2, height / 2).scale(0.8).translate(-width / 2, -height / 2)
            );
        };

        // Export PNG
        toolbar._onExportPNG = () => {
            _exportPNG(svg.node(), width, height);
        };
    }

    // Expose D3 state for live animation bridge
    _graphState = { nodeGroups, linkGroup, linkLines, links, nodes, simulation, svg, g, zoom, defs, colors, width, height };

    return { svg: svg.node(), simulation };
}


// ─── Legend (in-graph overlay) ──────────────────────────────────────────

function _renderLegend(container, colors, nodes) {
    const presentTypes = [...new Set(nodes.map(n => n.type))];
    if (presentTypes.length <= 1) return;

    const legend = document.createElement('div');
    legend.className = 'kg-legend';

    presentTypes.forEach(type => {
        const color = colors[type] || _themeColor('--text-muted', '#6b7280');
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;margin:2px 0;';
        row.innerHTML = `
            <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block"></span>
            <span style="color:var(--text-secondary, #d1d5db)">${_escapeHtml(type)}</span>
        `;
        legend.appendChild(row);
    });

    container.appendChild(legend);
}


// ─── Export PNG ──────────────────────────────────────────────────────────

function _exportPNG(svgNode, width, height) {
    const serializer = new XMLSerializer();
    const svgStr = serializer.serializeToString(svgNode);
    const svgBlob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);

    const img = new Image();
    img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = width * 2;
        canvas.height = height * 2;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = _themeColor('--bg-primary', '#0f172a');
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);

        canvas.toBlob(blob => {
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'knowledge-graph.png';
            a.click();
            URL.revokeObjectURL(a.href);
        }, 'image/png');
    };
    img.src = url;
}


// ─── Helpers ────────────────────────────────────────────────────────────

function _makeToolbarButton(label, title) {
    const btn = document.createElement('button');
    btn.className = 'kg-toolbar-btn';
    btn.textContent = label;
    btn.title = title;
    return btn;
}

function _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/** Read a CSS variable from the current theme (for D3 inline SVG attributes). */
function _themeColor(varName, fallback) {
    return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || fallback;
}


// ═══════════════════════════════════════════════════════════════════════
// LIVE ANIMATION BRIDGE — Entity extraction, animation, auto-zoom
// ═══════════════════════════════════════════════════════════════════════

// SQL keywords to exclude from entity extraction
const _SQL_KEYWORDS = new Set([
    'select', 'from', 'where', 'and', 'or', 'not', 'in', 'is', 'null',
    'join', 'inner', 'outer', 'left', 'right', 'on', 'as', 'order', 'by',
    'group', 'having', 'limit', 'offset', 'insert', 'into', 'values',
    'update', 'set', 'delete', 'create', 'drop', 'alter', 'table',
    'index', 'view', 'database', 'schema', 'like', 'between', 'exists',
    'case', 'when', 'then', 'else', 'end', 'distinct', 'count', 'sum',
    'avg', 'min', 'max', 'asc', 'desc', 'union', 'all', 'top', 'with',
]);

/**
 * Extract entity names from an event payload.
 * Returns an array of candidate names to match against graph nodes.
 */
function _extractEntityNames(eventType, payload) {
    const names = new Set();
    if (!payload) return [];

    // Tier 1: Direct argument fields
    const args = payload.arguments || payload.details?.arguments || {};
    if (args.database_name) names.add(args.database_name);
    if (args.object_name) names.add(args.object_name);
    if (args.table_name) names.add(args.table_name);
    if (args.column_name) names.add(args.column_name);

    // Tier 2: SQL parsing via regex
    const sql = args.sql || payload.details?.sql || '';
    if (sql) {
        const patterns = [
            /\bFROM\s+(\w+)/gi,
            /\bJOIN\s+(\w+)/gi,
            /\bINTO\s+(\w+)/gi,
            /\bUPDATE\s+(\w+)/gi,
            /\bTABLE\s+(\w+)/gi,
        ];
        for (const pat of patterns) {
            let m;
            while ((m = pat.exec(sql)) !== null) {
                const candidate = m[1];
                if (!_SQL_KEYWORDS.has(candidate.toLowerCase())) {
                    names.add(candidate);
                }
            }
        }
    }

    // Tier 3: Match known node names against phase goal text
    if ((eventType === 'plan_generated' || eventType === 'phase_start') && _graphState) {
        const goal = payload.goal || '';
        if (goal) {
            const goalLower = goal.toLowerCase();
            for (const node of _graphState.nodes) {
                if (node.name.length >= 3 && goalLower.includes(node.name.toLowerCase())) {
                    names.add(node.name);
                }
            }
        }
        // Also extract from plan phases
        const phases = payload.phases || [];
        for (const phase of phases) {
            const phaseGoal = phase.goal || phase.goal_template || '';
            if (phaseGoal) {
                const gl = phaseGoal.toLowerCase();
                for (const node of _graphState.nodes) {
                    if (node.name.length >= 3 && gl.includes(node.name.toLowerCase())) {
                        names.add(node.name);
                    }
                }
            }
        }
    }

    return [...names];
}

/**
 * Match extracted entity names against graph nodes (case-insensitive).
 * Returns array of matched node data objects.
 */
function _matchNodesToNames(entityNames) {
    if (!_graphState || !entityNames.length) return [];
    const matched = [];
    const nameLookup = new Map();
    for (const n of entityNames) nameLookup.set(n.toLowerCase(), true);
    for (const node of _graphState.nodes) {
        if (nameLookup.has(node.name.toLowerCase())) {
            matched.push(node);
        }
    }
    return matched;
}

/**
 * Get 1-hop neighbor node IDs for a set of source node IDs.
 */
function _getNeighborIds(sourceIds) {
    if (!_graphState) return new Set();
    const neighbors = new Set();
    const srcSet = new Set(sourceIds);
    for (const link of _graphState.links) {
        const sid = typeof link.source === 'object' ? link.source.id : link.source;
        const tid = typeof link.target === 'object' ? link.target.id : link.target;
        if (srcSet.has(sid)) neighbors.add(tid);
        if (srcSet.has(tid)) neighbors.add(sid);
    }
    // Remove the source nodes themselves
    for (const id of sourceIds) neighbors.delete(id);
    return neighbors;
}

// ─── Animation: Pulse a single node ────────────────────────────────────

function _pulseNode(nodeData) {
    if (!_graphState) return;
    const { nodeGroups, colors } = _graphState;

    // Find the node group element
    const nodeEl = nodeGroups.filter(d => d.id === nodeData.id);
    if (nodeEl.empty()) return;

    // Remove any existing activity ring on this node
    nodeEl.selectAll('.kg-activity-ring').remove();

    const color = colors[nodeData.type] || '#F15F22';

    // Append expanding ring (CSS animation handles the rest)
    nodeEl.append('circle')
        .attr('class', 'kg-activity-ring')
        .attr('r', 16)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', 2)
        .attr('stroke-opacity', 0.7);

    // Apply activity glow filter to the rect temporarily
    nodeEl.select('rect')
        .transition('activity')
        .duration(300)
        .attr('filter', 'url(#kg-activity-glow)');

    // Revert rect filter after animation
    const revertTimeout = setTimeout(() => {
        if (!_graphState) return;
        nodeEl.select('rect')
            .transition('activity')
            .duration(600)
            .attr('filter', 'url(#kg-shadow)');
    }, 1200);

    // Clean up the ring element after animation completes
    const cleanupTimeout = setTimeout(() => {
        nodeEl.selectAll('.kg-activity-ring').remove();
    }, 1400);

    // Track for cleanup
    const existing = _activeAnimations.get(nodeData.id);
    if (existing) {
        clearTimeout(existing.revertTimeout);
        clearTimeout(existing.cleanupTimeout);
    }
    _activeAnimations.set(nodeData.id, { revertTimeout, cleanupTimeout });
}

// ─── Animation: Brighten connected edges ───────────────────────────────

function _rippleEdges(nodeData) {
    if (!_graphState) return;
    const { linkLines, linkGroup } = _graphState;

    // Brighten connected edges
    linkLines
        .filter(l => l.source === nodeData || l.target === nodeData ||
                     l.source.id === nodeData.id || l.target.id === nodeData.id)
        .transition('activity')
        .delay(150)
        .duration(400)
        .attr('stroke-opacity', 0.85)
        .attr('stroke-width', 2.5)
        .transition('activity')
        .duration(800)
        .attr('stroke-opacity', 0.5)
        .attr('stroke-width', 1.5);

    // Brighten connected edge labels
    linkGroup.selectAll('text')
        .filter(l => l.source === nodeData || l.target === nodeData ||
                     l.source.id === nodeData.id || l.target.id === nodeData.id)
        .transition('activity')
        .delay(150)
        .duration(400)
        .style('opacity', 0.85)
        .transition('activity')
        .duration(800)
        .style('opacity', null);
}

// ─── Animation: Soft glow on neighbor nodes ────────────────────────────

function _glowNeighbors(nodeData) {
    if (!_graphState) return;
    const { nodeGroups } = _graphState;
    const neighborIds = _getNeighborIds([nodeData.id]);

    nodeGroups
        .filter(d => neighborIds.has(d.id))
        .each(function(d) {
            const el = d3.select(this);
            // Skip hidden/filtered nodes
            if (el.style('display') === 'none') return;

            el.select('rect')
                .transition('neighbor-glow')
                .delay(300)
                .duration(400)
                .attr('filter', `url(#kg-glow-${d.type})`)
                .transition('neighbor-glow')
                .delay(200)
                .duration(600)
                .attr('filter', 'url(#kg-shadow)');
        });
}

// ─── Animation: Orchestrate all layers for matched nodes ───────────────

function _animateNodes(matchedNodes) {
    if (!_graphState || matchedNodes.length === 0) return;
    const { nodeGroups } = _graphState;

    for (const node of matchedNodes) {
        // Skip hidden nodes (filtered out by type pills)
        const nodeEl = nodeGroups.filter(d => d.id === node.id);
        if (nodeEl.empty() || nodeEl.style('display') === 'none') continue;

        _pulseNode(node);
        _rippleEdges(node);
        _glowNeighbors(node);
    }
}

// ─── Auto-Zoom: Smooth camera to relevant subgraph ────────────────────

function _zoomToNodes(matchedNodes) {
    if (!_graphState || matchedNodes.length === 0) return;
    if (_userZoomOverride) return; // User manually panned — skip this event

    const { svg, zoom, width, height, nodes } = _graphState;

    // Collect positions of matched nodes + 1-hop neighbors
    const matchedIds = matchedNodes.map(n => n.id);
    const neighborIds = _getNeighborIds(matchedIds);
    const allRelevantIds = new Set([...matchedIds, ...neighborIds]);

    const relevantNodes = nodes.filter(n => allRelevantIds.has(n.id) && n.x != null && n.y != null);
    if (relevantNodes.length === 0) return;

    // Compute bounding box with padding
    const pad = 80;
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const n of relevantNodes) {
        if (n.x < minX) minX = n.x;
        if (n.x > maxX) maxX = n.x;
        if (n.y < minY) minY = n.y;
        if (n.y > maxY) maxY = n.y;
    }
    minX -= pad; maxX += pad; minY -= pad; maxY += pad;

    const bboxW = maxX - minX;
    const bboxH = maxY - minY;
    if (bboxW <= 0 || bboxH <= 0) return;

    // Calculate scale to fit bbox in viewport
    const scaleX = width / bboxW;
    const scaleY = height / bboxH;
    let scale = Math.min(scaleX, scaleY);
    scale = Math.max(0.4, Math.min(scale, 2.5)); // Clamp

    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;

    const transform = d3.zoomIdentity
        .translate(width / 2, height / 2)
        .scale(scale)
        .translate(-cx, -cy);

    // Debounce: cancel any pending auto-zoom
    if (_autozoomDebounce) clearTimeout(_autozoomDebounce);
    _autozoomDebounce = setTimeout(() => {
        if (!_graphState) return;
        svg.transition('autozoom')
            .duration(800)
            .ease(d3.easeCubicInOut)
            .call(zoom.transform, transform);
        _autozoomDebounce = null;
    }, 200);
}

function _zoomToFitAll() {
    if (!_graphState) return;
    const { svg, zoom, width, height } = _graphState;

    if (_autozoomDebounce) clearTimeout(_autozoomDebounce);

    svg.transition('autozoom')
        .duration(1000)
        .ease(d3.easeCubicInOut)
        .call(
            zoom.transform,
            d3.zoomIdentity.translate(width / 2, height / 2).scale(0.8).translate(-width / 2, -height / 2)
        );
}

// ─── Cleanup ───────────────────────────────────────────────────────────

function _clearAllAnimations() {
    // Remove all activity rings
    if (_graphState) {
        _graphState.nodeGroups.selectAll('.kg-activity-ring').remove();
        // Reset filters to baseline
        _graphState.nodeGroups.select('rect')
            .interrupt('activity')
            .attr('filter', 'url(#kg-shadow)');
        // Reset edges to baseline
        _graphState.linkLines
            .interrupt('activity')
            .attr('stroke-opacity', 0.5)
            .attr('stroke-width', 1.5);
        // Reset neighbor glows
        _graphState.nodeGroups.select('rect').interrupt('neighbor-glow');
    }

    // Cancel all tracked timeouts
    for (const [, entry] of _activeAnimations) {
        clearTimeout(entry.revertTimeout);
        clearTimeout(entry.cleanupTimeout);
    }
    _activeAnimations.clear();

    if (_autozoomDebounce) {
        clearTimeout(_autozoomDebounce);
        _autozoomDebounce = null;
    }

    _userZoomOverride = false;
}

// ─── Exported Bridge API ───────────────────────────────────────────────

/** Check if KG split panel is open and graph is rendered. */
export function isKGPanelActive() {
    return !!_graphState && !!_activeSpec;
}

/**
 * Main entry point — called from eventHandlers.js processStream().
 * Parses event for entity references and triggers animations + auto-zoom.
 */
export function dispatchKGAnimation(eventType, payload) {
    if (!_graphState || !_activeSpec) return;

    const entityNames = _extractEntityNames(eventType, payload);
    const matchedNodes = _matchNodesToNames(entityNames);
    if (matchedNodes.length === 0) return;

    // Clear user zoom override on new entity match (resume auto-zoom)
    _userZoomOverride = false;

    _animateNodes(matchedNodes);
    _zoomToNodes(matchedNodes);
}

/**
 * Graceful wind-down — called on execution_complete or final_answer.
 * Lets in-flight animations finish, then cleans up and zooms to fit-all.
 */
export function endKGExecutionAnimations() {
    if (!_graphState) return;

    // Let in-flight animations finish naturally, then clean up
    setTimeout(() => {
        _clearAllAnimations();
    }, 500);

    // Smooth zoom back to full view
    setTimeout(() => {
        _zoomToFitAll();
    }, 600);
}


// ─── Style Injection ────────────────────────────────────────────────────

function injectStyles() {
    if (_stylesInjected) return;
    _stylesInjected = true;

    const style = document.createElement('style');
    style.textContent = `
/* ═══════════════════════════════════════════════════════════════════
   Knowledge Graph Component Styles (theme-compliant)
   ═══════════════════════════════════════════════════════════════════ */

/* ─── Inline Compact ────────────────────────────────────────────── */
.kg-inline-compact {
    border: 1px solid var(--border-secondary, rgba(255,255,255,0.08));
    border-radius: 12px;
    background: var(--glass-bg, rgba(15, 23, 42, 0.5));
    overflow: hidden;
}
.kg-inline-compact-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 14px;
    border-bottom: 1px solid var(--border-subtle, var(--border-secondary, rgba(255,255,255,0.06)));
}
.kg-inline-compact-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary, #e2e8f0);
}
.kg-inline-compact-badge {
    font-size: 11px;
    color: var(--text-muted, #9ca3af);
    background: var(--hover-bg, rgba(255,255,255,0.06));
    padding: 2px 8px;
    border-radius: 10px;
}
.kg-inline-compact-graph {
    height: 200px;
    position: relative;
    cursor: grab;
}
.kg-inline-compact-graph:active {
    cursor: grabbing;
}
.kg-inline-compact-footer {
    display: flex;
    justify-content: flex-end;
    padding: 8px 14px;
    border-top: 1px solid var(--border-subtle, var(--border-secondary, rgba(255,255,255,0.06)));
}
.kg-inline-open-btn {
    font-size: 12px;
    color: var(--status-info, #60a5fa);
    background: none;
    border: none;
    cursor: pointer;
    padding: 4px 10px;
    border-radius: 6px;
    transition: all 0.15s;
}
.kg-inline-open-btn:hover {
    background: var(--status-info-bg, rgba(59,130,246,0.1));
}
.kg-inline-open-btn--active {
    color: var(--text-muted, #9ca3af);
}
.kg-inline-open-btn--active:hover {
    background: var(--hover-bg, rgba(255,255,255,0.05));
    color: var(--text-muted, #9ca3af);
}

/* ─── Split Panel ───────────────────────────────────────────────── */
#kg-split-panel {
    width: 0;
    min-width: 0;
    max-width: 55%;
    flex-shrink: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    background: var(--card-bg, rgba(15,23,42,0.6));
    border-left: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    transition: width 0.3s ease, min-width 0.3s ease;
}
#kg-split-panel.kg-split--open {
    width: 50%;
    min-width: 320px;
}
.kg-split-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border-secondary, rgba(255,255,255,0.08));
    background: var(--bg-overlay, var(--bg-primary, rgba(15,23,42,0.8)));
    flex-shrink: 0;
}
.kg-split-title-text {
    font-weight: 600;
    font-size: 0.8rem;
    color: var(--text-primary, #e2e8f0);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.kg-split-header-actions {
    display: flex;
    gap: 0.25rem;
    align-items: center;
}
.kg-split-action-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 0.25rem;
    border: none;
    background: transparent;
    color: var(--text-muted, #94a3b8);
    cursor: pointer;
    transition: all 0.15s ease;
}
.kg-split-action-btn:hover {
    background: var(--hover-bg-strong, rgba(255,255,255,0.1));
    color: var(--text-primary, #e2e8f0);
}
.kg-split-body {
    flex: 1;
    overflow: hidden;
    padding: 0;
    display: flex;
    flex-direction: column;
    min-height: 0;
}

/* ─── Fullscreen ────────────────────────────────────────────────── */
.kg-fullscreen #kg-split-panel.kg-split--open {
    position: fixed !important;
    top: var(--kg-fullscreen-top, 0px);
    left: 0 !important;
    right: 0 !important;
    bottom: 0 !important;
    width: auto !important;
    height: auto !important;
    max-width: none;
    z-index: 50;
}

/* ─── Toolbar ───────────────────────────────────────────────────── */
.kg-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: var(--header-bg, var(--bg-primary, rgba(15, 15, 20, 0.9)));
    border-bottom: 1px solid var(--border-secondary, rgba(255,255,255,0.08));
    flex-shrink: 0;
    flex-wrap: wrap;
}
.kg-toolbar-search {
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--input-bg, rgba(255,255,255,0.06));
    border: 1px solid var(--border-secondary, rgba(255,255,255,0.08));
    border-radius: 6px;
    padding: 4px 8px;
}
.kg-toolbar-search-input {
    background: transparent;
    border: none;
    outline: none;
    color: var(--text-primary, #e5e7eb);
    font-size: 12px;
    width: 130px;
}
.kg-toolbar-search-input::placeholder {
    color: var(--text-subtle, var(--text-muted, #6b7280));
}
.kg-toolbar-stats {
    font-size: 11px;
    color: var(--text-muted, #9ca3af);
    padding: 3px 8px;
    background: var(--hover-bg, rgba(255,255,255,0.04));
    border-radius: 10px;
    white-space: nowrap;
}
.kg-toolbar-filters {
    display: flex;
    gap: 4px;
    align-items: center;
}
.kg-toolbar-filter-pill {
    padding: 2px 8px;
    border-radius: 12px;
    font-size: 10px;
    border-width: 1px;
    border-style: solid;
    cursor: pointer;
    transition: all 0.2s;
}
.kg-toolbar-filter-pill:hover {
    filter: brightness(1.2);
}
.kg-toolbar-btn {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    background: var(--button-bg, rgba(255,255,255,0.06));
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    color: var(--text-primary, #e5e7eb);
    font-size: 14px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.2s;
}
.kg-toolbar-btn:hover {
    background: var(--hover-bg-strong, rgba(255,255,255,0.12));
}

/* ─── Legend ─────────────────────────────────────────────────────── */
.kg-legend {
    position: absolute;
    bottom: 10px;
    right: 10px;
    background: var(--glass-bg-strong, var(--glass-bg, rgba(15,15,20,0.85)));
    backdrop-filter: blur(8px);
    border: 1px solid var(--glass-border, rgba(255,255,255,0.08));
    border-radius: 10px;
    padding: 8px 12px;
    z-index: 5;
    font-size: 11px;
}

/* ─── SVG Theme-Aware Fills ─────────────────────────────────────── */
/* CSS fill/stroke properties override SVG presentation attributes, */
/* ensuring CSS variables are evaluated live by the browser engine. */
.kg-node-name  { fill: var(--text-primary, #e5e7eb); }
.kg-edge-label { fill: var(--text-muted, #6b7280); opacity: 0.5; }
.kg-mini-label { fill: var(--text-muted, #9ca3af); }
.kg-mini-link  { stroke: var(--border-primary, #4b5563); }
#kg-arrow path { fill: var(--text-muted, #555); }

/* ─── Tooltip (HTML overlay) ────────────────────────────────────── */
.kg-tooltip {
    position: absolute;
    display: none;
    background: var(--bg-overlay, var(--bg-primary, rgba(15,15,20,0.95)));
    border: 1px solid var(--border-primary, rgba(255,255,255,0.1));
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 12px;
    color: var(--text-primary, #e5e7eb);
    pointer-events: none;
    z-index: 10;
    max-width: 280px;
    backdrop-filter: blur(8px);
}

/* ─── Live Execution Animation ─────────────────────────────────── */
@keyframes kg-activity-expand {
    0%   { stroke-opacity: 0.7; r: 16; }
    40%  { stroke-opacity: 0.5; r: 22; }
    100% { stroke-opacity: 0;   r: 28; }
}
.kg-activity-ring {
    animation: kg-activity-expand 1.2s ease-out forwards;
    pointer-events: none;
}

/* ─── Light Theme Adjustments ─────────────────────────────────── */
[data-theme="light"] .kg-edge-label { opacity: 0.7; }
[data-theme="light"] .kg-mini-link  { stroke-opacity: 0.6; }
    `;
    document.head.appendChild(style);
}
