import React from 'react';
import { Handle, Position } from 'reactflow';

// Profile type colors matching Uderia
const PROFILE_COLORS = {
  tool_enabled: { bg: '#9333ea', border: '#a855f7', text: '#e9d5ff' },
  llm_only: { bg: '#22c55e', border: '#4ade80', text: '#dcfce7' },
  rag_focused: { bg: '#3b82f6', border: '#60a5fa', text: '#dbeafe' },
  genie: { bg: '#F15F22', border: '#f97316', text: '#ffedd5' }
};

export default function ProfileNode({ data, selected }) {
  const status = data.executionStatus;
  const profileType = data.profileType || 'tool_enabled';
  const colors = PROFILE_COLORS[profileType] || PROFILE_COLORS.tool_enabled;

  return (
    <div
      className={`
        relative px-4 py-3 rounded-lg border-2 min-w-[180px]
        bg-gray-900/90
        ${selected ? 'ring-2 ring-offset-2 ring-offset-gray-900' : ''}
        ${status === 'running' ? 'animate-pulse' : ''}
        ${status === 'completed' ? 'border-emerald-400' : ''}
        ${status === 'error' ? 'border-rose-500' : ''}
      `}
      style={{
        borderColor: status === 'completed' ? '#4ade80' : status === 'error' ? '#ef4444' : colors.border,
        '--ring-color': colors.border
      }}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 border-2"
        style={{ backgroundColor: colors.bg, borderColor: colors.border }}
      />

      {/* Status indicator */}
      {status && (
        <div className="absolute -top-1 -right-1">
          {status === 'running' && (
            <div className="w-4 h-4 rounded-full bg-amber-400 flex items-center justify-center">
              <svg className="w-3 h-3 text-amber-900 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
          )}
          {status === 'completed' && (
            <div className="w-4 h-4 rounded-full bg-emerald-400 flex items-center justify-center">
              <svg className="w-2.5 h-2.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
              </svg>
            </div>
          )}
          {status === 'error' && (
            <div className="w-4 h-4 rounded-full bg-rose-500 flex items-center justify-center">
              <span className="text-white text-xs font-bold">!</span>
            </div>
          )}
        </div>
      )}

      {/* Header with profile tag */}
      <div className="flex items-center gap-2 mb-2">
        <div
          className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold"
          style={{ backgroundColor: `${colors.bg}30`, color: colors.border }}
        >
          {(data.profileTag || data.label || 'P').charAt(0).toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-white truncate">{data.label || 'Profile'}</div>
          {data.profileTag && (
            <div className="text-xs truncate" style={{ color: colors.border }}>
              {data.profileTag}
            </div>
          )}
        </div>
      </div>

      {/* Profile type badge */}
      <div
        className="inline-block px-2 py-0.5 rounded text-xs font-medium"
        style={{ backgroundColor: `${colors.bg}20`, color: colors.border }}
      >
        {profileType.replace('_', ' ')}
      </div>

      {/* Execution stats */}
      {status === 'completed' && data.executionDuration && (
        <div className="mt-2 text-xs text-gray-500">
          {data.executionDuration.toFixed(2)}s
        </div>
      )}

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 border-2"
        style={{ backgroundColor: colors.bg, borderColor: colors.border }}
      />
    </div>
  );
}
