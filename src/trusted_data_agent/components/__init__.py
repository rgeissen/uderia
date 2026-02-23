"""
Generative UI Component Library.

Provides a modular, pluggable component system for rendering LLM output
through specialized visual components (charts, tables, code editors, etc.).

Components are:
  - Toggled per-profile and dynamically injected into the LLM prompt
  - Signaled by the LLM via tool calls (TDA_Charting, TDA_CodeEditor, etc.)
  - Rendered client-side by a frontend ComponentRendererRegistry
  - Extensible: third-party components from agent packs or user plugins

Usage::

    from trusted_data_agent.components.manager import get_component_manager

    manager = get_component_manager()
    handler = manager.get_handler("TDA_Charting")
    payload = await handler.process(arguments, context)
"""
