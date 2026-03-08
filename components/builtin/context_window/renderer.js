/**
 * Context Window system component — Resource Panel + Live Status renderer.
 *
 * Provides two visualization surfaces:
 *   1. Resource Panel "Context" tab: Module composition, budget allocation chart
 *   2. Live Status: context_window_snapshot event rendering
 *
 * This is a placeholder for Phase 5 implementation.
 */

export function renderContextWindow(containerId, payload) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // Phase 5: Full implementation with:
  // - Horizontal stacked bar chart of module allocations
  // - Per-module cards with active/inactive/skipped state
  // - Condensation event annotations
  // - Interactive module activation/deactivation
  // - Budget utilization percentage

  container.innerHTML = `
    <div class="context-window-placeholder" style="padding: 1rem; color: var(--text-muted, #888);">
      <p>Context Window visualization pending Phase 5 implementation.</p>
    </div>
  `;
}

export function renderContextWindowSnapshot(containerId, snapshot) {
  const container = document.getElementById(containerId);
  if (!container) return;

  // Phase 5: Render snapshot event as compact horizontal bar in Live Status
  const totalUsed = snapshot.total_used || 0;
  const budget = snapshot.available_budget || 1;
  const utilPct = ((totalUsed / budget) * 100).toFixed(1);

  const contributions = snapshot.contributions || [];
  const bars = contributions.map(c => {
    const width = budget > 0 ? ((c.tokens_used / budget) * 100).toFixed(1) : 0;
    return `<span class="ctx-bar" style="width:${width}%" title="${c.label}: ${c.tokens_used.toLocaleString()} tokens">${c.label}</span>`;
  }).join('');

  container.innerHTML = `
    <div class="context-window-snapshot">
      <div class="ctx-header">Context Window (${snapshot.context_window_type_name || 'Default'}) — ${totalUsed.toLocaleString()} / ${budget.toLocaleString()} tokens (${utilPct}%)</div>
      <div class="ctx-bars">${bars}</div>
    </div>
  `;
}
