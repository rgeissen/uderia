import React from 'react';
import { Handle, Position } from 'reactflow';

export default function ParallelNode({ data, selected }) {
  const status = data.executionStatus;

  return (
    <div
      className={`
        relative px-4 py-3 rounded-lg border-2 min-w-[160px]
        bg-gray-900/90 border-teal-500
        ${selected ? 'ring-2 ring-teal-400 ring-offset-2 ring-offset-gray-900' : ''}
        ${status === 'running' ? 'animate-pulse' : ''}
        ${status === 'completed' ? 'border-emerald-400' : ''}
        ${status === 'error' ? 'border-rose-500' : ''}
      `}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-teal-500 border-2 border-teal-300"
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

      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <div className="w-6 h-6 rounded bg-teal-500/20 flex items-center justify-center text-teal-400 text-lg">
          ⫴
        </div>
        <div className="text-sm font-medium text-white">{data.label || 'Parallel'}</div>
      </div>

      {/* Wait strategy */}
      {data.waitStrategy && (
        <div className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-teal-500/20 text-teal-400 mb-2">
          wait: {data.waitStrategy}
        </div>
      )}

      {/* Branch progress */}
      {status === 'running' && data.branchProgress && (
        <div className="space-y-1">
          {Object.entries(data.branchProgress).map(([branchId, progress]) => (
            <div key={branchId} className="flex items-center gap-2 text-xs">
              <span className="text-gray-500 w-16 truncate">{branchId}</span>
              <div className="flex-1 h-1 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all ${
                    progress === 'completed' ? 'bg-emerald-500 w-full' :
                    progress === 'running' ? 'bg-amber-500 w-1/2' :
                    progress === 'error' ? 'bg-rose-500 w-full' :
                    'bg-gray-600 w-0'
                  }`}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Completed stats */}
      {status === 'completed' && data.completedBranches !== undefined && (
        <div className="text-xs text-emerald-400 mt-1">
          ✓ {data.completedBranches} branches
        </div>
      )}

      {/* Timeout */}
      {data.timeout && (
        <div className="text-xs text-gray-500 mt-1">
          Timeout: {Math.floor(data.timeout / 60)}m
        </div>
      )}

      {/* Multiple output handles for branches */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="branch-1"
        className="w-3 h-3 bg-teal-500 border-2 border-teal-300"
        style={{ left: '25%' }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="branch-2"
        className="w-3 h-3 bg-teal-500 border-2 border-teal-300"
        style={{ left: '50%' }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="branch-3"
        className="w-3 h-3 bg-teal-500 border-2 border-teal-300"
        style={{ left: '75%' }}
      />

      {/* Branch labels */}
      <div className="absolute -bottom-4 left-0 w-full flex justify-around text-[9px] text-teal-400/60">
        <span>1</span>
        <span>2</span>
        <span>3</span>
      </div>
    </div>
  );
}
