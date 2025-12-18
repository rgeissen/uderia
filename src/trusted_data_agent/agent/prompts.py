# trusted_data_agent/agent/prompts.py
"""
BACKWARD COMPATIBILITY WRAPPER

This module now provides backward compatibility for the database-backed prompt system.
All prompts are loaded from the database via PromptLoader instead of prompts.dat.

Legacy code can continue to import prompts as before:
    from trusted_data_agent.agent.prompts import MASTER_SYSTEM_PROMPT

The old prompts.dat file is no longer used. All prompt content is managed in tda_auth.db.
"""

import logging
from trusted_data_agent.agent.prompt_loader import get_prompt_loader

# Initialize a logger for this module.
app_logger = logging.getLogger("quart.app")

# Initialize the prompt loader (this will verify the license on import)
try:
    _loader = get_prompt_loader()
    app_logger.info("PromptLoader initialized successfully with database backend")
except Exception as e:
    app_logger.critical(f"Failed to initialize PromptLoader: {e}")
    raise

# --- Prompt Definitions ---
# These variables maintain backward compatibility with existing code
# They now load from the database instead of prompts.dat

MASTER_SYSTEM_PROMPT = _loader.get_prompt("MASTER_SYSTEM_PROMPT")
GOOGLE_MASTER_SYSTEM_PROMPT = _loader.get_prompt("GOOGLE_MASTER_SYSTEM_PROMPT")
OLLAMA_MASTER_SYSTEM_PROMPT = _loader.get_prompt("OLLAMA_MASTER_SYSTEM_PROMPT")

PROVIDER_SYSTEM_PROMPTS = {
    "Google": GOOGLE_MASTER_SYSTEM_PROMPT,
    "Anthropic": MASTER_SYSTEM_PROMPT,
    "Amazon": MASTER_SYSTEM_PROMPT,
    "OpenAI": MASTER_SYSTEM_PROMPT,
    "Azure": MASTER_SYSTEM_PROMPT,
    "Friendli": MASTER_SYSTEM_PROMPT,
    "Ollama": OLLAMA_MASTER_SYSTEM_PROMPT
}

G2PLOT_GUIDELINES = _loader.get_prompt("G2PLOT_GUIDELINES")
# Note: CHARTING_INSTRUCTIONS was not migrated (not in prompts.dat)
CHARTING_INSTRUCTIONS = {}

ERROR_RECOVERY_PROMPT = _loader.get_prompt("ERROR_RECOVERY_PROMPT")
TACTICAL_SELF_CORRECTION_PROMPT = _loader.get_prompt("TACTICAL_SELF_CORRECTION_PROMPT")
TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR = _loader.get_prompt("TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR")
TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR = _loader.get_prompt("TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR")
TASK_CLASSIFICATION_PROMPT = _loader.get_prompt("TASK_CLASSIFICATION_PROMPT")
WORKFLOW_META_PLANNING_PROMPT = _loader.get_prompt("WORKFLOW_META_PLANNING_PROMPT")
WORKFLOW_TACTICAL_PROMPT = _loader.get_prompt("WORKFLOW_TACTICAL_PROMPT")
SQL_CONSOLIDATION_PROMPT = _loader.get_prompt("SQL_CONSOLIDATION_PROMPT")

# Expose the loader for advanced use cases
prompt_loader = _loader
