/**
 * Knowledge Graph Component Renderer
 *
 * Premium D3.js v7 force-directed graph visualization.
 * Designed for Uderia's dark glass-panel aesthetic with glowing nodes,
 * gradient edges, animated entry, and interactive exploration.
 *
 * @param {string} containerId - DOM element ID to render into
 * @param {object|string} payload - ComponentRenderPayload.spec from backend
 *   Expected: { nodes, links, title, center_entity, depth, entity_type_colors }
 */
export function renderKnowledgeGraph(containerId, payload) {
    const spec = typeof payload === 'string' ? JSON.parse(payload) : payload;
    const container = document.getElementById(containerId);
    if (!container || !spec || !spec.nodes) return null;

    // Clear container
    container.innerHTML = '';
    container.style.position = 'relative';
    container.style.background = 'rgba(0, 0, 0, 0.3)';
    container.style.borderRadius = '8px';
    container.style.overflow = 'hidden';

    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;
    const colors = spec.entity_type_colors || {};
    const nodes = spec.nodes || [];
    const links = spec.links || [];

    if (nodes.length === 0) {
        container.innerHTML = '<p style="color:#9ca3af;text-align:center;padding:2rem">No entities in graph</p>';
        return null;
    }

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

    // Pulse animation for center entity
    defs.append('style').text(`
        @keyframes kg-pulse { 0%, 100% { opacity: 0.6; } 50% { opacity: 0.15; } }
        .kg-center-ring { animation: kg-pulse 2s ease-in-out infinite; }
        .kg-node-label { pointer-events: none; user-select: none; }
        .kg-edge-label { pointer-events: none; user-select: none; }
    `);

    // Gradient for each link (source color → target color)
    links.forEach((link, i) => {
        const sourceType = nodes[typeof link.source === 'object' ? link.source.index : link.source]?.type;
        const targetType = nodes[typeof link.target === 'object' ? link.target.index : link.target]?.type;
        const grad = defs.append('linearGradient').attr('id', `kg-grad-${i}`).attr('gradientUnits', 'userSpaceOnUse');
        grad.append('stop').attr('offset', '0%').attr('stop-color', colors[sourceType] || '#6b7280');
        grad.append('stop').attr('offset', '100%').attr('stop-color', colors[targetType] || '#6b7280');
    });

    // Arrowhead marker
    defs.append('marker')
        .attr('id', 'kg-arrow')
        .attr('viewBox', '0 -5 10 10')
        .attr('refX', 28)
        .attr('refY', 0)
        .attr('markerWidth', 6)
        .attr('markerHeight', 6)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-4L8,0L0,4')
        .attr('fill', '#555');

    // ─── Zoom ────────────────────────────────────────────────────────
    const g = svg.append('g');

    const zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => g.attr('transform', event.transform));
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

    const linkLine = linkGroup.append('line')
        .attr('stroke', (d, i) => `url(#kg-grad-${i})`)
        .attr('stroke-width', 1.5)
        .attr('stroke-opacity', 0.5)
        .attr('marker-end', 'url(#kg-arrow)')
        // Animated entry: draw from zero length
        .attr('stroke-dasharray', function() { return this.getTotalLength ? this.getTotalLength() : 200; })
        .attr('stroke-dashoffset', function() { return this.getTotalLength ? this.getTotalLength() : 200; })
        .transition()
        .delay((d, i) => 300 + i * 30)
        .duration(600)
        .attr('stroke-dashoffset', 0);

    // Rebuild line references after transition (d3 transitions return new selection)
    const linkLines = linkGroup.select('line');

    // Edge labels (semi-transparent, visible on hover)
    linkGroup.append('text')
        .attr('class', 'kg-edge-label')
        .text(d => d.type)
        .attr('font-size', '9px')
        .attr('fill', '#6b7280')
        .attr('text-anchor', 'middle')
        .attr('dy', -6)
        .style('opacity', 0.3);

    // ─── Nodes ───────────────────────────────────────────────────────
    const nodeGroup = g.selectAll('.kg-node')
        .data(nodes)
        .join('g')
        .attr('class', 'kg-node')
        .style('cursor', 'pointer')
        // Animated entry: fade in staggered
        .style('opacity', 0)
        .transition()
        .delay((d, i) => i * 40)
        .duration(400)
        .style('opacity', 1);

    // Rebuild for event handling (transition returns new selection)
    const nodeGroups = g.selectAll('.kg-node');

    // Center entity pulse ring
    nodeGroups.filter(d => d.is_center)
        .append('circle')
        .attr('class', 'kg-center-ring')
        .attr('r', 24)
        .attr('fill', 'none')
        .attr('stroke', d => colors[d.type] || '#6b7280')
        .attr('stroke-width', 2);

    // Node: rounded rectangle card
    const nodeW = 24;
    const nodeH = 24;
    nodeGroups.append('rect')
        .attr('x', -nodeW / 2)
        .attr('y', -nodeH / 2)
        .attr('width', nodeW)
        .attr('height', nodeH)
        .attr('rx', 8)
        .attr('ry', 8)
        .attr('fill', d => {
            const c = colors[d.type] || '#6b7280';
            return `${c}30`; // 30 = ~19% opacity
        })
        .attr('stroke', d => colors[d.type] || '#6b7280')
        .attr('stroke-width', 1.5)
        .attr('filter', 'url(#kg-shadow)');

    // Node: type indicator dot
    nodeGroups.append('circle')
        .attr('cx', 0)
        .attr('cy', 0)
        .attr('r', d => 5 + (d.importance || 0) * 15)
        .attr('fill', d => colors[d.type] || '#6b7280');

    // Node: label
    nodeGroups.append('text')
        .attr('class', 'kg-node-label')
        .text(d => d.name.length > 18 ? d.name.slice(0, 16) + '…' : d.name)
        .attr('font-size', '11px')
        .attr('fill', '#e5e7eb')
        .attr('dx', nodeW / 2 + 6)
        .attr('dy', 4)
        .attr('font-weight', d => d.is_center ? '600' : '400');

    // Node: type badge (small text below)
    nodeGroups.append('text')
        .attr('class', 'kg-node-label')
        .text(d => d.type)
        .attr('font-size', '8px')
        .attr('fill', d => colors[d.type] || '#6b7280')
        .attr('dx', nodeW / 2 + 6)
        .attr('dy', 16);

    // ─── Interaction: Hover Glow ─────────────────────────────────────
    nodeGroups
        .on('mouseenter', function(event, d) {
            d3.select(this).select('rect')
                .attr('filter', `url(#kg-glow-${d.type})`);
            // Show connected edges
            linkGroup.select('text')
                .style('opacity', l => (l.source === d || l.target === d) ? 0.9 : 0.15);
            linkLines
                .attr('stroke-opacity', l => (l.source === d || l.target === d) ? 0.9 : 0.15);
        })
        .on('mouseleave', function() {
            d3.select(this).select('rect')
                .attr('filter', 'url(#kg-shadow)');
            linkGroup.select('text').style('opacity', 0.3);
            linkLines.attr('stroke-opacity', 0.5);
        });

    // ─── Interaction: Click Focus ────────────────────────────────────
    let focusedNode = null;

    nodeGroups.on('click', function(event, d) {
        event.stopPropagation();
        if (focusedNode === d) {
            // Unfocus
            focusedNode = null;
            nodeGroups.style('opacity', 1);
            linkLines.attr('stroke-opacity', 0.5);
            linkGroup.select('text').style('opacity', 0.3);
        } else {
            focusedNode = d;
            const connected = new Set();
            connected.add(d.id);
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

    // Click background to unfocus
    svg.on('click', () => {
        focusedNode = null;
        nodeGroups.style('opacity', 1);
        linkLines.attr('stroke-opacity', 0.5);
        linkGroup.select('text').style('opacity', 0.3);
    });

    // ─── Interaction: Drag ───────────────────────────────────────────
    nodeGroups.call(d3.drag()
        .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        })
        .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
        })
        .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        })
    );

    // ─── Tooltip ─────────────────────────────────────────────────────
    const tooltip = d3.select(container)
        .append('div')
        .style('position', 'absolute')
        .style('display', 'none')
        .style('background', 'rgba(15, 15, 20, 0.95)')
        .style('border', '1px solid rgba(255,255,255,0.1)')
        .style('border-radius', '8px')
        .style('padding', '10px 14px')
        .style('font-size', '12px')
        .style('color', '#e5e7eb')
        .style('pointer-events', 'none')
        .style('z-index', '10')
        .style('max-width', '280px')
        .style('backdrop-filter', 'blur(8px)');

    nodeGroups
        .on('mouseenter.tooltip', function(event, d) {
            const props = d.properties || {};
            let html = `<div style="font-weight:600;color:${colors[d.type] || '#fff'}">${d.name}</div>`;
            html += `<div style="color:#9ca3af;font-size:11px;margin-bottom:4px">${d.type}</div>`;
            if (props.description) html += `<div>${props.description}</div>`;
            if (props.data_type) html += `<div style="color:#9ca3af">Type: ${props.data_type}</div>`;
            if (props.business_meaning) html += `<div style="color:#a78bfa">Business: ${props.business_meaning}</div>`;
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
        // Update link positions (and gradients)
        linkGroup.select('line')
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y);

        linkGroup.select('text')
            .attr('x', d => (d.source.x + d.target.x) / 2)
            .attr('y', d => (d.source.y + d.target.y) / 2);

        // Update gradient endpoints
        links.forEach((d, i) => {
            const grad = defs.select(`#kg-grad-${i}`);
            if (grad.size()) {
                grad.attr('x1', d.source.x).attr('y1', d.source.y)
                    .attr('x2', d.target.x).attr('y2', d.target.y);
            }
        });

        // Update node positions
        nodeGroups.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    // ─── Controls Overlay ────────────────────────────────────────────
    _renderControls(container, svg, g, zoom, width, height, nodes, colors, nodeGroups, simulation);

    // ─── Legend ───────────────────────────────────────────────────────
    _renderLegend(container, colors, nodes);

    return { svg: svg.node(), simulation };
}


