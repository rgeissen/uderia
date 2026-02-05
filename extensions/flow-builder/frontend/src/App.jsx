import React, { useEffect, useCallback } from 'react';
import { ReactFlowProvider } from 'reactflow';
import FlowCanvas from './components/FlowCanvas';
import NodePalette from './components/NodePalette';
import ExecutionPanel from './components/ExecutionPanel';
import FlowToolbar from './components/FlowToolbar';
import { useFlowStore } from './store/flowStore';
import { flowApi } from './api/flowApi';
import 'reactflow/dist/style.css';

export default function App({ jwtToken, uderiaUrl, flowBuilderUrl }) {
  const {
    setConfig,
    setProfiles,
    setProfilesLoading,
    setFlows,
    setFlowsLoading,
    setTemplates,
    isPaletteExpanded,
    isExecutionPanelExpanded
  } = useFlowStore();

  // Initialize configuration
  useEffect(() => {
    setConfig({ jwtToken, uderiaUrl, flowBuilderUrl });
  }, [jwtToken, uderiaUrl, flowBuilderUrl, setConfig]);

  // Load profiles from Uderia
  const loadProfiles = useCallback(async () => {
    if (!jwtToken) return;

    setProfilesLoading(true);
    try {
      const profiles = await flowApi.getProfiles(flowBuilderUrl, jwtToken);
      setProfiles(profiles);
    } catch (error) {
      console.error('Failed to load profiles:', error);
    } finally {
      setProfilesLoading(false);
    }
  }, [jwtToken, flowBuilderUrl, setProfiles, setProfilesLoading]);

  // Load flows
  const loadFlows = useCallback(async () => {
    if (!jwtToken) return;

    setFlowsLoading(true);
    try {
      const flows = await flowApi.listFlows(flowBuilderUrl, jwtToken);
      setFlows(flows);
    } catch (error) {
      console.error('Failed to load flows:', error);
    } finally {
      setFlowsLoading(false);
    }
  }, [jwtToken, flowBuilderUrl, setFlows, setFlowsLoading]);

  // Load templates
  const loadTemplates = useCallback(async () => {
    if (!jwtToken) return;

    try {
      const templates = await flowApi.listTemplates(flowBuilderUrl, jwtToken);
      setTemplates(templates);
    } catch (error) {
      console.error('Failed to load templates:', error);
    }
  }, [jwtToken, flowBuilderUrl, setTemplates]);

  // Load data on mount
  useEffect(() => {
    loadProfiles();
    loadFlows();
    loadTemplates();
  }, [loadProfiles, loadFlows, loadTemplates]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Cmd/Ctrl + S - Save
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        // Trigger save (handled by FlowToolbar)
        document.dispatchEvent(new CustomEvent('flow-save'));
      }
      // Cmd/Ctrl + Enter - Run
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        document.dispatchEvent(new CustomEvent('flow-run'));
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  if (!jwtToken) {
    return (
      <div className="h-full flex items-center justify-center bg-uderia-bg text-white">
        <div className="text-center">
          <h2 className="text-xl font-bold mb-2">Authentication Required</h2>
          <p className="text-gray-400">Please log in to Uderia to use the Flow Builder.</p>
        </div>
      </div>
    );
  }

  return (
    <ReactFlowProvider>
      <div className="h-full flex flex-col bg-uderia-bg">
        {/* Header / Toolbar */}
        <FlowToolbar onFlowsChange={loadFlows} />

        {/* Main content area */}
        <div className="flex-1 flex overflow-hidden">
          {/* Left panel - Node Palette */}
          <div
            className={`${isPaletteExpanded ? 'w-64' : 'w-12'} transition-all duration-200 flex-shrink-0 border-r border-white/10`}
          >
            <NodePalette />
          </div>

          {/* Center - Canvas */}
          <div className="flex-1 relative">
            <FlowCanvas />
          </div>

          {/* Right panel - Execution Status */}
          <div
            className={`${isExecutionPanelExpanded ? 'w-80' : 'w-12'} transition-all duration-200 flex-shrink-0 border-l border-white/10`}
          >
            <ExecutionPanel />
          </div>
        </div>

        {/* Status bar */}
        <div className="h-6 flex items-center px-4 text-xs text-gray-500 border-t border-white/10 bg-gray-900/50">
          <span>Nodes: {useFlowStore.getState().nodes.length}</span>
          <span className="mx-2">|</span>
          <span>Edges: {useFlowStore.getState().edges.length}</span>
          {useFlowStore.getState().isDirty && (
            <>
              <span className="mx-2">|</span>
              <span className="text-amber-400">Unsaved changes</span>
            </>
          )}
        </div>
      </div>
    </ReactFlowProvider>
  );
}
