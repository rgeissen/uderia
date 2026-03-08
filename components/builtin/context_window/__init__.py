"""
Context Window system component.

Provides centralized context window management through a modular plugin system.
The orchestrator assembles context from pluggable modules (system prompt, tools,
history, RAG, knowledge, documents, etc.) using budget-aware allocation.

Phase 3 additions:
  - ContextBuilder: Single entry point for all LLM context assembly.
    Bridges the orchestrator's budget-aware module output to prompt
    template variables consumed by planner.py and phase_executor.py.
  - PromptContext: Return value from ContextBuilder.build() containing
    ready-to-use template_vars, content_blocks, and per-call snapshots.
"""
