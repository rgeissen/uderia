/**
 * Chart Component Renderer
 *
 * Renders G2Plot charts from a chart spec produced by ChartComponentHandler.
 * This is the component-library equivalent of the original renderChart() in utils.js.
 *
 * Expects G2Plot to be loaded globally (CDN dependency declared in manifest.json).
 */

/**
 * Render a chart into a container element.
 *
 * @param {string} containerId - DOM element ID to render into
 * @param {object} payload - ComponentRenderPayload.spec from the backend
 *   Expected shape: { type: "Column"|"Line"|"Pie"|..., options: { data, xField, yField, ... } }
 */
export function renderChart(containerId, payload) {
    try {
        const spec = typeof payload === 'string' ? JSON.parse(payload) : payload;

        if (!spec || !spec.type || !spec.options) {
            throw new Error('Invalid chart specification provided.');
        }

        if (typeof G2Plot === 'undefined' || !G2Plot[spec.type]) {
            throw new Error(`Chart type "${spec.type}" is not supported or G2Plot is not loaded.`);
        }

        const plot = new G2Plot[spec.type](containerId, spec.options);
        plot.render();
        return plot;
    } catch (e) {
        console.error('Failed to render chart:', e);
        const container = document.getElementById(containerId);
        if (container) {
            container.innerHTML = `<div class="p-4 text-red-400">Error rendering chart: ${e.message}</div>`;
        }
        return null;
    }
}
