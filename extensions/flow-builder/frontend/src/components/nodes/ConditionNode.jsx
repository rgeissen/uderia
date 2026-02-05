import React from 'react';
import { Handle, Position } from 'reactflow';

export default function ConditionNode({ data, selected }) {
  const status = data.executionStatus;

  return (
    <div
      className={`
        relative
        ${selected ? 'filter drop-shadow-lg' : ''}
      `}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-cyan-500 border-2 border-cyan-300"
      />

      {/* Diamond shape using CSS transform */}
      <div
        className={`
          w-32 h-32 flex items-center justify-center
          bg-gray-900/90 border-2 border-cyan-500
          ${status === 'running' ? 'animate-pulse' : ''}
          ${status === 'completed' ? 'border-emerald-400' : ''}
          ${status === 'error' ? 'border-rose-500' : ''}
        `}
        style={{ transform: 'rotate(45deg)' }}
      >
        <div style={{ transform: 'rotate(-45deg)' }} className="text-center p-2">
          {/* Status indicator */}
          {status && (
            <div className="absolute top-0 right-0" style={{ transform: 'rotate(-45deg) translate(8px, -8px)' }}>
              {status === 'running' && (
                <div className="w-3 h-3 rounded-full bg-amber-400 animate-pulse" />
              )}
              {status === 'completed' && (
                <div className="w-3 h-3 rounded-full bg-emerald-400" />
              )}
              {status === 'error' && (
                <div className="w-3 h-3 rounded-full bg-rose-500" />
              )}
            </div>
          )}

          {/* Icon */}
          <div className="text-cyan-400 text-lg mb-1">◇</div>

          {/* Label */}
          <div className="text-xs font-medium text-white truncate max-w-[80px]">
            {data.label || 'Condition'}
          </div>

          {/* Expression preview */}
          {data.expression && (
            <div className="text-[10px] text-gray-500 truncate max-w-[80px] mt-1">
              {data.expression.length > 15 ? data.expression.slice(0, 15) + '...' : data.expression}
            </div>
          )}

          {/* Branch result */}
          {status === 'completed' && data.branchTaken !== undefined && (
            <div className={`text-[10px] mt-1 ${data.branchTaken ? 'text-emerald-400' : 'text-rose-400'}`}>
              → {data.branchTaken ? 'TRUE' : 'FALSE'}
            </div>
          )}
        </div>
      </div>

      {/* True output handle (bottom-left) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="true"
        className="w-3 h-3 bg-emerald-500 border-2 border-emerald-300"
        style={{ left: '25%' }}
      />

      {/* False output handle (bottom-right) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        className="w-3 h-3 bg-rose-500 border-2 border-rose-300"
        style={{ left: '75%' }}
      />

      {/* Branch labels */}
      <div className="absolute -bottom-5 left-0 w-full flex justify-between px-2 text-[10px]">
        <span className="text-emerald-400">{data.trueLabel || 'True'}</span>
        <span className="text-rose-400">{data.falseLabel || 'False'}</span>
      </div>
    </div>
  );
}