// ─── Controls Overlay ────────────────────────────────────────────────

function _renderControls(container, svg, g, zoom, width, height, nodes, colors, nodeGroups, simulation) {
    const controls = document.createElement('div');
    controls.style.cssText = `
        position:absolute; top:10px; right:10px;
        background:rgba(15,15,20,0.85); backdrop-filter:blur(8px);
        border:1px solid rgba(255,255,255,0.08); border-radius:10px;
        padding:8px; display:flex; flex-direction:column; gap:4px;
        z-index:5;
    `;

    // Zoom fit button
    const fitBtn = _makeButton('⊡', 'Zoom to fit');
    fitBtn.onclick = () => {
        svg.transition().duration(500).call(
            zoom.transform,
            d3.zoomIdentity.translate(width / 2, height / 2).scale(0.8).translate(-width / 2, -height / 2)
        );
    };
    controls.appendChild(fitBtn);

    // Entity count badge
    const badge = document.createElement('div');
    badge.style.cssText = 'color:#9ca3af;font-size:10px;text-align:center;padding:2px 0;';
    badge.textContent = `${nodes.length} nodes`;
    controls.appendChild(badge);

    container.appendChild(controls);

    // Search input
    const searchWrap = document.createElement('div');
    searchWrap.style.cssText = `
        position:absolute; top:10px; left:10px;
        background:rgba(15,15,20,0.85); backdrop-filter:blur(8px);
        border:1px solid rgba(255,255,255,0.08); border-radius:10px;
        padding:6px 10px; z-index:5; display:flex; align-items:center; gap:6px;
    `;
    const searchIcon = document.createElement('span');
    searchIcon.textContent = '🔍';
    searchIcon.style.fontSize = '12px';
    searchWrap.appendChild(searchIcon);

    const searchInput = document.createElement('input');
    searchInput.type = 'text';
    searchInput.placeholder = 'Search entities...';
    searchInput.style.cssText = `
        background:transparent; border:none; outline:none;
        color:#e5e7eb; font-size:12px; width:140px;
    `;
    searchInput.oninput = () => {
        const q = searchInput.value.toLowerCase();
        if (!q) {
            nodeGroups.style('opacity', 1);
            return;
        }
        nodeGroups.style('opacity', d => d.name.toLowerCase().includes(q) ? 1 : 0.12);
    };
    searchWrap.appendChild(searchInput);
    container.appendChild(searchWrap);

    // Filter pills (bottom)
    const types = [...new Set(nodes.map(n => n.type))];
    if (types.length > 1) {
        const filterBar = document.createElement('div');
        filterBar.style.cssText = `
            position:absolute; bottom:10px; left:50%; transform:translateX(-50%);
            background:rgba(15,15,20,0.85); backdrop-filter:blur(8px);
            border:1px solid rgba(255,255,255,0.08); border-radius:10px;
            padding:6px 10px; display:flex; gap:6px; z-index:5;
        `;

        const hiddenTypes = new Set();

        types.forEach(type => {
            const pill = document.createElement('button');
            pill.style.cssText = `
                padding:2px 8px; border-radius:12px; font-size:10px;
                border:1px solid ${colors[type] || '#6b7280'}60;
                background:${colors[type] || '#6b7280'}20;
                color:${colors[type] || '#6b7280'}; cursor:pointer;
                transition:all 0.2s;
            `;
            pill.textContent = type;
            pill.onclick = () => {
                if (hiddenTypes.has(type)) {
                    hiddenTypes.delete(type);
                    pill.style.opacity = '1';
                } else {
                    hiddenTypes.add(type);
                    pill.style.opacity = '0.3';
                }
                nodeGroups.style('display', d => hiddenTypes.has(d.type) ? 'none' : null);
                // Also hide edges connected to hidden nodes
                g.selectAll('.kg-link').style('display', function(l) {
                    const sType = (typeof l.source === 'object' ? l.source : nodes[l.source])?.type;
                    const tType = (typeof l.target === 'object' ? l.target : nodes[l.target])?.type;
                    return (hiddenTypes.has(sType) || hiddenTypes.has(tType)) ? 'none' : null;
                });
            };
            filterBar.appendChild(pill);
        });
        container.appendChild(filterBar);
    }
}


