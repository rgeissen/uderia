/**
 * Debug script to trace cost accumulation in the browser.
 *
 * To use:
 * 1. Open browser console (F12)
 * 2. Paste this entire script
 * 3. Submit a new query
 * 4. Watch console output to see which events are accumulating costs
 */

(function() {
    console.log('%c=== COST ACCUMULATION DEBUGGER ===', 'color: cyan; font-weight: bold; font-size: 14px');
    console.log('Intercepting UI.updateTokenDisplay calls...\n');

    // Store original function
    const originalUpdateTokenDisplay = window.UI.updateTokenDisplay;

    // Track accumulated costs
    let eventLog = [];
    let totalAccumulated = 0;

    // Override the function
    window.UI.updateTokenDisplay = function(data, isHistorical = false) {
        // Only track live events (not historical reloads)
        if (!isHistorical && data.cost_usd) {
            const cost = parseFloat(data.cost_usd) || 0;
            totalAccumulated += cost;

            // Get call stack to see where this was called from
            const stack = new Error().stack;
            const callerLine = stack.split('\n')[2]; // Get caller info

            const logEntry = {
                timestamp: new Date().toISOString().split('T')[1].substring(0, 12),
                cost: cost,
                cumulative: totalAccumulated,
                input_tokens: data.input_tokens || data.statement_input || 0,
                output_tokens: data.output_tokens || data.statement_output || 0,
                caller: callerLine?.trim() || 'unknown'
            };

            eventLog.push(logEntry);

            // Color code based on cost
            const color = cost > 0.003 ? 'red' : cost > 0.001 ? 'orange' : 'green';
            console.log(
                `%c[${logEntry.timestamp}] COST ACCUMULATED`,
                `color: ${color}; font-weight: bold`,
                `\n  💰 Cost: $${cost.toFixed(6)}`,
                `\n  📊 Cumulative: $${totalAccumulated.toFixed(6)}`,
                `\n  🎯 Tokens: ${logEntry.input_tokens} in / ${logEntry.output_tokens} out`,
                `\n  📍 Caller: ${logEntry.caller}`
            );
        }

        // Call original function
        return originalUpdateTokenDisplay.call(this, data, isHistorical);
    };

    // Add global function to show summary
    window.showCostDebugSummary = function() {
        console.log('%c\n=== COST DEBUG SUMMARY ===', 'color: cyan; font-weight: bold; font-size: 14px');
        console.log(`Total events logged: ${eventLog.length}`);
        console.log(`Total cost accumulated: $${totalAccumulated.toFixed(6)}\n`);

        eventLog.forEach((entry, index) => {
            console.log(
                `${index + 1}. [${entry.timestamp}] $${entry.cost.toFixed(6)}`,
                `(cumulative: $${entry.cumulative.toFixed(6)})`,
                `\n   ${entry.input_tokens} in / ${entry.output_tokens} out`,
                `\n   Called from: ${entry.caller}\n`
            );
        });

        // Check for aggregate events
        console.log('\n%c=== AGGREGATE EVENT CHECK ===', 'color: yellow; font-weight: bold');
        const costs = eventLog.map(e => e.cost);
        const hasDuplicates = costs.some((cost, i) =>
            costs.slice(i + 1).some(c => Math.abs(c - cost) < 0.000001)
        );

        if (hasDuplicates) {
            console.warn('⚠️  DUPLICATE COSTS DETECTED - Aggregate events may be getting through!');

            // Find duplicates
            costs.forEach((cost, i) => {
                const duplicateIndices = costs
                    .map((c, idx) => ({c, idx}))
                    .filter(({c, idx}) => idx !== i && Math.abs(c - cost) < 0.000001)
                    .map(({idx}) => idx);

                if (duplicateIndices.length > 0) {
                    console.log(`  Event #${i + 1} ($${cost.toFixed(6)}) duplicated in events: ${duplicateIndices.map(i => i + 1).join(', ')}`);
                }
            });
        } else {
            console.log('✅ No duplicate costs detected');
        }
    };

    // Add global function to reset
    window.resetCostDebugger = function() {
        eventLog = [];
        totalAccumulated = 0;
        console.log('%cCost debugger reset', 'color: green');
    };

    console.log('%cDebugger installed!', 'color: green; font-weight: bold');
    console.log('\nCommands available:');
    console.log('  - showCostDebugSummary() - Show detailed cost log');
    console.log('  - resetCostDebugger() - Clear log and start fresh');
    console.log('\n%cNow submit a query and watch this console...', 'color: yellow');
})();
