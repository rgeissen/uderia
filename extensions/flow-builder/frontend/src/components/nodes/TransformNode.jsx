import React from 'react';
import { Handle, Position } from 'reactflow';

export default function TransformNode({ data, selected }) {
  const status = data.executionStatus;

  return (
    <div
      className={`
        relative px-4 py-3 rounded-lg border-2 min-w-[160px]
        bg-gray-900/90 border-indigo-500
        ${selected ? 'ring-2 ring-indigo-400 ring-offset-2 ring-offset-gray-900' : ''}
        ${status === 'running' ? 'animate-pulse' : ''}
        ${status === 'completed' ? 'border-emerald-400' : ''}
        ${status === 'error' ? 'border-rose-500' : ''}
      `}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-indigo-500 border-2 border-indigo-300"
      />

      {/* Status indicator */}
      {status && (
        <div className="absolute -top-1 -right-1">
          {status === 'running' && (
            <div className="w-3 h-3 rounded-full bg-amber-400 animate-pulse" />
          )}
          {status === 'completed' && (
            <div className="w-3 h-3 rounded-full bg-emerald-400 flex items-center justify-center">
              <svg className="w-2 h-2 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
              </svg>
            </div>
          )}
          {status === 'error' && (
            <div className="w-3 h-3 rounded-full bg-rose-500 flex items-center justify-center">
              <span className="text-white text-[8px] font-bold">!</span>
            </div>
          )}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <div className="w-6 h-6 rounded bg-indigo-500/20 flex items-center justify-center text-indigo-400">
          ⚙
        </div>
        <div className="text-sm font-medium text-white">{data.label || 'Transform'}</div>
      </div>

      {/* Operation type */}
      {data.operation && (
        <div className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-indigo-500/20 text-indigo-400 mb-2">
          {data.operation}
        </div>
      )}

      {/* Expression preview */}
      {data.expression && (
        <div className="p-2 bg-gray-800/50 rounded text-xs font-mono text-gray-400 truncate">
          {data.expression.length > 25 ? data.expression.slice(0, 25) + '...' : data.expression}
        </div>
      )}

      {/* Output key */}
      {data.outputKey && (
        <div className="text-xs text-gray-500 mt-2">
          → {data.outputKey}
        </div>
      )}

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-indigo-500 border-2 border-indigo-300"
      />
    </div>
  );
}
