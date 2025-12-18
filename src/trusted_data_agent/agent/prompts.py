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

# --- Lazy-Loading Prompt Definitions ---
# These variables maintain backward compatibility with existing code
# They now load from the database on first access (lazy loading for bootstrap)

class LazyPrompt:
    """Lazy-loading wrapper for database prompts.
    
    Handles both string prompts and JSON dict prompts (like CHARTING_INSTRUCTIONS).
    """
    def __init__(self, name: str):
        self._name = name
        self._cached = None
        self._is_dict = None
    
    def _load(self):
        """Load and cache the prompt from database."""
        if self._cached is None:
            import json
            content = _loader.get_prompt(self._name)
            # Try to parse as JSON dict
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    self._cached = parsed
                    self._is_dict = True
                else:
                    self._cached = content
                    self._is_dict = False
            except (json.JSONDecodeError, TypeError):
                self._cached = content
                self._is_dict = False
        return self._cached
    
    def __str__(self):
        """Return string representation."""
        result = self._load()
        if self._is_dict:
            import json
            return json.dumps(result)
        return result
    
    def format(self, **kwargs):
        """Support .format() calls on the lazy prompt."""
        return str(self).format(**kwargs)
    
    def get(self, key, default=None):
        """Support dict .get() for dict prompts like CHARTING_INSTRUCTIONS."""
        result = self._load()
        if self._is_dict:
            return result.get(key, default)
        raise AttributeError(f"'{self._name}' is not a dict prompt")
    
    def __bool__(self):
        """Support truthiness checks."""
        try:
            return bool(self._load())
        except:
            return False

def _get_prompt_lazy(name: str):
    """Create a lazy-loading proxy for a prompt."""
    return LazyPrompt(name)

# For backward compatibility, expose as module-level variables
# These will be None during bootstrap, populated once database is ready
MASTER_SYSTEM_PROMPT = _get_prompt_lazy("MASTER_SYSTEM_PROMPT")
GOOGLE_MASTER_SYSTEM_PROMPT = _get_prompt_lazy("GOOGLE_MASTER_SYSTEM_PROMPT")
OLLAMA_MASTER_SYSTEM_PROMPT = _get_prompt_lazy("OLLAMA_MASTER_SYSTEM_PROMPT")

PROVIDER_SYSTEM_PROMPTS = {
    "Google": GOOGLE_MASTER_SYSTEM_PROMPT,
    "Anthropic": MASTER_SYSTEM_PROMPT,
    "Amazon": MASTER_SYSTEM_PROMPT,
    "OpenAI": MASTER_SYSTEM_PROMPT,
    "Azure": MASTER_SYSTEM_PROMPT,
    "Friendli": MASTER_SYSTEM_PROMPT,
    "Ollama": OLLAMA_MASTER_SYSTEM_PROMPT
}

G2PLOT_GUIDELINES = _get_prompt_lazy("G2PLOT_GUIDELINES")
CHARTING_INSTRUCTIONS = _get_prompt_lazy("CHARTING_INSTRUCTIONS") or {}

ERROR_RECOVERY_PROMPT = _get_prompt_lazy("ERROR_RECOVERY_PROMPT")
TACTICAL_SELF_CORRECTION_PROMPT = _get_prompt_lazy("TACTICAL_SELF_CORRECTION_PROMPT")
TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR = _get_prompt_lazy("TACTICAL_SELF_CORRECTION_PROMPT_COLUMN_ERROR")
TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR = _get_prompt_lazy("TACTICAL_SELF_CORRECTION_PROMPT_TABLE_ERROR")
TASK_CLASSIFICATION_PROMPT = _get_prompt_lazy("TASK_CLASSIFICATION_PROMPT")
WORKFLOW_META_PLANNING_PROMPT = _get_prompt_lazy("WORKFLOW_META_PLANNING_PROMPT")
WORKFLOW_TACTICAL_PROMPT = _get_prompt_lazy("WORKFLOW_TACTICAL_PROMPT")
SQL_CONSOLIDATION_PROMPT = _get_prompt_lazy("SQL_CONSOLIDATION_PROMPT")

# Expose the loader for advanced use cases
prompt_loader = _loader
