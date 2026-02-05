import React, { useEffect, useRef } from 'react';
import { useFlowStore } from '../store/flowStore';

// Event type categories and colors (matches Uderia's Live Status patterns)
const EVENT_CATEGORIES = {
  'flow_execution_started': { color: '#10b981', icon: '▶', category: 'lifecycle' },
  'flow_execution_completed': { color: '#10b981', icon: '✓', category: 'lifecycle' },
  'flow_execution_failed': { color: '#ef4444', icon: '✗', category: 'error' },
  'flow_node_started': { color: '#F15F22', icon: '◉', category: 'execution' },
  'flow_node_completed': { color: '#10b981', icon: '✓', category: 'success' },
  'flow_node_error': { color: '#ef4444', icon: '✗', category: 'error' },
  'flow_node_skipped': { color: '#6b7280', icon: '○', category: 'system' },
  'flow_condition_evaluated': { color: '#06b6d4', icon: '◇', category: 'optimization' },
  'flow_loop_iteration': { color: '#ec4899', icon: '↻', category: 'system' },
  'flow_human_input_required': { color: '#f59e0b', icon: '👤', category: 'coordination' },
  'flow_human_input_received': { color: '#10b981', icon: '✓', category: 'success' },
  'flow_parallel_started': { color: '#14b8a6', icon: '⫴', category: 'system' },
  'flow_parallel_completed': { color: '#14b8a6', icon: '✓', category: 'success' }
};

function EventItem({ event }) {
  const config = EVENT_CATEGORIES[event.type] || { color: '#6b7280', icon: '•', category: 'system' };

  const formatTime = (timestamp) => {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };

  const renderEventContent = () => {
    switch (event.type) {
      case 'flow_execution_started':
        return (
          <div>
            <div className="font-medium">Flow Started</div>
            <div className="text-xs text-gray-500">{event.flow_name}</div>
          </div>
        );

      case 'flow_execution_completed':
        return (
          <div>
            <div className="font-medium text-emerald-400">Flow Completed</div>
            {event.duration && (
              <div className="text-xs text-gray-500">Duration: {event.duration.toFixed(2)}s</div>
            )}
          </div>
        );

      case 'flow_execution_failed':
        return (
          <div>
            <div className="font-medium text-rose-400">Flow Failed</div>
            <div className="text-xs text-rose-400/80">{event.error}</div>
          </div>
        );

      case 'flow_node_started':
        return (
          <div>
            <div className="font-medium">{event.node_label || event.node_id}</div>
            <div className="text-xs text-gray-500">
              <span className="px-1.5 py-0.5 rounded bg-white/5">{event.node_type}</span>
              {event.profile_tag && (
                <span className="ml-2 text-purple-400">{event.profile_tag}</span>
              )}
            </div>
          </div>
        );

      case 'flow_node_completed':
        return (
          <div>
            <div className="font-medium text-emerald-400">{event.node_label || event.node_id}</div>
            {event.duration && (
              <div className="text-xs text-gray-500">{event.duration.toFixed(2)}s</div>
            )}
            {event.token_usage && (
              <div className="text-xs text-gray-500">
                Tokens: {event.token_usage.input?.toLocaleString() || 0} in / {event.token_usage.output?.toLocaleString() || 0} out
              </div>
            )}
          </div>
        );

      case 'flow_node_error':
        return (
          <div>
            <div className="font-medium text-rose-400">{event.node_label || event.node_id}</div>
            <div className="text-xs text-rose-400/80">{event.error}</div>
          </div>
        );

      case 'flow_condition_evaluated':
        return (
          <div>
            <div className="font-medium">{event.node_label || 'Condition'}</div>
            <div className="text-xs">
              <code className="bg-white/5 px-1 py-0.5 rounded">{event.expression}</code>
              <span className={`ml-2 ${event.result ? 'text-emerald-400' : 'text-rose-400'}`}>
                → {event.result ? 'TRUE' : 'FALSE'}
              </span>
            </div>
          </div>
        );

      case 'flow_human_input_required':
        return (
          <div>
            <div className="font-medium text-amber-400">Human Input Required</div>
            <div className="text-xs text-gray-500">{event.prompt}</div>
          </div>
        );

      case 'flow_loop_iteration':
        return (
          <div>
            <div className="font-medium">Loop Iteration</div>
            <div className="text-xs text-gray-500">
              {event.index + 1} of {event.total}
            </div>
          </div>
        );

      default:
        return (
          <div>
            <div className="font-medium">{event.type}</div>
            {event.message && <div className="text-xs text-gray-500">{event.message}</div>}
          </div>
        );
    }
  };

  return (
    <div className="p-3 rounded-lg bg-gray-800/50 border border-white/5 mb-2">
      <div className="flex items-start gap-3">
        <div
          className="w-6 h-6 rounded-full flex items-center justify-center text-sm flex-shrink-0"
          style={{ backgroundColor: `${config.color}20`, color: config.color }}
        >
          {config.icon}
        </div>
        <div className="flex-1 min-w-0">
          {renderEventContent()}
        </div>
        <div className="text-xs text-gray-600 flex-shrink-0">
          {formatTime(event.timestamp)}
        </div>
      </div>
    </div>
  );
}

