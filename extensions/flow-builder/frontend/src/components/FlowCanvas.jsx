import React, { useCallback, useMemo, useRef } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useReactFlow
} from 'reactflow';
import { useFlowStore } from '../store/flowStore';

// Custom node components
import StartNode from './nodes/StartNode';
import EndNode from './nodes/EndNode';
import ProfileNode from './nodes/ProfileNode';
import ConditionNode from './nodes/ConditionNode';
import MergeNode from './nodes/MergeNode';
import TransformNode from './nodes/TransformNode';
import LoopNode from './nodes/LoopNode';
import HumanNode from './nodes/HumanNode';
import ParallelNode from './nodes/ParallelNode';

// Node types registry
const nodeTypes = {
  start: StartNode,
  end: EndNode,
  profile: ProfileNode,
  condition: ConditionNode,
  merge: MergeNode,
  transform: TransformNode,
  loop: LoopNode,
  human: HumanNode,
  parallel: ParallelNode
};

export default function FlowCanvas() {
  const reactFlowWrapper = useRef(null);
  const { screenToFlowPosition } = useReactFlow();

  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    addNode,
    setSelectedNode,
    setSelectedEdge,
    clearSelection,
    nodeStatuses
  } = useFlowStore();

  // Add execution status to nodes
  const nodesWithStatus = useMemo(() => {
    return nodes.map(node => ({
      ...node,
      data: {
        ...node.data,
        executionStatus: nodeStatuses[node.id] || null
      }
    }));
  }, [nodes, nodeStatuses]);

  // Handle drag over for palette drag-and-drop
  const onDragOver = useCallback((event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  // Handle drop from palette
  const onDrop = useCallback((event) => {
    event.preventDefault();

    const nodeTypeData = event.dataTransfer.getData('application/reactflow');
    if (!nodeTypeData) return;

    const { type, data } = JSON.parse(nodeTypeData);

    // Get position where node was dropped
    const position = screenToFlowPosition({
      x: event.clientX,
      y: event.clientY
    });

    addNode({
      type,
      position,
      data: {
        label: data?.label || type.charAt(0).toUpperCase() + type.slice(1),
        ...data
      }
    });
  }, [screenToFlowPosition, addNode]);

  // Handle node selection
  const onNodeClick = useCallback((_, node) => {
    setSelectedNode(node.id);
  }, [setSelectedNode]);

  // Handle edge selection
  const onEdgeClick = useCallback((_, edge) => {
    setSelectedEdge(edge.id);
  }, [setSelectedEdge]);

  // Handle pane click (deselect)
  const onPaneClick = useCallback(() => {
    clearSelection();
  }, [clearSelection]);

  // Double-click to add node
  const onPaneDoubleClick = useCallback((event) => {
    const position = screenToFlowPosition({
      x: event.clientX,
      y: event.clientY
    });

    // Add a profile node by default
    addNode({
      type: 'profile',
      position,
      data: {
        label: 'New Profile',
        profileType: 'tool_enabled'
      }
    });
  }, [screenToFlowPosition, addNode]);

  // Validate connections
  const isValidConnection = useCallback((connection) => {
    // Prevent self-connections
    if (connection.source === connection.target) return false;

    // Prevent duplicate connections
    const existingEdge = edges.find(
      edge => edge.source === connection.source && edge.target === connection.target
    );
    if (existingEdge) return false;

    return true;
  }, [edges]);

  return (
    <div ref={reactFlowWrapper} className="w-full h-full">
      <ReactFlow
        nodes={nodesWithStatus}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onEdgeClick={onEdgeClick}
        onPaneClick={onPaneClick}
        onPaneDoubleClick={onPaneDoubleClick}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={nodeTypes}
        isValidConnection={isValidConnection}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        defaultEdgeOptions={{
          type: 'smoothstep',
          animated: false
        }}
        connectionLineStyle={{ stroke: '#F15F22', strokeWidth: 2 }}
        connectionLineType="smoothstep"
        proOptions={{ hideAttribution: true }}
        className="bg-uderia-bg"
      >
        <Background
          color="#333"
          gap={20}
          size={1}
        />
        <Controls
          className="bg-gray-800 border border-white/10 rounded"
        />
        <MiniMap
          nodeColor={(node) => {
            switch (node.type) {
              case 'start': return '#10b981';
              case 'end': return '#ef4444';
              case 'profile': return '#9333ea';
              case 'condition': return '#06b6d4';
              case 'merge': return '#8b5cf6';
              case 'transform': return '#6366f1';
              case 'loop': return '#ec4899';
              case 'human': return '#f59e0b';
              case 'parallel': return '#14b8a6';
              default: return '#6b7280';
            }
          }}
          maskColor="rgba(0, 0, 0, 0.8)"
          className="bg-gray-900/80 border border-white/10 rounded"
        />
      </ReactFlow>
    </div>
  );
}
