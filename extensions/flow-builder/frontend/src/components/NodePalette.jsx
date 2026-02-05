import React from 'react';
import { useFlowStore } from '../store/flowStore';

// Node type definitions with icons and descriptions
const nodeCategories = [
  {
    name: 'Flow Control',
    nodes: [
      {
        type: 'start',
        label: 'Start',
        icon: '○',
        color: '#10b981',
        description: 'Flow entry point'
      },
      {
        type: 'end',
        label: 'End',
        icon: '●',
        color: '#ef4444',
        description: 'Flow exit point'
      }
    ]
  },
  {
    name: 'Execution',
    nodes: [
      {
        type: 'profile',
        label: 'Profile',
        icon: '◎',
        color: '#9333ea',
        description: 'Execute Uderia profile'
      },
      {
        type: 'transform',
        label: 'Transform',
        icon: '⚙',
        color: '#6366f1',
        description: 'Modify/filter data'
      }
    ]
  },
  {
    name: 'Logic',
    nodes: [
      {
        type: 'condition',
        label: 'Condition',
        icon: '◇',
        color: '#06b6d4',
        description: 'Branch based on expression'
      },
      {
        type: 'merge',
        label: 'Merge',
        icon: '⊕',
        color: '#8b5cf6',
        description: 'Combine multiple inputs'
      },
      {
        type: 'loop',
        label: 'Loop',
        icon: '↻',
        color: '#ec4899',
        description: 'Iterate over collection'
      }
    ]
  },
  {
    name: 'Advanced',
    nodes: [
      {
        type: 'human',
        label: 'Human',
        icon: '👤',
        color: '#f59e0b',
        description: 'Wait for user input'
      },
      {
        type: 'parallel',
        label: 'Parallel',
        icon: '⫴',
        color: '#14b8a6',
        description: 'Execute simultaneously'
      }
    ]
  }
];

function DraggableNode({ type, label, icon, color, description }) {
  const onDragStart = (event) => {
    event.dataTransfer.setData(
      'application/reactflow',
      JSON.stringify({ type, data: { label } })
    );
    event.dataTransfer.effectAllowed = 'move';
  };

  return (
    <div
      className="flex items-center gap-3 p-2 rounded-lg cursor-grab hover:bg-white/5 transition-colors border border-transparent hover:border-white/10"
      draggable
      onDragStart={onDragStart}
      title={description}
    >
      <div
        className="w-8 h-8 rounded-md flex items-center justify-center text-lg font-medium"
        style={{ backgroundColor: `${color}20`, color }}
      >
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-white truncate">{label}</div>
        <div className="text-xs text-gray-500 truncate">{description}</div>
      </div>
    </div>
  );
}

export default function NodePalette() {
  const { isPaletteExpanded, togglePalette, profiles, profilesLoading } = useFlowStore();

  // Handle dragging profiles directly to canvas
  const onProfileDragStart = (event, profile) => {
    event.dataTransfer.setData(
      'application/reactflow',
      JSON.stringify({
        type: 'profile',
        data: {
          label: profile.tag || profile.name,
          profileId: profile.id,
          profileTag: profile.tag,
          profileType: profile.profile_type
        }
      })
    );
    event.dataTransfer.effectAllowed = 'move';
  };

  if (!isPaletteExpanded) {
    return (
      <div className="h-full flex flex-col items-center py-4 bg-gray-900/50">
        <button
          onClick={togglePalette}
          className="p-2 rounded-lg hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
          title="Expand palette"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>

        {/* Vertical icons for collapsed state */}
        <div className="mt-4 space-y-2">
          {nodeCategories.flatMap(cat => cat.nodes).slice(0, 6).map(node => (
            <div
              key={node.type}
              className="w-8 h-8 rounded-md flex items-center justify-center text-sm cursor-grab hover:ring-2 ring-white/20"
              style={{ backgroundColor: `${node.color}20`, color: node.color }}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(
                  'application/reactflow',
                  JSON.stringify({ type: node.type, data: { label: node.label } })
                );
                e.dataTransfer.effectAllowed = 'move';
              }}
              title={node.label}
            >
              {node.icon}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-gray-900/50">
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-white/10">
        <h3 className="text-sm font-semibold text-white">Nodes</h3>
        <button
          onClick={togglePalette}
          className="p-1 rounded hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
          title="Collapse palette"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
      </div>

      {/* Node categories */}
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {nodeCategories.map(category => (
          <div key={category.name}>
            <h4 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
              {category.name}
            </h4>
            <div className="space-y-1">
              {category.nodes.map(node => (
                <DraggableNode key={node.type} {...node} />
              ))}
            </div>
          </div>
        ))}

        {/* Profiles section */}
        <div>
          <h4 className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-2">
            Profiles
          </h4>
          {profilesLoading ? (
            <div className="text-xs text-gray-500 p-2">Loading profiles...</div>
          ) : profiles.length === 0 ? (
            <div className="text-xs text-gray-500 p-2">No profiles available</div>
          ) : (
            <div className="space-y-1">
              {profiles.map(profile => {
                const profileColors = {
                  tool_enabled: '#9333ea',
                  llm_only: '#4ade80',
                  rag_focused: '#3b82f6',
                  genie: '#F15F22'
                };
                const color = profileColors[profile.profile_type] || '#6b7280';

                return (
                  <div
                    key={profile.id}
                    className="flex items-center gap-3 p-2 rounded-lg cursor-grab hover:bg-white/5 transition-colors border border-transparent hover:border-white/10"
                    draggable
                    onDragStart={(e) => onProfileDragStart(e, profile)}
                    title={`${profile.profile_type} profile`}
                  >
                    <div
                      className="w-8 h-8 rounded-md flex items-center justify-center text-xs font-bold"
                      style={{ backgroundColor: `${color}20`, color }}
                    >
                      {(profile.tag || profile.name || '?').charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-white truncate">
                        {profile.tag || profile.name}
                      </div>
                      <div className="text-xs text-gray-500 truncate">
                        {profile.profile_type}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Help text */}
      <div className="p-3 border-t border-white/10">
        <p className="text-xs text-gray-500">
          Drag nodes to canvas or double-click to add
        </p>
      </div>
    </div>
  );
}
