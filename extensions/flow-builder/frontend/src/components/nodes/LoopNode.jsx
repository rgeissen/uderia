import React from 'react';
import { Handle, Position } from 'reactflow';

export default function LoopNode({ data, selected }) {
  const status = data.executionStatus;

  return (
    <div
      className={`
        relative px-4 py-3 rounded-lg border-2 min-w-[160px]
        bg-gray-900/90 border-pink-500
        ${selected ? 'ring-2 ring-pink-400 ring-offset-2 ring-offset-gray-900' : ''}
        ${status === 'running' ? 'animate-pulse' : ''}
        ${status === 'completed' ? 'border-emerald-400' : ''}
        ${status === 'error' ? 'border-rose-500' : ''}
      `}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-pink-500 border-2 border-pink-300"
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
        <div className="w-6 h-6 rounded bg-pink-500/20 flex items-center justify-center text-pink-400">
          ↻
        </div>
        <div className="text-sm font-medium text-white">{data.label || 'Loop'}</div>
      </div>

      {/* Collection expression */}
      {data.collection && (
        <div className="p-2 bg-gray-800/50 rounded text-xs font-mono text-gray-400 truncate mb-2">
          {data.collection.length > 25 ? data.collection.slice(0, 25) + '...' : data.collection}
        </div>
      )}

      {/* Loop configuration */}
      <div className="flex items-center gap-2 text-xs text-gray-500">
        {data.itemVariable && (
          <span className="px-1.5 py-0.5 bg-gray-800/50 rounded">
            as {data.itemVariable}
          </span>
        )}
        {data.maxIterations && (
          <span className="px-1.5 py-0.5 bg-gray-800/50 rounded">
            max: {data.maxIterations}
          </span>
        )}
      </div>

      {/* Progress indicator */}
      {status === 'running' && data.currentIteration !== undefined && (
        <div className="mt-2">
          <div className="flex justify-between text-xs text-gray-500 mb-1">
            <span>Iteration</span>
            <span>{data.currentIteration + 1} / {data.totalIterations || '?'}</span>
          </div>
          <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-pink-500 transition-all"
              style={{
                width: data.totalIterations
                  ? `${((data.currentIteration + 1) / data.totalIterations) * 100}%`
                  : '50%'
              }}
            />
          </div>
        </div>
      )}

      {/* Completed stats */}
      {status === 'completed' && data.completedIterations !== undefined && (
        <div className="mt-2 text-xs text-emerald-400">
          ✓ {data.completedIterations} iterations
        </div>
      )}

      {/* Loop body output handle */}
      <Handle
        type="source"
        position={Position.Right}
        id="loop-body"
        className="w-3 h-3 bg-pink-400 border-2 border-pink-200"
        style={{ top: '50%' }}
      />

      {/* Completion output handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="completed"
        className="w-3 h-3 bg-pink-500 border-2 border-pink-300"
      />

      {/* Handle labels */}
      <div className="absolute right-0 top-1/2 transform translate-x-full -translate-y-1/2 text-[10px] text-pink-400 ml-1 whitespace-nowrap pl-2">
        each
      </div>
      <div className="absolute bottom-0 left-1/2 transform -translate-x-1/2 translate-y-full text-[10px] text-pink-400 pt-1">
        done
      </div>
    </div>
  );
}
