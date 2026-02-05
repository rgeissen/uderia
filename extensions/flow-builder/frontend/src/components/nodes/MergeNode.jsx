import React from 'react';
import { Handle, Position } from 'reactflow';

export default function MergeNode({ data, selected }) {
  const status = data.executionStatus;

  return (
    <div
      className={`
        relative px-4 py-3 rounded-lg border-2 min-w-[140px] text-center
        bg-gray-900/90 border-violet-500
        ${selected ? 'ring-2 ring-violet-400 ring-offset-2 ring-offset-gray-900' : ''}
        ${status === 'running' ? 'animate-pulse' : ''}
        ${status === 'completed' ? 'border-emerald-400' : ''}
        ${status === 'error' ? 'border-rose-500' : ''}
      `}
    >
      {/* Multiple input handles */}
      <Handle
        type="target"
        position={Position.Top}
        id="input-1"
        className="w-3 h-3 bg-violet-500 border-2 border-violet-300"
        style={{ left: '30%' }}
      />
      <Handle
        type="target"
        position={Position.Top}
        id="input-2"
        className="w-3 h-3 bg-violet-500 border-2 border-violet-300"
        style={{ left: '70%' }}
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

      {/* Icon */}
      <div className="text-violet-400 text-xl mb-1">⊕</div>

      {/* Label */}
      <div className="text-sm font-medium text-white">{data.label || 'Merge'}</div>

      {/* Strategy */}
      {data.strategy && (
        <div className="text-xs text-gray-500 mt-1">{data.strategy}</div>
      )}

      {/* Waiting indicator */}
      {status === 'running' && data.waitingFor && (
        <div className="text-xs text-amber-400 mt-1">
          Waiting: {data.waitingFor}/{data.totalInputs}
        </div>
      )}

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-violet-500 border-2 border-violet-300"
      />
    </div>
  );
}