export default function ExecutionPanel() {
  const {
    isExecutionPanelExpanded,
    toggleExecutionPanel,
    executionId,
    executionStatus,
    executionEvents,
    clearExecutionEvents
  } = useFlowStore();

  const eventsContainerRef = useRef(null);

  // Auto-scroll to bottom when new events arrive
  useEffect(() => {
    if (eventsContainerRef.current) {
      eventsContainerRef.current.scrollTop = eventsContainerRef.current.scrollHeight;
    }
  }, [executionEvents]);

  if (!isExecutionPanelExpanded) {
    return (
      <div className="h-full flex flex-col items-center py-4 bg-gray-900/50">
        <button
          onClick={toggleExecutionPanel}
          className="p-2 rounded-lg hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
          title="Expand execution panel"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        {/* Status indicator */}
        {executionStatus && (
          <div className="mt-4">
            {executionStatus === 'running' && (
              <div className="w-3 h-3 rounded-full bg-amber-400 animate-pulse" title="Running" />
            )}
            {executionStatus === 'completed' && (
              <div className="w-3 h-3 rounded-full bg-emerald-400" title="Completed" />
            )}
            {executionStatus === 'failed' && (
              <div className="w-3 h-3 rounded-full bg-rose-400" title="Failed" />
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-gray-900/50">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-white/10">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-white">Execution</h3>
          {executionStatus && (
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              executionStatus === 'running' ? 'bg-amber-400/20 text-amber-400' :
              executionStatus === 'completed' ? 'bg-emerald-400/20 text-emerald-400' :
              executionStatus === 'failed' ? 'bg-rose-400/20 text-rose-400' :
              'bg-gray-500/20 text-gray-400'
            }`}>
              {executionStatus}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {executionEvents.length > 0 && (
            <button
              onClick={clearExecutionEvents}
              className="p-1 rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
              title="Clear events"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          )}
          <button
            onClick={toggleExecutionPanel}
            className="p-1 rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
            title="Collapse panel"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>
      </div>

      {/* Events list */}
      <div
        ref={eventsContainerRef}
        className="flex-1 overflow-y-auto p-3"
      >
        {executionEvents.length === 0 ? (
          <div className="h-full flex items-center justify-center text-gray-500 text-sm">
            <div className="text-center">
              <div className="mb-2">No execution events</div>
              <div className="text-xs">Run a flow to see events here</div>
            </div>
          </div>
        ) : (
          executionEvents.map((event, index) => (
            <EventItem key={`${event.type}-${index}`} event={event} />
          ))
        )}
      </div>

      {/* Execution ID footer */}
      {executionId && (
        <div className="p-2 border-t border-white/10 text-xs text-gray-600">
          ID: {executionId.slice(0, 8)}...
        </div>
      )}
    </div>
  );
}
