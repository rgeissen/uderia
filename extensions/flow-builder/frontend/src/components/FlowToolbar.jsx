import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useFlowStore } from '../store/flowStore';
import { flowApi } from '../api/flowApi';

export default function FlowToolbar({ onFlowsChange }) {
  const {
    flowId,
    flowName,
    flowDescription,
    isDirty,
    nodes,
    edges,
    flows,
    flowsLoading,
    templates,
    executionStatus,
    jwtToken,
    flowBuilderUrl,
    newFlow,
    loadFlow,
    setFlowName,
    setFlowDescription,
    getFlowDefinition,
    markSaved,
    setExecutionId,
    setExecutionStatus,
    addExecutionEvent,
    clearExecutionEvents
  } = useFlowStore();

  const [isFlowMenuOpen, setIsFlowMenuOpen] = useState(false);
  const [isTemplateMenuOpen, setIsTemplateMenuOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [showInputModal, setShowInputModal] = useState(false);
  const [flowInput, setFlowInput] = useState('');
  const [editingName, setEditingName] = useState(false);

  const flowMenuRef = useRef(null);
  const templateMenuRef = useRef(null);
  const abortControllerRef = useRef(null);

  // Close menus when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (flowMenuRef.current && !flowMenuRef.current.contains(event.target)) {
        setIsFlowMenuOpen(false);
      }
      if (templateMenuRef.current && !templateMenuRef.current.contains(event.target)) {
        setIsTemplateMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Listen for keyboard shortcuts
  useEffect(() => {
    const handleSaveEvent = () => handleSave();
    const handleRunEvent = () => {
      if (nodes.length > 0) {
        setShowInputModal(true);
      }
    };

    document.addEventListener('flow-save', handleSaveEvent);
    document.addEventListener('flow-run', handleRunEvent);
    return () => {
      document.removeEventListener('flow-save', handleSaveEvent);
      document.removeEventListener('flow-run', handleRunEvent);
    };
  }, [nodes]);

  const handleSave = useCallback(async () => {
    if (!jwtToken || isSaving) return;

    setIsSaving(true);
    try {
      const definition = getFlowDefinition();

      if (flowId) {
        // Update existing flow
        await flowApi.updateFlow(flowBuilderUrl, jwtToken, flowId, {
          name: flowName,
          description: flowDescription,
          definition
        });
      } else {
        // Create new flow
        const result = await flowApi.createFlow(flowBuilderUrl, jwtToken, {
          name: flowName,
          description: flowDescription,
          definition
        });
        // Load the created flow to get its ID
        loadFlow(result);
      }

      markSaved();
      onFlowsChange?.();
    } catch (error) {
      console.error('Failed to save flow:', error);
      alert(`Failed to save: ${error.message}`);
    } finally {
      setIsSaving(false);
    }
  }, [jwtToken, flowId, flowName, flowDescription, isSaving, flowBuilderUrl, getFlowDefinition, markSaved, loadFlow, onFlowsChange]);

  const handleRun = useCallback(async () => {
    if (!jwtToken || !flowId || isRunning) return;

    setIsRunning(true);
    clearExecutionEvents();
    setExecutionStatus('running');
    setShowInputModal(false);

    try {
      // Start execution
      const result = await flowApi.executeFlow(flowBuilderUrl, jwtToken, flowId, flowInput);
      setExecutionId(result.execution_id);

      // Connect to SSE stream
      abortControllerRef.current = flowApi.streamExecution(
        flowBuilderUrl,
        jwtToken,
        result.execution_id,
        (eventType, data) => {
          addExecutionEvent({
            type: eventType,
            ...data,
            timestamp: new Date().toISOString()
          });

          // Update execution status based on events
          if (eventType === 'flow_execution_completed') {
            setExecutionStatus('completed');
          } else if (eventType === 'flow_execution_failed') {
            setExecutionStatus('failed');
          }
        },
        (error) => {
          console.error('Stream error:', error);
          setExecutionStatus('failed');
          addExecutionEvent({
            type: 'flow_execution_failed',
            error: error.message,
            timestamp: new Date().toISOString()
          });
        },
        () => {
          setIsRunning(false);
        }
      );
    } catch (error) {
      console.error('Failed to run flow:', error);
      setExecutionStatus('failed');
      addExecutionEvent({
        type: 'flow_execution_failed',
        error: error.message,
        timestamp: new Date().toISOString()
      });
      setIsRunning(false);
    }
  }, [jwtToken, flowId, flowInput, isRunning, flowBuilderUrl, clearExecutionEvents, setExecutionId, setExecutionStatus, addExecutionEvent]);

  const handleStop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current();
      abortControllerRef.current = null;
    }
    setIsRunning(false);
    setExecutionStatus('cancelled');
  }, [setExecutionStatus]);

  const handleNewFlow = () => {
    if (isDirty && !confirm('You have unsaved changes. Create new flow anyway?')) {
      return;
    }
    newFlow();
    setIsFlowMenuOpen(false);
  };

  const handleLoadFlow = async (flow) => {
    if (isDirty && !confirm('You have unsaved changes. Load another flow anyway?')) {
      return;
    }

    try {
      const fullFlow = await flowApi.getFlow(flowBuilderUrl, jwtToken, flow.id);
      loadFlow(fullFlow);
    } catch (error) {
      console.error('Failed to load flow:', error);
      alert(`Failed to load flow: ${error.message}`);
    }
    setIsFlowMenuOpen(false);
  };

  const handleDeleteFlow = async (flow, event) => {
    event.stopPropagation();
    if (!confirm(`Delete flow "${flow.name}"?`)) return;

    try {
      await flowApi.deleteFlow(flowBuilderUrl, jwtToken, flow.id);
      onFlowsChange?.();
      if (flowId === flow.id) {
        newFlow();
      }
    } catch (error) {
      console.error('Failed to delete flow:', error);
      alert(`Failed to delete: ${error.message}`);
    }
  };

  const handleCreateFromTemplate = async (template) => {
    if (isDirty && !confirm('You have unsaved changes. Create from template anyway?')) {
      return;
    }

    try {
      const result = await flowApi.createFromTemplate(
        flowBuilderUrl,
        jwtToken,
        template.id,
        `${template.name} Copy`,
        template.description
      );
      loadFlow(result);
      onFlowsChange?.();
    } catch (error) {
      console.error('Failed to create from template:', error);
      alert(`Failed to create from template: ${error.message}`);
    }
    setIsTemplateMenuOpen(false);
  };

  return (
    <>
      <div className="h-12 flex items-center px-4 border-b border-white/10 bg-gray-900/80">
        {/* Left section: Flow selector */}
        <div className="flex items-center gap-3">
          {/* Flow dropdown */}
          <div className="relative" ref={flowMenuRef}>
            <button
              onClick={() => setIsFlowMenuOpen(!isFlowMenuOpen)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-white/10 text-sm"
            >
              <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
              </svg>
              <span className="text-white max-w-[200px] truncate">
                {flowName}
              </span>
              {isDirty && <span className="text-amber-400">•</span>}
              <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {isFlowMenuOpen && (
              <div className="absolute top-full left-0 mt-1 w-72 bg-gray-800 border border-white/10 rounded-lg shadow-xl z-50">
                <div className="p-2 border-b border-white/10">
                  <button
                    onClick={handleNewFlow}
                    className="w-full flex items-center gap-2 px-3 py-2 rounded hover:bg-white/5 text-left"
                  >
                    <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    <span className="text-white">New Flow</span>
                  </button>
                </div>
                <div className="max-h-60 overflow-y-auto p-2">
                  {flowsLoading ? (
                    <div className="text-gray-500 text-sm p-2">Loading...</div>
                  ) : flows.length === 0 ? (
                    <div className="text-gray-500 text-sm p-2">No saved flows</div>
                  ) : (
                    flows.map(flow => (
                      <div
                        key={flow.id}
                        onClick={() => handleLoadFlow(flow)}
                        className={`flex items-center justify-between px-3 py-2 rounded cursor-pointer hover:bg-white/5 ${
                          flow.id === flowId ? 'bg-white/10' : ''
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="text-white text-sm truncate">{flow.name}</div>
                          <div className="text-gray-500 text-xs truncate">
                            {new Date(flow.updated_at).toLocaleDateString()}
                          </div>
                        </div>
                        <button
                          onClick={(e) => handleDeleteFlow(flow, e)}
                          className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-rose-400"
                        >
                          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Flow name edit */}
          {editingName ? (
            <input
              type="text"
              value={flowName}
              onChange={(e) => setFlowName(e.target.value)}
              onBlur={() => setEditingName(false)}
              onKeyDown={(e) => e.key === 'Enter' && setEditingName(false)}
              className="px-2 py-1 bg-gray-800 border border-white/20 rounded text-sm text-white focus:outline-none focus:border-orange-500"
              autoFocus
            />
          ) : (
            <button
              onClick={() => setEditingName(true)}
              className="p-1 rounded hover:bg-white/10 text-gray-400 hover:text-white"
              title="Rename flow"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
              </svg>
            </button>
          )}

          {/* Templates dropdown */}
          <div className="relative" ref={templateMenuRef}>
            <button
              onClick={() => setIsTemplateMenuOpen(!isTemplateMenuOpen)}
              className="p-1.5 rounded hover:bg-white/10 text-gray-400 hover:text-white"
              title="Templates"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
              </svg>
            </button>

            {isTemplateMenuOpen && (
              <div className="absolute top-full left-0 mt-1 w-64 bg-gray-800 border border-white/10 rounded-lg shadow-xl z-50">
                <div className="p-2 text-xs text-gray-500 uppercase tracking-wider border-b border-white/10">
                  Templates
                </div>
                <div className="max-h-60 overflow-y-auto p-2">
                  {templates.length === 0 ? (
                    <div className="text-gray-500 text-sm p-2">No templates available</div>
                  ) : (
                    templates.map(template => (
                      <div
                        key={template.id}
                        onClick={() => handleCreateFromTemplate(template)}
                        className="px-3 py-2 rounded cursor-pointer hover:bg-white/5"
                      >
                        <div className="text-white text-sm">{template.name}</div>
                        <div className="text-gray-500 text-xs">{template.description}</div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Center spacer */}
        <div className="flex-1" />

        {/* Right section: Actions */}
        <div className="flex items-center gap-2">
          {/* Validate button */}
          <button
            onClick={async () => {
              if (!flowId) {
                alert('Save the flow first to validate');
                return;
              }
              try {
                const result = await flowApi.validateFlow(flowBuilderUrl, jwtToken, flowId);
                if (result.valid) {
                  alert('Flow is valid!');
                } else {
                  alert(`Validation errors:\n${result.errors.join('\n')}`);
                }
              } catch (error) {
                alert(`Validation failed: ${error.message}`);
              }
            }}
            disabled={!flowId}
            className="px-3 py-1.5 rounded-lg text-sm text-gray-300 hover:text-white hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed"
            title="Validate flow"
          >
            Validate
          </button>

          {/* Save button */}
          <button
            onClick={handleSave}
            disabled={isSaving || !isDirty}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm bg-gray-700 hover:bg-gray-600 text-white disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isSaving ? (
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4" />
              </svg>
            )}
            Save
          </button>

          {/* Run/Stop button */}
          {isRunning ? (
            <button
              onClick={handleStop}
              className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm bg-rose-600 hover:bg-rose-500 text-white"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              Stop
            </button>
          ) : (
            <button
              onClick={() => {
                if (!flowId) {
                  alert('Save the flow first to run it');
                  return;
                }
                setShowInputModal(true);
              }}
              disabled={nodes.length === 0 || !flowId}
              className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm bg-orange-600 hover:bg-orange-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path d="M8 5v14l11-7z" />
              </svg>
              Run
            </button>
          )}
        </div>
      </div>

      {/* Input modal */}
      {showInputModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 border border-white/10 rounded-xl shadow-2xl w-full max-w-md p-6">
            <h3 className="text-lg font-semibold text-white mb-4">Run Flow</h3>
            <div className="mb-4">
              <label className="block text-sm text-gray-400 mb-2">Initial Input</label>
              <textarea
                value={flowInput}
                onChange={(e) => setFlowInput(e.target.value)}
                placeholder="Enter the initial query or data for the flow..."
                className="w-full h-32 px-3 py-2 bg-gray-900 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-orange-500 resize-none"
                autoFocus
              />
            </div>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowInputModal(false)}
                className="px-4 py-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/10"
              >
                Cancel
              </button>
              <button
                onClick={handleRun}
                className="px-4 py-2 rounded-lg bg-orange-600 hover:bg-orange-500 text-white"
              >
                Run Flow
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
