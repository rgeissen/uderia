"""
Context Window system component.

Provides centralized context window management through a modular plugin system.
The orchestrator assembles context from pluggable modules (system prompt, tools,
history, RAG, knowledge, documents, etc.) using budget-aware allocation.
"""