// ─── Legend ───────────────────────────────────────────────────────────

function _renderLegend(container, colors, nodes) {
    const presentTypes = [...new Set(nodes.map(n => n.type))];
    if (presentTypes.length <= 1) return;

    const legend = document.createElement('div');
    legend.style.cssText = `
        position:absolute; bottom:50px; right:10px;
        background:rgba(15,15,20,0.85); backdrop-filter:blur(8px);
        border:1px solid rgba(255,255,255,0.08); border-radius:10px;
        padding:8px 12px; z-index:5; font-size:11px;
    `;

    presentTypes.forEach(type => {
        const color = colors[type] || '#6b7280';
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:center;gap:6px;margin:2px 0;';
        row.innerHTML = `
            <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block"></span>
            <span style="color:#d1d5db">${type}</span>
        `;
        legend.appendChild(row);
    });

    container.appendChild(legend);
}


// ─── Helpers ─────────────────────────────────────────────────────────

function _makeButton(label, title) {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.title = title;
    btn.style.cssText = `
        width:28px; height:28px; border-radius:6px;
        background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.1);
        color:#e5e7eb; font-size:14px; cursor:pointer;
        display:flex; align-items:center; justify-content:center;
        transition:background 0.2s;
    `;
    btn.onmouseenter = () => { btn.style.background = 'rgba(255,255,255,0.12)'; };
    btn.onmouseleave = () => { btn.style.background = 'rgba(255,255,255,0.06)'; };
    return btn;
}
