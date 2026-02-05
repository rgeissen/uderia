import React from 'react';
import { Handle, Position } from 'reactflow';

export default function HumanNode({ data, selected }) {
  const status = data.executionStatus;

  return (
    <div
      className={`
        relative px-4 py-3 rounded-lg border-2 min-w-[180px]
        bg-gray-900/90 border-amber-500
        ${selected ? 'ring-2 ring-amber-400 ring-offset-2 ring-offset-gray-900' : ''}
        ${status === 'running' ? 'animate-pulse border-amber-400' : ''}
        ${status === 'completed' ? 'border-emerald-400' : ''}
        ${status === 'error' ? 'border-rose-500' : ''}
      `}
    >
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-amber-500 border-2 border-amber-300"
      />

      {/* Status indicator */}
      {status && (
        <div className="absolute -top-1 -right-1">
          {status === 'running' && (
            <div className="w-4 h-4 rounded-full bg-amber-400 flex items-center justify-center animate-bounce">
              <span className="text-amber-900 text-xs">!</span>
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
        <div className="w-8 h-8 rounded-full bg-amber-500/20 flex items-center justify-center text-lg">
          👤
        </div>
        <div>
          <div className="text-sm font-medium text-white">{data.label || 'Human Input'}</div>
          <div className="text-xs text-gray-500">{data.inputType || 'text'}</div>
        </div>
      </div>

      {/* Prompt */}
      {data.prompt && (
        <div className="p-2 bg-gray-800/50 rounded text-xs text-gray-400 mb-2">
          {data.prompt.length > 50 ? data.prompt.slice(0, 50) + '...' : data.prompt}
        </div>
      )}

      {/* Choices for choice input type */}
      {data.inputType === 'choice' && data.choices && (
        <div className="flex flex-wrap gap-1 mb-2">
          {data.choices.slice(0, 3).map((choice, i) => (
            <span
              key={i}
              className="px-2 py-0.5 bg-amber-500/20 rounded text-xs text-amber-400"
            >
              {choice}
            </span>
          ))}
          {data.choices.length > 3 && (
            <span className="text-xs text-gray-500">+{data.choices.length - 3} more</span>
          )}
        </div>
      )}

      {/* Waiting state */}
      {status === 'running' && (
        <div className="p-2 bg-amber-500/10 border border-amber-500/30 rounded text-xs text-amber-400 text-center">
          ⏳ Waiting for response...
          {data.timeout && (
            <div className="text-amber-400/60 mt-1">
              Timeout: {Math.floor(data.timeout / 60)}m
            </div>
          )}
        </div>
      )}

      {/* Response received */}
      {status === 'completed' && data.userResponse && (
        <div className="p-2 bg-emerald-500/10 border border-emerald-500/30 rounded text-xs text-emerald-400">
          Response: {data.userResponse.slice(0, 30)}{data.userResponse.length > 30 ? '...' : ''}
        </div>
      )}

      {/* Timeout indicator */}
      {data.timeout && status !== 'running' && status !== 'completed' && (
        <div className="text-xs text-gray-500 mt-1">
          Timeout: {Math.floor(data.timeout / 60)}m
        </div>
      )}

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-amber-500 border-2 border-amber-300"
      />
    </div>
  );
}
