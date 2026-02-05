import { create } from 'zustand';
import { addEdge, applyNodeChanges, applyEdgeChanges } from 'reactflow';

const initialNodes = [];
const initialEdges = [];

export const useFlowStore = create((set, get) => ({
  // Flow data
  nodes: initialNodes,
  edges: initialEdges,
  flowId: null,
  flowName: 'Untitled Flow',
  flowDescription: '',
  isDirty: false,

  // Execution state
  executionId: null,
  executionStatus: null, // null, 'running', 'completed', 'failed'
  executionEvents: [],
  nodeStatuses: {}, // nodeId -> status

  // UI state
  selectedNode: null,
  selectedEdge: null,
  isPaletteExpanded: true,
  isExecutionPanelExpanded: true,

  // Available profiles (from Uderia)
  profiles: [],
  profilesLoading: false,

  // Available flows
  flows: [],
  flowsLoading: false,

  // Templates
  templates: [],

  // Config
  jwtToken: null,
  uderiaUrl: 'http://localhost:5050',
  flowBuilderUrl: 'http://localhost:5051',

  // Actions - Configuration
  setConfig: (config) => set({
    jwtToken: config.jwtToken,
    uderiaUrl: config.uderiaUrl || 'http://localhost:5050',
    flowBuilderUrl: config.flowBuilderUrl || 'http://localhost:5051'
  }),

  // Actions - Node/Edge management
  onNodesChange: (changes) => {
    set({
      nodes: applyNodeChanges(changes, get().nodes),
      isDirty: true
    });
  },

  onEdgesChange: (changes) => {
    set({
      edges: applyEdgeChanges(changes, get().edges),
      isDirty: true
    });
  },

  onConnect: (connection) => {
    set({
      edges: addEdge({
        ...connection,
        id: `e-${connection.source}-${connection.target}-${Date.now()}`,
        type: 'smoothstep',
        animated: false
      }, get().edges),
      isDirty: true
    });
  },

  addNode: (node) => {
    const newNode = {
      ...node,
      id: node.id || `node-${Date.now()}`,
      position: node.position || { x: 250, y: 100 }
    };
    set({
      nodes: [...get().nodes, newNode],
      isDirty: true
    });
    return newNode;
  },

  updateNode: (nodeId, data) => {
    set({
      nodes: get().nodes.map(node =>
        node.id === nodeId
          ? { ...node, data: { ...node.data, ...data } }
          : node
      ),
      isDirty: true
    });
  },

  deleteNode: (nodeId) => {
    set({
      nodes: get().nodes.filter(n => n.id !== nodeId),
      edges: get().edges.filter(e => e.source !== nodeId && e.target !== nodeId),
      selectedNode: get().selectedNode === nodeId ? null : get().selectedNode,
      isDirty: true
    });
  },

  // Actions - Selection
  setSelectedNode: (nodeId) => set({ selectedNode: nodeId, selectedEdge: null }),
  setSelectedEdge: (edgeId) => set({ selectedEdge: edgeId, selectedNode: null }),
  clearSelection: () => set({ selectedNode: null, selectedEdge: null }),

  // Actions - Flow management
  newFlow: () => {
    set({
      nodes: [],
      edges: [],
      flowId: null,
      flowName: 'Untitled Flow',
      flowDescription: '',
      isDirty: false,
      executionId: null,
      executionStatus: null,
      executionEvents: [],
      nodeStatuses: {},
      selectedNode: null,
      selectedEdge: null
    });
  },

  loadFlow: (flow) => {
    const definition = flow.definition || { nodes: [], edges: [] };
    set({
      flowId: flow.id,
      flowName: flow.name,
      flowDescription: flow.description || '',
      nodes: definition.nodes || [],
      edges: definition.edges || [],
      isDirty: false,
      executionId: null,
      executionStatus: null,
      executionEvents: [],
      nodeStatuses: {},
      selectedNode: null,
      selectedEdge: null
    });
  },

  setFlowName: (name) => set({ flowName: name, isDirty: true }),
  setFlowDescription: (description) => set({ flowDescription: description, isDirty: true }),

  getFlowDefinition: () => ({
    nodes: get().nodes,
    edges: get().edges
  }),

  // Actions - Execution
  setExecutionId: (id) => set({ executionId: id }),
  setExecutionStatus: (status) => set({ executionStatus: status }),

  addExecutionEvent: (event) => {
    set(state => ({
      executionEvents: [...state.executionEvents, event]
    }));

    // Update node status based on event
    const { event: eventType, node_id } = event;
    if (node_id) {
      if (eventType === 'flow_node_started') {
        get().setNodeStatus(node_id, 'running');
      } else if (eventType === 'flow_node_completed') {
        get().setNodeStatus(node_id, 'completed');
      } else if (eventType === 'flow_node_error') {
        get().setNodeStatus(node_id, 'error');
      } else if (eventType === 'flow_node_skipped') {
        get().setNodeStatus(node_id, 'skipped');
      }
    }
  },

  clearExecutionEvents: () => set({
    executionEvents: [],
    nodeStatuses: {},
    executionStatus: null
  }),

  setNodeStatus: (nodeId, status) => {
    set(state => ({
      nodeStatuses: { ...state.nodeStatuses, [nodeId]: status }
    }));
  },

  // Actions - Profiles
  setProfiles: (profiles) => set({ profiles }),
  setProfilesLoading: (loading) => set({ profilesLoading: loading }),

  // Actions - Flows list
  setFlows: (flows) => set({ flows }),
  setFlowsLoading: (loading) => set({ flowsLoading: loading }),

  // Actions - Templates
  setTemplates: (templates) => set({ templates }),

  // Actions - UI
  togglePalette: () => set(state => ({ isPaletteExpanded: !state.isPaletteExpanded })),
  toggleExecutionPanel: () => set(state => ({ isExecutionPanelExpanded: !state.isExecutionPanelExpanded })),

  // Mark as saved
  markSaved: () => set({ isDirty: false })
}));

export default useFlowStore;
