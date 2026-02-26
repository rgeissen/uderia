# trusted_data_agent/agent/executor.py
import re
import json
import logging
import copy
import uuid
import time
# --- MODIFICATION START: Import asyncio ---
import asyncio
# --- MODIFICATION END ---
from enum import Enum, auto
from typing import Tuple, List, Optional, Dict, Any
# --- MODIFICATION START: Import datetime and timezone ---
from datetime import datetime, timezone
# --- MODIFICATION END ---

from trusted_data_agent.agent.formatter import OutputFormatter
from trusted_data_agent.core import session_manager
from trusted_data_agent.llm import handler as llm_handler
# --- MODIFICATION START: Import APP_CONFIG and APP_STATE ---
from trusted_data_agent.core.config import (
    APP_CONFIG, APP_STATE,
    get_user_provider, get_user_model, set_user_provider, set_user_model,
    set_user_aws_region, set_user_azure_deployment_details,
    set_user_friendli_details, set_user_model_provider_in_profile
)
# --- MODIFICATION END ---
from trusted_data_agent.agent.response_models import CanonicalResponse, PromptReportResponse
from trusted_data_agent.mcp_adapter import adapter as mcp_adapter


# Refactored components
from trusted_data_agent.agent.planner import Planner
from trusted_data_agent.agent.phase_executor import PhaseExecutor
from trusted_data_agent.agent.session_name_generator import generate_session_name_with_events


app_logger = logging.getLogger("quart.app")


def load_document_context(user_uuid: str, session_id: str, attachments: list) -> tuple[str | None, list[dict]]:
    """
    Load extracted text from uploaded documents and format as context block.

    This is a module-level function so it can be used by both PlanExecutor and
    the genie execution path.

    Args:
        user_uuid: The user's UUID
        session_id: The session ID
        attachments: List of attachment dicts with file_id, filename keys

    Returns:
        Tuple of (formatted document context string or None, list of truncation event dicts)
    """
    if not attachments:
        return None, []

    from pathlib import Path
    from trusted_data_agent.core.utils import get_project_root

    safe_user = "".join(c for c in user_uuid if c.isalnum() or c in ['-', '_'])
    safe_session = "".join(c for c in session_id if c.isalnum() or c in ['-', '_'])
    manifest_path = get_project_root() / "tda_sessions" / safe_user / "uploads" / safe_session / "manifest.json"

    if not manifest_path.exists():
        app_logger.warning(f"Upload manifest not found for session {session_id}")
        return None, []

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.loads(f.read())
    except Exception as e:
        app_logger.error(f"Failed to load upload manifest: {e}")
        return None, []

    context_parts = []
    total_chars = 0
    truncation_events = []

    for attachment in attachments:
        file_id = attachment.get("file_id")
        if not file_id or file_id not in manifest:
            app_logger.warning(f"Attachment file_id {file_id} not found in manifest")
            continue

        entry = manifest[file_id]
        filename = entry.get("filename", attachment.get("filename", "Unknown"))
        extracted_text = entry.get("extracted_text", "")

        if not extracted_text:
            continue

        # Truncate individual documents if needed
        original_size = len(extracted_text)
        if original_size > APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS:
            extracted_text = extracted_text[:APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS] + \
                f"\n\n[Document truncated - showing first {APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS:,} characters of {original_size:,} total]"
            truncation_events.append({
                "subtype": "document_truncation",
                "summary": f"Document '{filename}' truncated: {original_size:,} → {APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS:,} chars",
                "filename": filename,
                "original_chars": original_size,
                "truncated_to_chars": APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS,
                "reason": "per_file_limit"
            })

        context_parts.append(f"--- Document: {filename} ---\n{extracted_text}\n--- End of {filename} ---")
        total_chars += len(extracted_text)

        if total_chars > APP_CONFIG.DOCUMENT_CONTEXT_MAX_CHARS:
            context_parts.append("[Additional documents omitted - context limit reached]")
            truncation_events.append({
                "subtype": "document_truncation",
                "summary": f"Document context limit reached: {len(context_parts)} of {len(attachments)} documents loaded ({total_chars:,} chars)",
                "documents_loaded": len(context_parts),
                "documents_total": len(attachments),
                "total_chars": total_chars,
                "limit_chars": APP_CONFIG.DOCUMENT_CONTEXT_MAX_CHARS,
                "reason": "total_context_limit"
            })
            break

    if not context_parts:
        return None, []

    app_logger.info(f"Loaded document context: {len(context_parts)} documents, {total_chars:,} chars total")
    return "\n\n".join(context_parts), truncation_events


def load_multimodal_document_content(
    user_uuid: str, session_id: str, attachments: list,
    provider: str, model: str
) -> tuple[list[dict] | None, str | None]:
    """
    Split attachments into native multimodal blocks vs text fallback.

    For providers that support native document/image upload (e.g. Anthropic, Google),
    binary files are routed as multimodal blocks. Files that can't go native
    (wrong format, too large, unsupported provider) fall back to text extraction.

    Args:
        user_uuid: The user's UUID
        session_id: The session ID
        attachments: List of attachment dicts with file_id, filename keys
        provider: LLM provider name (e.g. "Anthropic", "Google", "Friendli")
        model: Model name for capability filtering

    Returns:
        (multimodal_blocks, text_fallback) where either can be None.
        multimodal_blocks: [{"type": "document"|"image", "path": str, "mime_type": str, "filename": str}]
        text_fallback: formatted text string for files that can't go native
    """
    if not attachments:
        return None, None

    import os
    from pathlib import Path
    from trusted_data_agent.core.utils import get_project_root
    from trusted_data_agent.llm.document_upload import DocumentUploadConfig, DocumentUploadCapability

    safe_user = "".join(c for c in user_uuid if c.isalnum() or c in ['-', '_'])
    safe_session = "".join(c for c in session_id if c.isalnum() or c in ['-', '_'])
    upload_dir = get_project_root() / "tda_sessions" / safe_user / "uploads" / safe_session
    manifest_path = upload_dir / "manifest.json"

    if not manifest_path.exists():
        app_logger.warning(f"Upload manifest not found for session {session_id}")
        return None, None

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.loads(f.read())
    except Exception as e:
        app_logger.error(f"Failed to load upload manifest: {e}")
        return None, None

    # Determine provider capabilities
    capability = DocumentUploadConfig.get_capability(provider, model)
    native_formats = set(DocumentUploadConfig.get_supported_formats(provider, model))
    max_file_size = DocumentUploadConfig.get_max_file_size(provider, model)
    supports_native = capability in [DocumentUploadCapability.NATIVE_FULL, DocumentUploadCapability.NATIVE_VISION_ONLY]

    app_logger.info(f"Multimodal routing: provider={provider}, model={model}, capability={capability.value}, native_formats={native_formats}")

    native_blocks = []
    text_parts = []
    total_text_chars = 0

    # MIME type mapping
    mime_types = {
        '.pdf': 'application/pdf', '.txt': 'text/plain',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.gif': 'image/gif', '.webp': 'image/webp'
    }
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

    for attachment in attachments:
        file_id = attachment.get("file_id")
        if not file_id or file_id not in manifest:
            app_logger.warning(f"Attachment file_id {file_id} not found in manifest")
            continue

        entry = manifest[file_id]
        filename = entry.get("filename", attachment.get("filename", "Unknown"))
        file_ext = os.path.splitext(filename)[1].lower()
        binary_path = upload_dir / entry.get("stored_filename", f"{file_id}{file_ext}")

        # Check if this file qualifies for native multimodal upload
        can_go_native = False
        if supports_native and file_ext in native_formats and binary_path.exists():
            file_size = binary_path.stat().st_size
            if max_file_size == 0 or file_size <= max_file_size:
                can_go_native = True
            else:
                app_logger.info(f"File {filename} ({file_size:,} bytes) exceeds native size limit ({max_file_size:,} bytes), falling back to text")

        if can_go_native:
            mime_type = mime_types.get(file_ext, 'application/octet-stream')
            block_type = "image" if file_ext in image_extensions else "document"
            native_blocks.append({
                "type": block_type,
                "path": str(binary_path),
                "mime_type": mime_type,
                "filename": filename
            })
            app_logger.info(f"Native multimodal block: {filename} ({block_type}, {mime_type})")

            # For document-type files (not images), ALSO extract text as fallback.
            # This ensures paths that can't send native document blocks (e.g. LangChain)
            # still have the text content available via document_context.
            if block_type == "document":
                extracted_text = entry.get("extracted_text", "")
                if extracted_text:
                    if len(extracted_text) > APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS:
                        extracted_text = extracted_text[:APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS] + \
                            f"\n\n[Document truncated - showing first {APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS:,} characters]"
                    text_parts.append(f"--- Document: {filename} ---\n{extracted_text}\n--- End of {filename} ---")
                    total_text_chars += len(extracted_text)
                    app_logger.info(f"Also extracted text for native document {filename} (fallback for non-multimodal paths)")
        else:
            # Fall back to text extraction
            extracted_text = entry.get("extracted_text", "")
            if not extracted_text:
                continue
            if len(extracted_text) > APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS:
                extracted_text = extracted_text[:APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS] + \
                    f"\n\n[Document truncated - showing first {APP_CONFIG.DOCUMENT_PER_FILE_MAX_CHARS:,} characters]"
            text_parts.append(f"--- Document: {filename} ---\n{extracted_text}\n--- End of {filename} ---")
            total_text_chars += len(extracted_text)
            if total_text_chars > APP_CONFIG.DOCUMENT_CONTEXT_MAX_CHARS:
                text_parts.append("[Additional documents omitted - context limit reached]")
                break

    multimodal_blocks = native_blocks if native_blocks else None
    text_fallback = "\n\n".join(text_parts) if text_parts else None

    if multimodal_blocks:
        app_logger.info(f"Multimodal result: {len(native_blocks)} native block(s) for {provider}")
    if text_fallback:
        app_logger.info(f"Text fallback: {len(text_parts)} document(s), {total_text_chars:,} chars")

    return multimodal_blocks, text_fallback


class DefinitiveToolError(Exception):
    """Custom exception for unrecoverable tool errors."""
    def __init__(self, message, friendly_message):
        super().__init__(message)
        self.friendly_message = friendly_message


class AgentState(Enum):
    PLANNING = auto()
    EXECUTING = auto()
    SUMMARIZING = auto()
    DONE = auto()
    ERROR = auto()


def unwrap_exception(e: BaseException) -> BaseException:
    """Recursively unwraps ExceptionGroups to find the root cause.

    Note: ExceptionGroup was added in Python 3.11. This function is compatible
    with Python 3.10+ by checking if ExceptionGroup exists.
    """
    # ExceptionGroup was added in Python 3.11 - use sys.version_info for compatibility
    import sys
    if sys.version_info >= (3, 11):
        if isinstance(e, ExceptionGroup) and e.exceptions:
            return unwrap_exception(e.exceptions[0])
    return e


def rebuild_tools_and_prompts_context(tool_to_exclude: str = None) -> Tuple[str, str]:
    """
    Rebuild tools_context and prompts_context strings from APP_STATE.

    This function should be called after profile override filtering to ensure
    the LLM sees the correct filtered tools/prompts in planning context.

    Args:
        tool_to_exclude: Tool name to exclude from context (e.g., 'TDA_FinalReport')

    Returns:
        Tuple[str, str]: (tools_context, prompts_context)
    """
    structured_tools = APP_STATE.get('structured_tools', {})
    mcp_tools = APP_STATE.get('mcp_tools', {})
    structured_prompts = APP_STATE.get('structured_prompts', {})

    # Build tools_context
    tool_context_parts = ["--- Available Tools ---"]
    for category, tools in sorted(structured_tools.items()):
        enabled_tools_in_category = [
            t for t in tools
            if not t.get('disabled') and t['name'] != tool_to_exclude
        ]
        if enabled_tools_in_category:
            tool_context_parts.append(f"--- Category: {category} ---")
            for tool_info in enabled_tools_in_category:
                tool_obj = mcp_tools.get(tool_info['name'])
                if not tool_obj:
                    continue

                tool_str = f"- `{tool_obj.name}` (tool): {tool_obj.description}"
                args_dict = tool_obj.args if isinstance(tool_obj.args, dict) else {}

                if args_dict:
                    tool_str += "\n  - Arguments:"
                    for arg_name, arg_details in args_dict.items():
                        arg_type = arg_details.get('type', 'any')
                        is_required = arg_details.get('required', False)
                        req_str = "required" if is_required else "optional"
                        arg_desc = arg_details.get('description', 'No description.')
                        tool_str += f"\n    - `{arg_name}` ({arg_type}, {req_str}): {arg_desc}"
                tool_context_parts.append(tool_str)

    tools_context = "\n".join(tool_context_parts) if len(tool_context_parts) > 1 else "--- No Tools Available ---"

    # Build prompts_context
    prompt_context_parts = ["--- Available Prompts ---"]
    for category, prompts in sorted(structured_prompts.items()):
        enabled_prompts_in_category = [p for p in prompts if not p.get('disabled')]
        if enabled_prompts_in_category:
            prompt_context_parts.append(f"--- Category: {category} ---")
            for prompt_info in enabled_prompts_in_category:
                prompt_description = prompt_info.get("description", "No description available.")
                prompt_str = f"- `{prompt_info['name']}` (prompt): {prompt_description}"

                processed_args = prompt_info.get('arguments', [])
                if processed_args:
                    prompt_str += "\n  - Arguments:"
                    for arg_details in processed_args:
                        arg_name = arg_details.get('name', 'unknown')
                        arg_type = arg_details.get('type', 'any')
                        is_required = arg_details.get('required', False)
                        req_str = "required" if is_required else "optional"
                        arg_desc = arg_details.get('description', 'No description.')
                        prompt_str += f"\n    - `{arg_name}` ({arg_type}, {req_str}): {arg_desc}"
                prompt_context_parts.append(prompt_str)

    prompts_context = "\n".join(prompt_context_parts) if len(prompt_context_parts) > 1 else "--- No Prompts Available ---"

    return tools_context, prompts_context


class PlanExecutor:
    AgentState = AgentState

    def _get_prompt_info(self, prompt_name: str) -> dict | None:
        """Helper to find prompt details from the structured prompts in the global state."""
        if not prompt_name:
            return None
        structured_prompts = self.dependencies['STATE'].get('structured_prompts', {})
        for category_prompts in structured_prompts.values():
            for prompt in category_prompts:
                if prompt.get("name") == prompt_name:
                    return prompt
        return None

    # --- MODIFICATION START: Add plan_to_execute and is_replay ---
    def __init__(self, session_id: str, user_uuid: str, original_user_input: str, dependencies: dict, active_prompt_name: str = None, prompt_arguments: dict = None, execution_depth: int = 0, disabled_history: bool = False, previous_turn_data: dict = None, force_history_disable: bool = False, source: str = "text", is_delegated_task: bool = False, force_final_summary: bool = False, plan_to_execute: list = None, is_replay: bool = False, task_id: str = None, profile_override_id: str = None, event_handler=None, is_session_primer: bool = False, attachments: list = None, skill_result=None, canvas_context: dict = None):
        self.session_id = session_id
        self.user_uuid = user_uuid
        self.event_handler = event_handler
        self.is_session_primer = is_session_primer  # Track if this is a session primer execution
        # --- MODIFICATION END ---
        self.original_user_input = original_user_input
        self.dependencies = dependencies
        self.state = self.AgentState.PLANNING

        # --- MODIFICATION START: Store profile override and setup temporary context ---
        self.profile_override_id = profile_override_id
        self.original_llm = None  # Will store original LLM if overridden
        self.original_mcp_tools = None  # Will store original tools if overridden
        self.original_mcp_prompts = None  # Will store original prompts if overridden
        self.original_provider = None  # Will store original provider if overridden
        self.original_model = None  # Will store original model if overridden
        self.original_structured_tools = None  # Will store original structured_tools if overridden
        self.original_structured_prompts = None  # Will store original structured_prompts if overridden
        self.original_provider_details = {}  # Will store provider-specific config (Friendli, Azure, AWS)
        self.original_server_id = None  # Will store original current_server_id_by_user entry if overridden
        self.effective_mcp_server_id = None  # Track the ACTUAL MCP server ID used during this turn (for RAG storage)
        self.profile_llm_instance = None  # Profile-specific LLM client (created when profile uses different provider than default)
        self.thinking_budget = None  # Gemini 2.x thinking budget from LLM config (None = not set, 0 = disabled, -1 = dynamic)

        # Snapshot model and provider for this turn from active profile (default or override)
        # Don't use global config as it may not match the profile being used
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            
            # Determine which profile will be used (override or default)
            self.active_profile_id = profile_override_id if profile_override_id else config_manager.get_default_profile_id(user_uuid)
            
            if self.active_profile_id:
                profiles = config_manager.get_profiles(user_uuid)
                active_profile = next((p for p in profiles if p.get("id") == self.active_profile_id), None)
                
                if active_profile:
                    # Get LLM configuration from the active profile
                    llm_config_id = active_profile.get('llmConfigurationId')
                    if llm_config_id:
                        llm_configs = config_manager.get_llm_configurations(user_uuid)
                        llm_config = next((cfg for cfg in llm_configs if cfg['id'] == llm_config_id), None)

                        if llm_config:
                            self.current_provider = llm_config.get('provider', get_user_provider(user_uuid))
                            self.current_model = llm_config.get('model', get_user_model(user_uuid))
                            self.thinking_budget = llm_config.get('thinking_budget')
                            app_logger.debug(f"Initialized consumption tracking with profile model: {self.current_provider}/{self.current_model}")
                        else:
                            # Fallback to global config if LLM config not found
                            self.current_model = get_user_model(user_uuid)
                            self.current_provider = get_user_provider(user_uuid)
                    else:
                        # Fallback to global config if no LLM config in profile
                        self.current_model = get_user_model(user_uuid)
                        self.current_provider = get_user_provider(user_uuid)

                    # Initialize dual-model configuration (tool_enabled only)
                    dual_model_config = active_profile.get('dualModelConfig')
                    if dual_model_config and active_profile.get('profile_type') == 'tool_enabled':
                        strategic_id = dual_model_config.get('strategicModelId')
                        tactical_id = dual_model_config.get('tacticalModelId')

                        llm_configs = config_manager.get_llm_configurations(user_uuid)

                        # Resolve strategic model (fallback to base)
                        if strategic_id:
                            strategic_config = next((cfg for cfg in llm_configs if cfg['id'] == strategic_id), None)
                            if strategic_config:
                                self.strategic_provider = strategic_config.get('provider')
                                self.strategic_model = strategic_config.get('model')
                                app_logger.info(f"[Dual-Model] Strategic: {self.strategic_provider}/{self.strategic_model}")
                            else:
                                app_logger.warning(f"Strategic model '{strategic_id}' not found, using base")
                                self.strategic_provider = self.current_provider
                                self.strategic_model = self.current_model
                        else:
                            self.strategic_provider = self.current_provider
                            self.strategic_model = self.current_model

                        # Resolve tactical model (fallback to base)
                        if tactical_id:
                            tactical_config = next((cfg for cfg in llm_configs if cfg['id'] == tactical_id), None)
                            if tactical_config:
                                self.tactical_provider = tactical_config.get('provider')
                                self.tactical_model = tactical_config.get('model')
                                app_logger.info(f"[Dual-Model] Tactical: {self.tactical_provider}/{self.tactical_model}")
                            else:
                                app_logger.warning(f"Tactical model '{tactical_id}' not found, using base")
                                self.tactical_provider = self.current_provider
                                self.tactical_model = self.current_model
                        else:
                            self.tactical_provider = self.current_provider
                            self.tactical_model = self.current_model

                        # Track if dual-model is active
                        self.is_dual_model_active = (
                            self.strategic_provider != self.tactical_provider or
                            self.strategic_model != self.tactical_model
                        )

                        # Initialize client instances (created in async run() method)
                        self.strategic_llm_instance = None
                        self.tactical_llm_instance = None
                    else:
                        # No dual-model config: Use base for both
                        self.strategic_provider = self.current_provider
                        self.strategic_model = self.current_model
                        self.tactical_provider = self.current_provider
                        self.tactical_model = self.current_model
                        self.is_dual_model_active = False
                        self.strategic_llm_instance = None
                        self.tactical_llm_instance = None
                else:
                    # Fallback to global config if profile not found
                    self.current_model = get_user_model(user_uuid)
                    self.current_provider = get_user_provider(user_uuid)
                    # No dual-model for fallback
                    self.strategic_provider = self.current_provider
                    self.strategic_model = self.current_model
                    self.tactical_provider = self.current_provider
                    self.tactical_model = self.current_model
                    self.is_dual_model_active = False
                    self.strategic_config = None
                    self.tactical_config = None
                    self.strategic_llm_instance = None
                    self.tactical_llm_instance = None
            else:
                # Fallback to global config if no active profile
                self.active_profile_id = "__system_default__"
                self.current_model = get_user_model(user_uuid)
                self.current_provider = get_user_provider(user_uuid)
                # No dual-model for fallback
                self.strategic_provider = self.current_provider
                self.strategic_model = self.current_model
                self.tactical_provider = self.current_provider
                self.tactical_model = self.current_model
                self.is_dual_model_active = False
                self.strategic_config = None
                self.tactical_config = None
                self.strategic_llm_instance = None
                self.tactical_llm_instance = None
        except Exception as e:
            # Fallback to global config on error
            app_logger.warning(f"Failed to get model/provider from profile, using global config: {e}")
            self.active_profile_id = "__system_default__"
            self.current_model = get_user_model(user_uuid)
            self.current_provider = get_user_provider(user_uuid)
            # No dual-model for fallback
            self.strategic_provider = self.current_provider
            self.strategic_model = self.current_model
            self.tactical_provider = self.current_provider
            self.tactical_model = self.current_model
            self.is_dual_model_active = False
            self.strategic_config = None
            self.tactical_config = None
            self.strategic_llm_instance = None
            self.tactical_llm_instance = None
            self.tactical_provider = self.current_provider
            self.tactical_model = self.current_model
            self.is_dual_model_active = False
        
        # Initialize profile-aware prompt resolver
        from trusted_data_agent.agent.profile_prompt_resolver import ProfilePromptResolver
        self.prompt_resolver = ProfilePromptResolver(
            profile_id=self.active_profile_id,
            provider=self.current_provider
        )
        app_logger.info(f"Initialized ProfilePromptResolver with profile_id='{self.active_profile_id}', provider='{self.current_provider}'")
        # --- MODIFICATION END ---

        self.structured_collected_data = {}
        self.workflow_state = {}
        self.turn_action_history = []
        self.meta_plan = None
        self.original_plan_for_history = None # Added to store original plan
        self.raw_llm_plan = None  # LLM's raw output before any preprocessing/rewrite passes
        self.current_phase_index = 0
        self.last_tool_output = None

        self.active_prompt_name = active_prompt_name
        self.prompt_arguments = prompt_arguments or {}
        self.workflow_goal_prompt = ""

        prompt_info = self._get_prompt_info(active_prompt_name)
        self.prompt_type = prompt_info.get("prompt_type", "reporting") if prompt_info else "reporting"

        self.is_in_loop = False
        self.current_loop_items = []
        self.processed_loop_items = []

        self.tool_constraints_cache = {}
        self.globally_skipped_tools = set()
        self.temp_data_holder = None
        self.last_failed_action_info = "None"
        self.events_to_yield = []
        self.last_action_str = None

        self.llm_debug_history = []
        self.max_steps = 40

        self.execution_depth = execution_depth
        self.MAX_EXECUTION_DEPTH = APP_CONFIG.MAX_EXECUTION_DEPTH

        self.disabled_history = disabled_history or force_history_disable
        self.previous_turn_data = previous_turn_data or {}
        self.is_synthesis_from_history = False
        self.is_conversational_plan = False
        self.source = source
        self.is_delegated_task = is_delegated_task
        self.force_final_summary = force_final_summary

        self.is_complex_prompt_workflow = False
        self.final_canonical_response = None
        self.is_single_prompt_plan = False
        self.final_summary_text = ""

        # --- MODIFICATION START: Store replay flags ---
        self.plan_to_execute = plan_to_execute # Store the plan if provided for replay
        self.is_replay = is_replay # Flag indicating if this is a replay
        # --- MODIFICATION END ---
        # --- MODIFICATION START: Add instance variable for turn number ---
        self.current_turn_number = 0 # Will be calculated once in run()
        # --- MODIFICATION END ---
        # --- MODIFICATION START: Store task_id ---
        self.task_id = task_id
        # --- MODIFICATION END ---
        # --- Document upload attachments ---
        self.attachments = attachments or []
        self.document_context = None  # Will be populated from extracted text if attachments present
        self.multimodal_content = None  # Will be populated with native multimodal blocks if provider supports it
        # --- Pre-processing skill injections ---
        self.skill_result = skill_result  # SkillResult from skills module (or None)
        # --- Canvas bidirectional context ---
        self.canvas_context = canvas_context  # {title, language, content, modified} or None

        self.turn_input_tokens = 0
        self.turn_output_tokens = 0

        # --- MODIFICATION START: Store the global RAG retriever instance ---
        if APP_CONFIG.RAG_ENABLED:
            from trusted_data_agent.agent.rag_retriever import get_rag_retriever
            self.rag_retriever = get_rag_retriever()
            if self.rag_retriever is None:
                app_logger.warning("RAG is enabled but retriever could not be initialized. Knowledge retrieval will be unavailable for this turn.")
        else:
            self.rag_retriever = None
        # --- MODIFICATION END ---
        
        # --- MODIFICATION START: Track which collection RAG examples came from ---
        self.rag_source_collection_id = None  # Will be set when RAG examples are retrieved
        self.rag_source_case_id = None  # Will be set when RAG examples are retrieved (for feedback tracking)
        # --- MODIFICATION END ---
        
        # --- PHASE 2: Track knowledge repository access ---
        self.knowledge_accessed = []  # List of {collection_id, collection_name, document_count} during planning
        self.knowledge_retrieval_event = None  # Store the knowledge retrieval event for replay
        # --- PHASE 2 END ---


    def _check_cancellation(self):
        """
        Check if cancellation was requested for this execution.
        Raises asyncio.CancelledError if cancellation flag is set.
        This provides a manual cancellation checkpoint independent of asyncio task.cancel().
        """
        from trusted_data_agent.core.config import APP_STATE
        active_tasks_key = f"{self.user_uuid}_{self.session_id}"
        cancellation_flags = APP_STATE.get("cancellation_flags", {})

        if cancellation_flags.get(active_tasks_key):
            app_logger.info(f"[CANCELLATION] Flag detected for session {self.session_id} - raising CancelledError")
            raise asyncio.CancelledError()

    def _log_system_event(self, event_data: dict, event_name: str = None):
        """Logs a system-level event to the turn action history for replay and debugging."""
        # Avoid logging token updates or status indicators
        if event_name in ["token_update", "status_indicator_update"] or "state" in event_data:
            return

        # Avoid logging the final answer event as it's not a step in the process
        if event_name == "final_answer":
            return

        action_for_history = {
            "tool_name": "TDA_SystemLog",
            "arguments": {
                "message": event_data.get("step"),
                "details": event_data.get("details")
            },
            "metadata": {
                "execution_depth": self.execution_depth,
                "type": event_data.get("type"),
                # --- MODIFICATION START: Add timestamp for per-step timing ---
                "timestamp": datetime.now(timezone.utc).isoformat()
                # --- MODIFICATION END ---
            }
        }
        result = {"status": "info"}
        if event_data.get("type") in ["error", "cancelled"]:
            result["status"] = event_data.get("type")

        self.turn_action_history.append({"action": action_for_history, "result": result})


    @staticmethod
    def _format_sse(data: dict, event: str = None) -> str:
        msg = f"data: {json.dumps(data)}\n"
        if event is not None:
            msg += f"event: {event}\n"
        return f"{msg}\n"

    def _format_sse_with_depth(self, data: dict, event: str = None) -> str:
        """Wraps _format_sse and auto-injects execution_depth into metadata."""
        if self.execution_depth > 0:
            data.setdefault("metadata", {})["execution_depth"] = self.execution_depth
        return self._format_sse(data, event)

    async def _call_llm_and_update_tokens(self, prompt: str, reason: str, system_prompt_override: str = None, raise_on_error: bool = False, disabled_history: bool = False, active_prompt_name_for_filter: str = None, source: str = "text", multimodal_content: list = None, planning_phase: str = None, current_provider: str = None, current_model: str = None) -> tuple[str, int, int]:
        """
        A centralized wrapper for calling the LLM that handles token updates.

        Args:
            planning_phase: Optional string indicating which phase of planning this call belongs to.
                           Valid values: "strategic" | "tactical" | "conversation"
            current_provider: Optional override for LLM provider (for dual-model support)
            current_model: Optional override for LLM model (for dual-model support)
        """
        final_disabled_history = disabled_history or self.disabled_history

        # Use explicitly passed provider/model if provided (dual-model feature)
        # Otherwise fall back to instance defaults
        effective_provider = current_provider if current_provider else self.current_provider
        effective_model = current_model if current_model else self.current_model

        # **NEW: Select LLM instance based on planning_phase for dual-model**
        # When dual-model is active, use strategic/tactical instances based on planning phase.
        # Otherwise, use profile-specific or global instance.
        if self.is_dual_model_active and planning_phase:
            if planning_phase == "strategic" and self.strategic_llm_instance:
                llm_instance = self.strategic_llm_instance
                app_logger.debug(f"[Dual-Model] Using strategic LLM instance for {effective_provider}/{effective_model}")
            elif planning_phase == "tactical" and self.tactical_llm_instance:
                llm_instance = self.tactical_llm_instance
                app_logger.debug(f"[Dual-Model] Using tactical LLM instance for {effective_provider}/{effective_model}")
            else:
                # Fallback if instances weren't created
                llm_instance = self.profile_llm_instance if self.profile_llm_instance else self.dependencies['STATE']['llm']
        else:
            # Single-model mode: Use profile-specific LLM instance when available (e.g., RAG profile with Friendli
            # while default profile uses Google). Falls back to global instance.
            llm_instance = self.profile_llm_instance if self.profile_llm_instance else self.dependencies['STATE']['llm']
        response_text, statement_input_tokens, statement_output_tokens, actual_provider, actual_model = await llm_handler.call_llm_api(
            llm_instance, prompt,
            # --- MODIFICATION START: Pass user_uuid and session_id ---
            user_uuid=self.user_uuid, session_id=self.session_id,
            # --- MODIFICATION END ---
            dependencies=self.dependencies, reason=reason,
            system_prompt_override=system_prompt_override, raise_on_error=raise_on_error,
            disabled_history=final_disabled_history,
            active_prompt_name_for_filter=active_prompt_name_for_filter,
            source=source,
            # --- MODIFICATION START: Pass active profile, provider and model for prompt resolution ---
            active_profile_id=self.active_profile_id,
            current_provider=effective_provider,  # Use effective provider (may be overridden)
            current_model=effective_model,        # Use effective model (may be overridden)
            # --- MODIFICATION END ---
            multimodal_content=multimodal_content,
            thinking_budget=self.thinking_budget
        )
        self.llm_debug_history.append({"reason": reason, "response": response_text})
        app_logger.debug(f"LLM RESPONSE (DEBUG): Reason='{reason}', Response='{response_text}'")

        self.turn_input_tokens += statement_input_tokens
        self.turn_output_tokens += statement_output_tokens

        # Store planning phase and model info for potential event emission
        # (actual event emission happens in callers that have access to event handlers)
        # Calculate per-call cost for centralized access by all callers
        from trusted_data_agent.core.cost_manager import CostManager
        cost_manager = CostManager()
        call_cost_usd = cost_manager.calculate_cost(
            provider=actual_provider or "Unknown",
            model=actual_model or "Unknown",
            input_tokens=statement_input_tokens,
            output_tokens=statement_output_tokens
        )

        self._last_call_metadata = {
            "planning_phase": planning_phase,
            "provider": actual_provider,
            "model": actual_model,
            "input_tokens": statement_input_tokens,
            "output_tokens": statement_output_tokens,
            "cost_usd": call_cost_usd
        }

        # **NEW: Track model usage with planning_phase for dual-model visibility**
        # This ensures session data accurately reflects which models were used for
        # strategic vs tactical planning
        await session_manager.update_models_used(
            user_uuid=self.user_uuid,
            session_id=self.session_id,
            provider=actual_provider,
            model=actual_model,
            profile_tag=self._get_current_profile_tag(),
            planning_phase=planning_phase  # ← Enables dual-model tracking
        )

        return response_text, statement_input_tokens, statement_output_tokens

    def _get_current_profile_tag(self) -> str | None:
        """
        Get the current profile tag from active profiles or profile override.
        
        Returns:
            Profile tag string or None if no active profile
        """
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            
            # If profile override is active, use that profile's tag
            if self.profile_override_id:
                profiles = config_manager.get_profiles(self.user_uuid)
                override_profile = next((p for p in profiles if p.get("id") == self.profile_override_id), None)
                if override_profile:
                    profile_tag = override_profile.get("tag")
                    app_logger.debug(f"_get_current_profile_tag: Using profile override tag: {profile_tag}")
                    return profile_tag
                else:
                    app_logger.warning(f"_get_current_profile_tag: Profile override ID {self.profile_override_id} not found")
            
            # Otherwise use the default profile
            default_profile_id = config_manager.get_default_profile_id(self.user_uuid)
            if default_profile_id:
                profiles = config_manager.get_profiles(self.user_uuid)
                default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
                if default_profile:
                    profile_tag = default_profile.get("tag")
                    app_logger.debug(f"_get_current_profile_tag: Using default profile tag: {profile_tag}")
                    return profile_tag
            
            app_logger.debug(f"_get_current_profile_tag: No profile tag found (override_id={self.profile_override_id}, default_id={default_profile_id if 'default_profile_id' in locals() else 'not set'})")
        except Exception as e:
            app_logger.warning(f"Failed to get current profile tag: {e}", exc_info=True)
        return None

    def _get_active_profile_tag(self) -> str:
        """
        Get the tag of the currently active (default) profile, ignoring any profile override.
        Used for fallback messaging when profile override fails.
        
        Returns:
            str: The tag of the default profile, or "DEFAULT" if none found
        """
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            
            default_profile_id = config_manager.get_default_profile_id(self.user_uuid)
            if default_profile_id:
                profiles = config_manager.get_profiles(self.user_uuid)
                default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
                if default_profile:
                    return default_profile.get("tag", "DEFAULT")
            
        except Exception as e:
            app_logger.warning(f"Failed to get default profile tag: {e}", exc_info=True)
        
        return "DEFAULT"

    def _calculate_session_cost_at_turn(self, session_data: dict) -> float:
        """
        Calculate cumulative session cost up to (but not including) current turn.
        Iterates workflow_history and sums turn_cost for all previous turns.
        Falls back to token-based calculation for legacy sessions missing turn_cost.

        Args:
            session_data: Session dictionary containing workflow_history

        Returns:
            float: Cumulative cost of all previous turns in USD
        """
        session_cost = 0.0
        workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

        for past_turn in workflow_history:
            if "turn_cost" in past_turn:
                # Use stored turn cost (preferred - accurate historical cost)
                session_cost += float(past_turn["turn_cost"])
                app_logger.debug(f"[Session Cost] Turn {past_turn.get('turn', '?')}: ${past_turn['turn_cost']:.6f} (from stored)")
            else:
                # Legacy fallback: calculate from tokens using current pricing
                # Note: This may not reflect historical pricing, but is best effort
                try:
                    from trusted_data_agent.core.cost_manager import CostManager
                    cost_manager = CostManager()
                    turn_cost = cost_manager.calculate_cost(
                        provider=past_turn.get("provider", self.current_provider),
                        model=past_turn.get("model", self.current_model),
                        input_tokens=past_turn.get("turn_input_tokens", 0),
                        output_tokens=past_turn.get("turn_output_tokens", 0)
                    )
                    session_cost += turn_cost
                    app_logger.debug(f"[Session Cost] Turn {past_turn.get('turn', '?')}: ${turn_cost:.6f} (calculated from tokens - legacy)")
                except Exception as e:
                    app_logger.warning(f"Failed to calculate legacy turn cost for turn {past_turn.get('turn', '?')}: {e}")

        app_logger.debug(f"[Session Cost] Cumulative up to turn {self.current_turn_number}: ${session_cost:.6f}")
        return session_cost

    async def _get_tool_constraints(self, tool_name: str) -> Tuple[dict, list]:
        """
        Uses an LLM to determine if a tool requires numeric or character columns.
        Returns the constraints and a list of events to be yielded by the caller.
        """
        if tool_name in self.tool_constraints_cache:
            return self.tool_constraints_cache[tool_name], []

        events = []
        tool_definition = self.dependencies['STATE'].get('mcp_tools', {}).get(tool_name)
        constraints = {}

        if tool_definition:
            prompt_modifier = ""
            if any(k in tool_name.lower() for k in ["univariate", "standarddeviation", "negativevalues"]):
                prompt_modifier = "This tool is for quantitative analysis and requires a 'numeric' data type for `column_name`."
            elif any(k in tool_name.lower() for k in ["distinctcategories"]):
                prompt_modifier = "This tool is for categorical analysis and requires a 'character' data type for `column_name`."

            prompt = (
                f"Analyze the tool to determine if its `column_name` argument is for 'numeric', 'character', or 'any' type.\n"
                f"Tool: `{tool_definition.name}`\nDescription: \"{tool_definition.description}\"\nHint: {prompt_modifier}\n"
                "Respond with a single JSON object: {\"dataType\": \"numeric\" | \"character\" | \"any\"}"
            )

            reason="Determining tool constraints for column iteration."
            call_id = str(uuid.uuid4())
            events.append(self._format_sse_with_depth({"step": "Calling LLM", "type": "system_message", "details": {"summary": reason, "call_id": call_id}}))

            response_text, input_tokens, output_tokens = await self._call_llm_and_update_tokens(
                prompt=prompt, reason=reason,
                system_prompt_override="You are a JSON-only responding assistant.",
                raise_on_error=True,
                source=self.source
            )

            # Log post-LLM system_message with tokens + cost for historical replay
            constraint_log_event = {
                "step": "Calling LLM",
                "type": "system_message",
                "details": {
                    "summary": reason,
                    "call_id": call_id,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": self._last_call_metadata.get("cost_usd", 0)
                }
            }
            self._log_system_event(constraint_log_event)

            updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
            if updated_session:
                events.append(self._format_sse_with_depth({
                    "statement_input": input_tokens,
                    "statement_output": output_tokens,
                    "turn_input": self.turn_input_tokens,
                    "turn_output": self.turn_output_tokens,
                    "total_input": updated_session.get("input_tokens", 0),
                    "total_output": updated_session.get("output_tokens", 0),
                    "call_id": call_id,
                    "cost_usd": self._last_call_metadata.get("cost_usd", 0)
                }, "token_update"))

            try:
                constraints = json.loads(re.search(r'\{.*\}', response_text, re.DOTALL).group(0))
            except (json.JSONDecodeError, AttributeError):
                constraints = {}

        self.tool_constraints_cache[tool_name] = constraints
        return constraints, events

    def _add_to_structured_data(self, tool_result: dict, context_key_override: str = None):
        """Adds tool results to the structured data dictionary."""
        context_key = context_key_override or f"Plan Results: {self.active_prompt_name or 'Ad-hoc'}"
        if context_key not in self.structured_collected_data:
            self.structured_collected_data[context_key] = []

        if isinstance(tool_result, list):
             self.structured_collected_data[context_key].extend(tool_result)
        else:
             self.structured_collected_data[context_key].append(tool_result)
        app_logger.debug(f"Added tool result to structured data under key: '{context_key}'.")

    def _distill_data_for_llm_context(self, data: any, _events: list = None) -> any:
        """
        Recursively distills large data structures into metadata summaries to protect the LLM context window.

        Args:
            data: The data structure to distill
            _events: Optional list to accumulate distillation event dicts (caller reads after call)
        """
        if isinstance(data, dict):
            if 'results' in data and isinstance(data['results'], list):
                results_list = data['results']
                is_large = (len(results_list) > APP_CONFIG.CONTEXT_DISTILLATION_MAX_ROWS or
                            len(json.dumps(results_list)) > APP_CONFIG.CONTEXT_DISTILLATION_MAX_CHARS)

                if is_large and all(isinstance(item, dict) for item in results_list):
                    columns = list(results_list[0].keys()) if results_list else []
                    if _events is not None:
                        _events.append({
                            "subtype": "context_distillation",
                            "summary": f"Large result distilled: {len(results_list):,} rows → metadata summary",
                            "row_count": len(results_list),
                            "char_count": len(json.dumps(results_list)),
                            "columns": columns
                        })
                    distilled_result = {
                        "status": data.get("status", "success"),
                        "metadata": {
                            "row_count": len(results_list),
                            "columns": columns,
                            **data.get("metadata", {})
                        },
                        "comment": "Full data is too large for context. This is a summary."
                    }
                    return distilled_result

            return {key: self._distill_data_for_llm_context(value, _events=_events) for key, value in data.items()}

        elif isinstance(data, list):
            return [self._distill_data_for_llm_context(item, _events=_events) for item in data]

        return data

    def _find_value_by_key(self, data_structure: any, target_key: str) -> any:
        """Recursively searches a nested data structure for the first value of a given key."""
        if isinstance(data_structure, dict):
            # Check for a direct match, but be case-insensitive for robustness
            for key, value in data_structure.items():
                if key.lower() == target_key.lower():
                    return value

            # If no direct match, recurse into values
            for value in data_structure.values():
                found = self._find_value_by_key(value, target_key)
                if found is not None:
                    return found

        elif isinstance(data_structure, list):
            for item in data_structure:
                found = self._find_value_by_key(item, target_key)
                if found is not None:
                    return found
        return None

    def _unwrap_single_value_from_result(self, data_structure: any) -> any:
        """
        Deterministically unwraps a standard tool result structure to extract a
        single primary value, if one exists.
        """
        is_single_value_structure = (
            isinstance(data_structure, list) and len(data_structure) == 1 and
            isinstance(data_structure[0], dict) and "results" in data_structure[0] and
            isinstance(data_structure[0]["results"], list) and len(data_structure[0]["results"]) == 1 and
            isinstance(data_structure[0]["results"][0], dict) and len(data_structure[0]["results"][0]) == 1
        )

        if is_single_value_structure:
            # Extract the single value from the nested structure
            return next(iter(data_structure[0]["results"][0].values()))

        # If the structure doesn't match, return the original data structure
        return data_structure

    def _resolve_arguments(self, arguments: dict, loop_item: dict = None) -> dict:
        """
        Scans tool arguments for placeholders and resolves them based on the
        current context (workflow state and the optional loop_item).
        """
        if not isinstance(arguments, dict):
            return arguments

        resolved_args = {}

        placeholder_pattern = re.compile(r'(\s*\{[\s\n]*"source":\s*"[^"]+"(?:,[\s\n]*"key":\s*"[^"]+")?[\s\n]*\}\s*)')

        def _resolve_embedded_placeholder(match):
            """Callback function for re.sub to resolve a matched placeholder string."""
            placeholder_str = match.group(1).strip()
            try:
                placeholder_data = json.loads(placeholder_str)
                source_key = placeholder_data.get("source")
                target_key = placeholder_data.get("key")

                data_from_source = None
                if source_key == "loop_item" and loop_item:
                    data_from_source = loop_item
                elif source_key and source_key.startswith("result_of_phase_"):
                    data_from_source = self.workflow_state.get(source_key)
                elif source_key and source_key.startswith("phase_"):
                    data_from_source = self.workflow_state.get(f"result_of_{source_key}")
                elif source_key:
                    data_from_source = self.workflow_state.get(source_key)

                if data_from_source is None:
                    app_logger.warning(f"Could not resolve embedded placeholder: source '{source_key}' not found.")
                    return match.group(1)

                if target_key:
                    found_value = self._find_value_by_key(data_from_source, target_key)
                else:
                    found_value = self._unwrap_single_value_from_result(data_from_source)

                if found_value is not None:
                    app_logger.info(f"Resolved embedded placeholder '{placeholder_str}' to value '{found_value}'.")
                    return str(found_value)
                else:
                    app_logger.warning(f"Could not resolve embedded placeholder: key '{target_key}' not found in source '{source_key}'.")
                    return match.group(1)

            except (json.JSONDecodeError, AttributeError):
                return match.group(1)

        for key, value in arguments.items():
            if isinstance(value, str) and '"source":' in value and not placeholder_pattern.fullmatch(value.strip()):
                resolved_value = placeholder_pattern.sub(_resolve_embedded_placeholder, value)
                resolved_args[key] = resolved_value
                continue

            source_phase_key = None
            target_data_key = None
            is_placeholder = False
            original_placeholder = copy.deepcopy(value)

            if isinstance(value, dict) and value.get("source") == "loop_item" and loop_item:
                loop_key = value.get("key")
                # --- MODIFICATION START ---
                # If a key is specified, get that value. If no key is specified, pass the entire loop_item.
                resolved_args[key] = loop_item.get(loop_key) if loop_key else loop_item
                # --- MODIFICATION END ---
                continue

            if isinstance(value, str):
                # Handle bare {KeyName} templates embedded in SQL strings or other text
                # Planner normalizes standalone templates to dicts, but embedded ones remain as strings
                if loop_item and re.search(r'\{[A-Za-z][A-Za-z0-9_]*\}', value):
                    def replace_bare_template(match):
                        key = match.group(1)
                        # Only resolve if it looks like a template variable and exists in loop_item
                        if (key[0].isupper() or key in ['TableName', 'ColumnName', 'DatabaseName', 'SchemaName']) and key in loop_item:
                            replacement = loop_item.get(key)
                            if replacement is not None:
                                app_logger.info(f"Resolved bare template: {{{key}}} -> '{replacement}'")
                                return str(replacement)
                        return match.group(0)  # Return original if not a template or key not found

                    value = re.sub(r'\{([A-Za-z][A-Za-z0-9_]*)\}', replace_bare_template, value)
                    resolved_args[key] = value
                    continue

                # --- NEW: Handle string interpolation for result_of_phase_N references ---
                # Pattern: {result_of_phase_1[KeyName]} or {result_of_phase_1} within strings
                if "{result_of_phase_" in value or "{phase_" in value:
                    phase_pattern = re.compile(r'\{(result_of_phase_\d+|phase_\d+)(?:\[([^\]]+)\])?\}')

                    def replace_phase_ref(match):
                        """Replace {result_of_phase_N[key]} with actual value from workflow state."""
                        source_key = match.group(1)
                        target_key = match.group(2)  # Optional key within brackets

                        if source_key.startswith("phase_"):
                            source_key = f"result_of_{source_key}"

                        data_from_phase = self.workflow_state.get(source_key)

                        if data_from_phase is None:
                            app_logger.warning(f"Could not resolve phase interpolation: '{source_key}' not in workflow state.")
                            return match.group(0)

                        if target_key:
                            # Extract specific key from the phase result
                            target_key_clean = target_key.strip('\'"')
                            found_value = self._find_value_by_key(data_from_phase, target_key_clean)
                            if found_value is not None:
                                app_logger.info(f"Resolved phase interpolation: {{{source_key}[{target_key_clean}]}} -> '{found_value}'")
                                return str(found_value)
                            else:
                                app_logger.warning(f"Could not find key '{target_key_clean}' in '{source_key}'.")
                                return match.group(0)
                        else:
                            # No specific key - unwrap single value
                            unwrapped = self._unwrap_single_value_from_result(data_from_phase)
                            if unwrapped is not None:
                                app_logger.info(f"Resolved phase interpolation: {{{source_key}}} -> '{unwrapped}'")
                                return str(unwrapped)
                            else:
                                app_logger.warning(f"Could not unwrap value from '{source_key}'.")
                                return match.group(0)

                    resolved_value = phase_pattern.sub(replace_phase_ref, value)
                    resolved_args[key] = resolved_value
                    continue
                # --- END NEW ---

                match = re.match(r"(result_of_phase_\d+|phase_\d+|injected_previous_turn_data)", value)
                if match:
                    source_phase_key = match.group(1)
                    is_placeholder = True

            elif isinstance(value, dict):
                if "source" in value and "key" in value:
                    source_phase_key = value["source"]
                    target_data_key = value["key"]
                    is_placeholder = True

                elif "source" in value and "key" not in value:
                    source_phase_key = value["source"]
                    target_data_key = None
                    is_placeholder = True
                    self.events_to_yield.append(self._format_sse_with_depth({
                        "step": "System Correction", "type": "workaround",
                        "details": {
                            "summary": "The agent's plan used an incomplete placeholder. The system will automatically extract the primary value from the source.",
                            "correction_type": "placeholder_unwrapping",
                            "from": original_placeholder,
                            "to": f"Unwrapped value from '{source_phase_key}'"
                        }
                    }))

                else:
                    for k, v in value.items():
                        if re.match(r"result_of_phase_\d+", k):
                            source_phase_key = k
                            target_data_key = v
                            is_placeholder = True

                            canonical_value = {"source": source_phase_key, "key": target_data_key}
                            self.events_to_yield.append(self._format_sse_with_depth({
                                "step": "System Correction", "type": "workaround",
                                "details": {
                                    "summary": "The agent's plan contained a non-standard placeholder. The system has automatically normalized it to ensure correct data flow.",
                                    "correction_type": "placeholder_normalization",
                                    "from": original_placeholder,
                                    "to": canonical_value
                                }
                            }))
                            value = canonical_value
                            break

            if is_placeholder:
                if source_phase_key and source_phase_key.startswith("phase_"):
                    source_phase_key = f"result_of_{source_phase_key}"

                # Normalize tool_<ToolName> references to result_of_phase_N
                # Some LLMs generate "source": "tool_TDA_CurrentDate" instead of "result_of_phase_5"
                if source_phase_key and source_phase_key.startswith("tool_") and source_phase_key not in self.workflow_state:
                    tool_ref_name = source_phase_key[5:]  # Strip "tool_" prefix
                    if self.meta_plan:
                        for phase in self.meta_plan:
                            phase_tools = phase.get("relevant_tools", [])
                            if tool_ref_name in phase_tools:
                                resolved_key = f"result_of_phase_{phase.get('phase', '')}"
                                if resolved_key in self.workflow_state:
                                    app_logger.info(f"Normalized tool reference '{source_phase_key}' → '{resolved_key}'")
                                    source_phase_key = resolved_key
                                    break

                if source_phase_key in self.workflow_state:
                    data_from_phase = self.workflow_state[source_phase_key]

                    if target_data_key:
                        found_value = self._find_value_by_key(data_from_phase, target_data_key)
                        if found_value is not None:
                            resolved_args[key] = found_value
                        else:
                            app_logger.warning(f"Could not resolve placeholder: key '{target_data_key}' not found in '{source_phase_key}'. Omitting argument.")
                            # Don't set None - just omit the argument entirely
                    else:
                        unwrapped_value = self._unwrap_single_value_from_result(data_from_phase)
                        resolved_args[key] = unwrapped_value
                        app_logger.info(f"Resolved placeholder for '{key}' by unwrapping the result of '{source_phase_key}'.")

                else:
                    app_logger.warning(f"Could not resolve placeholder: source '{source_phase_key}' not in workflow state.")
                    resolved_args[key] = value

            elif isinstance(value, dict):
                resolved_args[key] = self._resolve_arguments(value, loop_item)

            elif isinstance(value, list):
                resolved_list = [self._resolve_arguments(item, loop_item) if isinstance(item, dict) else item for item in value]
                resolved_args[key] = resolved_list

            else:
                resolved_args[key] = value

        # Filter out None values (defense in depth)
        filtered_args = {k: v for k, v in resolved_args.items() if v is not None}

        if len(filtered_args) < len(resolved_args):
            removed_keys = set(resolved_args.keys()) - set(filtered_args.keys())
            app_logger.debug(f"Filtered out None values for keys: {removed_keys}")

        return filtered_args

    async def _generate_and_emit_session_name(self):
        """
        Generate session name using unified generator and emit SSE events.
        Collects events for system_events array (plan reload).

        Yields:
            - SSE formatted events (strings) for live streaming
            - Final tuple: (session_name, input_tokens, output_tokens, collected_events)
        """
        collected_events = []
        session_name = "New Chat"
        name_input_tokens = 0
        name_output_tokens = 0

        async for event_data, event_type, in_tokens, out_tokens in generate_session_name_with_events(
            user_query=self.original_user_input,
            session_id=self.session_id,
            llm_interface="executor",
            llm_dependencies=self.dependencies,
            user_uuid=self.user_uuid,
            active_profile_id=self.active_profile_id,
            current_provider=self.current_provider,
            current_model=self.current_model,
            profile_llm_instance=self.profile_llm_instance,
            emit_events=True
        ):
            if event_data is None:
                # Final yield: (None, session_name, input_tokens, output_tokens)
                session_name = event_type  # event_type contains name in final yield
                name_input_tokens = in_tokens
                name_output_tokens = out_tokens
            else:
                # SSE event: yield to frontend
                yield self._format_sse_with_depth(event_data, event_type)

                # Collect for system_events (plan reload)
                # Store complete event_data including 'step', 'details', and 'type'
                collected_events.append({
                    "type": event_type,
                    "payload": event_data  # Full event data, not just details
                })

        # Final yield: return the collected data as a tuple
        yield (session_name, name_input_tokens, name_output_tokens, collected_events)


    def _detect_profile_type(self) -> str:
        """Detect whether current profile is llm_only, rag_focused, or tool_enabled."""
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()

            if self.profile_override_id:
                # Check override profile
                profiles = config_manager.get_profiles(self.user_uuid)
                override = next((p for p in profiles if p.get("id") == self.profile_override_id), None)
                if override:
                    return override.get("profile_type", "tool_enabled")
            else:
                # Check default profile
                default_profile_id = config_manager.get_default_profile_id(self.user_uuid)
                if default_profile_id:
                    default = config_manager.get_profile(default_profile_id, self.user_uuid)
                    if default:
                        return default.get("profile_type", "tool_enabled")
        except Exception as e:
            app_logger.error(f"Error detecting profile type: {e}")

        return "tool_enabled"  # Default

    def _is_rag_focused_profile(self) -> bool:
        """Check if current profile is RAG focused type."""
        profile_type = self._detect_profile_type()
        return profile_type == "rag_focused"

    async def _execute_conversation_with_tools(self):
        """
        Execute using LangChain tool-calling agent for conversation_with_tools profile.

        This provides a simpler, more conversational approach to MCP tool usage
        compared to the multi-phase planner/executor architecture.

        Yields SSE events for:
        - Agent initialization
        - Tool invocations
        - Tool completions
        - Final response

        Also saves turn data to workflow_history for session reload.
        """
        from trusted_data_agent.llm.langchain_adapter import (
            create_langchain_llm,
            load_mcp_tools_for_langchain
        )
        from trusted_data_agent.agent.conversation_agent import ConversationAgentExecutor
        from trusted_data_agent.core.config_manager import get_config_manager

        config_manager = get_config_manager()

        # Get profile configuration
        profile_config = self._get_profile_config()
        profile_tag = profile_config.get("tag", "CONV")
        mcp_server_id = profile_config.get("mcpServerId")
        llm_config_id = profile_config.get("llmConfigurationId")

        # MCP server is optional when component tools are available (platform feature).
        # Component tools (TDA_Charting, etc.) don't require an MCP server.
        from trusted_data_agent.components.manager import get_component_langchain_tools
        component_tools = get_component_langchain_tools(self.active_profile_id, self.user_uuid, session_id=self.session_id)

        if not mcp_server_id and not component_tools:
            error_msg = "conversation_with_tools profile requires an MCP server configuration or active component tools."
            app_logger.error(error_msg)
            yield self._format_sse_with_depth({"step": "Error", "error": error_msg}, "error")
            return

        if not llm_config_id:
            error_msg = "conversation_with_tools profile requires an LLM configuration."
            app_logger.error(error_msg)
            yield self._format_sse_with_depth({"step": "Error", "error": error_msg}, "error")
            return

        try:
            # Create LangChain LLM instance
            app_logger.info(f"Creating LangChain LLM for config {llm_config_id}")
            llm_instance = create_langchain_llm(llm_config_id, self.user_uuid, thinking_budget=self.thinking_budget)

            # Load MCP tools filtered by profile (if MCP server configured)
            all_tools = []
            if mcp_server_id:
                app_logger.info(f"Loading MCP tools from server {mcp_server_id}")
                mcp_tools = await load_mcp_tools_for_langchain(
                    mcp_server_id=mcp_server_id,
                    profile_id=self.active_profile_id,
                    user_uuid=self.user_uuid
                )
                all_tools.extend(mcp_tools)
                app_logger.info(f"Loaded {len(mcp_tools)} MCP tools for agent")

            # Merge component tools (TDA_Charting, etc.) — platform feature, per-profile config
            # component_tools already loaded above (before MCP server check)
            if component_tools:
                all_tools.extend(component_tools)
                app_logger.info(f"Added {len(component_tools)} component tool(s): {', '.join(t.name for t in component_tools)}")

            # Get conversation history for context
            # NOTE: The current user query has already been added to chat_object by execution_service.py
            # before this code runs. We need to exclude it to avoid duplication since the agent
            # will add it again as the current query.
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)
            conversation_history = []
            if session_data:
                chat_object = session_data.get("chat_object", [])
                app_logger.debug(f"[ConvAgent] chat_object has {len(chat_object)} messages")

                # Take last N messages for context, excluding the current query
                # We need to exclude ALL instances of the current query from the end of history
                history_messages = chat_object[-11:]  # Get one extra to check

                # Debug: Log what we're comparing
                if history_messages:
                    last_msg = history_messages[-1]
                    last_content = last_msg.get("content", "")
                    app_logger.debug(f"[ConvAgent] Last message role: {last_msg.get('role')}")
                    app_logger.debug(f"[ConvAgent] Last message content (first 100 chars): {last_content[:100] if last_content else 'EMPTY'}")
                    app_logger.debug(f"[ConvAgent] Current query (first 100 chars): {self.original_user_input[:100] if self.original_user_input else 'EMPTY'}")
                    app_logger.debug(f"[ConvAgent] Contents match: {last_content == self.original_user_input}")
                    app_logger.debug(f"[ConvAgent] Contents match (stripped): {last_content.strip() == self.original_user_input.strip() if last_content and self.original_user_input else False}")

                # Use stripped comparison to handle whitespace differences
                original_input_stripped = self.original_user_input.strip() if self.original_user_input else ""

                # Remove current query from history if present (compare stripped to handle whitespace)
                if history_messages and history_messages[-1].get("role") == "user":
                    last_content = history_messages[-1].get("content", "").strip()
                    if last_content == original_input_stripped:
                        # Exclude the current query from history (it will be added by the agent)
                        app_logger.info(f"[ConvAgent] Excluding current query from history")
                        history_messages = history_messages[:-1]
                    else:
                        app_logger.info(f"[ConvAgent] Last message differs from current query, keeping in history")

                # Take only the last 10 after exclusion
                # Filter out Google's initial priming messages that shouldn't be in conversation history
                priming_messages = {
                    "You are a helpful assistant.",
                    "Understood."
                }

                app_logger.info(f"[ConvAgent] Processing {len(history_messages[-10:])} messages for history")
                for msg in history_messages[-10:]:
                    msg_content = msg.get("content", "")

                    # Skip messages marked as invalid (purged or toggled off by user)
                    if msg.get("isValid") is False:
                        app_logger.debug(f"[ConvAgent] Skipping invalid message: {msg_content[:50]}...")
                        continue

                    # Skip Google priming messages
                    if msg_content in priming_messages:
                        app_logger.info(f"[ConvAgent] Skipping priming message: {msg_content[:50]}")
                        continue

                    # Normalize role: 'model' (Google) → 'assistant' (standard)
                    msg_role = msg.get("role", "user")
                    original_role = msg_role
                    if msg_role == "model":
                        msg_role = "assistant"
                    app_logger.info(f"[ConvAgent] Adding to history: role={msg_role} (original: {original_role}), content first 50 chars: {msg_content[:50]}")
                    conversation_history.append({
                        "role": msg_role,
                        "content": msg_content
                    })

                app_logger.info(f"[ConvAgent] Built conversation history with {len(conversation_history)} messages")

            # --- KNOWLEDGE RETRIEVAL FOR CONVERSATION WITH TOOLS ---
            # Check if knowledge collections are enabled for this profile
            knowledge_config = profile_config.get("knowledgeConfig", {})
            knowledge_enabled = knowledge_config.get("enabled", False)
            knowledge_context_str = ""
            knowledge_accessed = []
            knowledge_chunks = []
            knowledge_retrieval_event_data = None

            if knowledge_enabled and self.rag_retriever:
                app_logger.info("🔍 Knowledge retrieval enabled for conversation_with_tools profile")

                try:
                    import time
                    retrieval_start_time = time.time()

                    knowledge_collections = knowledge_config.get("collections", [])
                    # Use three-tier configuration (global -> profile -> locks)
                    from trusted_data_agent.core.config_manager import get_config_manager
                    config_manager = get_config_manager()
                    effective_config = config_manager.get_effective_knowledge_config(knowledge_config)
                    max_docs = effective_config.get("maxDocs", APP_CONFIG.KNOWLEDGE_RAG_NUM_DOCS)
                    min_relevance = effective_config.get("minRelevanceScore", APP_CONFIG.KNOWLEDGE_MIN_RELEVANCE_SCORE)
                    max_tokens = effective_config.get("maxTokens", APP_CONFIG.KNOWLEDGE_MAX_TOKENS)

                    if knowledge_collections:
                        # Emit start event (fetch actual collection names from metadata)
                        collection_names_for_start = []
                        for coll_config in knowledge_collections:
                            coll_id = coll_config.get("id")
                            if coll_id and self.rag_retriever:
                                coll_meta = self.rag_retriever.get_collection_metadata(coll_id)
                                if coll_meta:
                                    collection_names_for_start.append(coll_meta.get("name", coll_id))
                                else:
                                    # Fallback: try to get name from collection DB table directly
                                    try:
                                        from trusted_data_agent.core.collection_db import get_collection_db
                                        coll_db = get_collection_db()
                                        coll_info = coll_db.get_collection_by_id(coll_id)
                                        if coll_info and coll_info.get("name"):
                                            collection_names_for_start.append(coll_info["name"])
                                        else:
                                            collection_names_for_start.append(coll_config.get("name", coll_id))
                                    except Exception as e:
                                        logger.warning(f"Failed to fetch collection name for {coll_id}: {e}")
                                        collection_names_for_start.append(coll_config.get("name", coll_id))
                            else:
                                collection_names_for_start.append(coll_config.get("name", coll_id or "Unknown"))

                        yield self._format_sse_with_depth({
                            "type": "knowledge_retrieval_start",
                            "payload": {
                                "collections": collection_names_for_start,
                                "max_docs": max_docs,
                                "session_id": self.session_id
                            }
                        }, event="notification")

                        from trusted_data_agent.agent.rag_access_context import RAGAccessContext
                        rag_context = RAGAccessContext(user_id=self.user_uuid, retriever=self.rag_retriever)

                        all_results = self.rag_retriever.retrieve_examples(
                            query=self.original_user_input,
                            k=max_docs * len(knowledge_collections),
                            min_score=min_relevance,
                            allowed_collection_ids=set([c["id"] for c in knowledge_collections]),
                            rag_context=rag_context,
                            repository_type="knowledge"
                        )

                        if all_results:
                            # Apply reranking if configured
                            reranked_results = all_results
                            for coll_config in knowledge_collections:
                                if coll_config.get("reranking", False):
                                    coll_results = [r for r in all_results
                                                  if r.get("metadata", {}).get("collection_id") == coll_config["id"]]
                                    if coll_results and self.llm_handler:
                                        # Get actual collection name from metadata
                                        coll_id = coll_config.get("id")
                                        coll_name = "Unknown"
                                        if coll_id and self.rag_retriever:
                                            coll_meta = self.rag_retriever.get_collection_metadata(coll_id)
                                            if coll_meta:
                                                coll_name = coll_meta.get("name", "Unknown")
                                            else:
                                                coll_name = coll_config.get("name", "Unknown")
                                        else:
                                            coll_name = coll_config.get("name", "Unknown")

                                        # Emit reranking start event
                                        yield self._format_sse_with_depth({
                                            "type": "knowledge_reranking_start",
                                            "payload": {
                                                "collection": coll_name,
                                                "document_count": len(coll_results),
                                                "session_id": self.session_id
                                            }
                                        }, event="notification")

                                        reranked = await self._rerank_knowledge_with_llm(
                                            query=self.original_user_input,
                                            documents=coll_results,
                                            max_docs=max_docs
                                        )

                                        # Emit reranking complete event with token info
                                        # Get session to show updated token counts
                                        updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
                                        if updated_session:
                                            yield self._format_sse_with_depth({
                                                "type": "knowledge_reranking_complete",
                                                "payload": {
                                                    "collection": coll_name,
                                                    "reranked_count": len(reranked),
                                                    "session_id": self.session_id
                                                }
                                            }, event="notification")

                                        reranked_results = [r for r in reranked_results
                                                          if r.get("metadata", {}).get("collection_id") != coll_config["id"]]
                                        reranked_results.extend(reranked)

                            # Limit total documents
                            final_results = reranked_results[:max_docs]

                            # Enrich documents with collection_name
                            for doc in final_results:
                                if not doc.get("collection_name"):
                                    coll_id = doc.get("collection_id")
                                    if coll_id:
                                        coll_meta = self.rag_retriever.get_collection_metadata(coll_id)
                                        if coll_meta:
                                            doc["collection_name"] = coll_meta.get("name", "Unknown")

                            # Format knowledge context for agent
                            knowledge_context_str = self._format_knowledge_for_prompt(final_results, max_tokens)

                            # Build detailed event data for Live Status panel
                            collection_names = set()
                            for doc in final_results:
                                collection_name = doc.get("collection_name", "Unknown")
                                collection_names.add(collection_name)
                                doc_metadata = doc.get("metadata", {})

                                # Try title first (user-friendly name), then filename
                                source_name = doc_metadata.get("title") or doc_metadata.get("filename")

                                # If no title or filename, check if this is an imported collection
                                if not source_name:
                                    if "(Imported)" in collection_name or doc_metadata.get("source") == "import":
                                        source_name = "No Document Source (Imported)"
                                    else:
                                        source_name = "Unknown Source"

                                knowledge_chunks.append({
                                    "source": source_name,
                                    "content": doc.get("content", ""),
                                    "similarity_score": doc.get("similarity_score", 0),
                                    "document_id": doc.get("document_id"),
                                    "chunk_index": doc.get("chunk_index", 0)
                                })

                            knowledge_accessed = list(collection_names)

                            # Calculate retrieval duration
                            retrieval_duration_ms = int((time.time() - retrieval_start_time) * 1000)

                            # Store event data for SSE emission and turn summary
                            # Include chunks for live status window display
                            knowledge_retrieval_event_data = {
                                "collections": list(collection_names),
                                "document_count": len(final_results),
                                "duration_ms": retrieval_duration_ms,
                                "summary": f"Retrieved {len(final_results)} documents from {len(collection_names)} collection(s)",
                                "chunks": knowledge_chunks  # Include full chunks for UI display
                            }

                            # Emit completion event for Live Status panel (replaces old single event)
                            yield self._format_sse_with_depth({
                                "type": "knowledge_retrieval_complete",
                                "payload": knowledge_retrieval_event_data
                            }, event="notification")

                            app_logger.info(f"📚 Retrieved {len(final_results)} knowledge documents from {len(collection_names)} collection(s) in {retrieval_duration_ms}ms")

                except Exception as e:
                    app_logger.error(f"Error during knowledge retrieval for conversation_with_tools: {e}", exc_info=True)
                    # Continue without knowledge (graceful degradation)
            # --- END KNOWLEDGE RETRIEVAL ---

            # Create and execute agent with real-time SSE event handler
            # Pass self.event_handler for immediate SSE streaming during execution
            agent = ConversationAgentExecutor(
                profile=profile_config,
                user_uuid=self.user_uuid,
                session_id=self.session_id,
                llm_instance=llm_instance,
                mcp_tools=all_tools,
                async_event_handler=self.event_handler,  # Real-time SSE via asyncio.create_task()
                max_iterations=5,
                conversation_history=conversation_history,
                knowledge_context=knowledge_context_str if knowledge_enabled else None,
                document_context=self.document_context,
                multimodal_content=self.multimodal_content,
                turn_number=self.current_turn_number,
                provider=self.current_provider,  # NEW: Pass provider for event tracking
                model=self.current_model,        # NEW: Pass model for event tracking
                canvas_context=self._format_canvas_context()  # Canvas bidirectional context
            )

            # Execute agent (events are emitted in real-time via async_event_handler)
            result = await agent.execute(self.original_user_input)

            # Note: Events are now emitted in real-time via asyncio.create_task() in the agent
            # The collected_events in result are used for session storage/replay only

            # Extract result data
            response_text = result.get("response", "")
            tools_used = result.get("tools_used", [])
            success = result.get("success", False)
            duration_ms = result.get("duration_ms", 0)
            input_tokens = result.get("input_tokens", 0)
            output_tokens = result.get("output_tokens", 0)

            # Include component-internal LLM tokens (e.g., chart mapping resolution).
            # These are NOT captured by LangChain callbacks but were already persisted
            # to session DB by call_llm_api → update_token_count (handler.py:1082).
            comp_llm_in = result.get("component_llm_input_tokens", 0)
            comp_llm_out = result.get("component_llm_output_tokens", 0)
            combined_input = input_tokens + comp_llm_in
            combined_output = output_tokens + comp_llm_out

            # Update turn token counters with combined totals
            self.turn_input_tokens += combined_input
            self.turn_output_tokens += combined_output

            # CRITICAL: Conversation agent uses LangChain directly (not llm_handler)
            # so we must explicitly update session token counts here.
            # NOTE: Only add LangChain tokens — component tokens already in DB.
            if input_tokens > 0 or output_tokens > 0:
                await session_manager.update_token_count(
                    self.user_uuid,
                    self.session_id,
                    input_tokens,
                    output_tokens
                )

            # Emit token update event with updated session totals
            updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
            if updated_session:
                # Calculate cost using combined tokens (LangChain + component LLM)
                _conv_cost = 0
                try:
                    from trusted_data_agent.core.cost_manager import CostManager
                    _conv_cost = CostManager().calculate_cost(
                        provider=self.current_provider or "Unknown",
                        model=self.current_model or "Unknown",
                        input_tokens=combined_input,
                        output_tokens=combined_output
                    )
                except Exception:
                    pass
                yield self._format_sse_with_depth({
                    "statement_input": combined_input,
                    "statement_output": combined_output,
                    "turn_input": self.turn_input_tokens,
                    "turn_output": self.turn_output_tokens,
                    "total_input": updated_session.get("input_tokens", 0),
                    "total_output": updated_session.get("output_tokens", 0),
                    "call_id": str(uuid.uuid4()),
                    "cost_usd": _conv_cost
                }, "token_update")

            # Format the response using OutputFormatter's markdown renderer
            # This ensures consistent formatting with other profile types
            formatter_kwargs = {
                "llm_response_text": response_text,  # Triggers markdown rendering
                "collected_data": [],  # No structured data from conversation agent
                "original_user_input": self.original_user_input,
                "active_prompt_name": None
            }
            formatter = OutputFormatter(**formatter_kwargs)
            final_html, tts_payload = formatter.render()

            # Append component rendering HTML (chart, code, audio, video, etc.)
            from trusted_data_agent.components.utils import generate_component_html
            final_html += generate_component_html(result.get("component_payloads", []))

            # Add assistant message to conversation history (with HTML for display)
            await session_manager.add_message_to_histories(
                user_uuid=self.user_uuid,
                session_id=self.session_id,
                role='assistant',
                content=response_text,  # Clean text for LLM consumption
                html_content=final_html,  # Formatted HTML for UI display
                profile_tag=profile_tag,
                is_session_primer=self.is_session_primer
            )

            # Update session metadata
            await session_manager.update_models_used(
                self.user_uuid,
                self.session_id,
                self.current_provider,
                self.current_model,
                profile_tag
            )

            # Collect system events for plan reload (like session name generation)
            system_events = []

            # Generate session name if first turn (using unified generator)
            if self.current_turn_number == 1:
                async for name_result in self._generate_and_emit_session_name():
                    if isinstance(name_result, str):
                        # SSE event - yield to frontend
                        yield name_result
                    else:
                        # Final result tuple: (name, input_tokens, output_tokens, collected_events)
                        new_name, name_input_tokens, name_output_tokens, name_events = name_result
                        system_events.extend(name_events)

                        # Add session name tokens to turn totals and session totals
                        if name_input_tokens > 0 or name_output_tokens > 0:
                            self.turn_input_tokens += name_input_tokens
                            self.turn_output_tokens += name_output_tokens
                            await session_manager.update_token_count(
                                self.user_uuid, self.session_id, name_input_tokens, name_output_tokens
                            )
                            # Emit token_update event so UI reflects updated session totals
                            updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
                            if updated_session:
                                from trusted_data_agent.core.cost_manager import CostManager as _CM1
                                _name_cost = _CM1().calculate_cost(
                                    provider=self.current_provider or "Unknown",
                                    model=self.current_model or "Unknown",
                                    input_tokens=name_input_tokens,
                                    output_tokens=name_output_tokens
                                )
                                yield self._format_sse_with_depth({
                                    "statement_input": name_input_tokens,
                                    "statement_output": name_output_tokens,
                                    "turn_input": self.turn_input_tokens,
                                    "turn_output": self.turn_output_tokens,
                                    "total_input": updated_session.get("input_tokens", 0),
                                    "total_output": updated_session.get("output_tokens", 0),
                                    "call_id": "session_name_generation",
                                    "cost_usd": _name_cost
                                }, "token_update")

                        if new_name and new_name != "New Chat":
                            await session_manager.update_session_name(self.user_uuid, self.session_id, new_name)
                            yield self._format_sse_with_depth({
                                "session_id": self.session_id,
                                "newName": new_name
                            }, "session_name_update")

            # Emit final answer with formatted HTML
            yield self._format_sse_with_depth({
                "step": "Finished",
                "final_answer": final_html,  # Send formatted HTML
                "final_answer_text": response_text,  # Also include clean text
                "turn_id": self.current_turn_number,
                "session_id": self.session_id,  # Include session_id for filtering when switching sessions
                "tts_payload": tts_payload,
                "source": self.source,
                "is_session_primer": self.is_session_primer
            }, "final_answer")

            # Get session data for session token totals (needed for plan reload display)
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)
            session_input_tokens = session_data.get("input_tokens", 0) if session_data else 0
            session_output_tokens = session_data.get("output_tokens", 0) if session_data else 0

            # Calculate turn cost for persistence
            turn_cost = 0.0
            try:
                from trusted_data_agent.core.cost_manager import CostManager
                cost_manager = CostManager()
                turn_cost = cost_manager.calculate_cost(
                    provider=self.current_provider,
                    model=self.current_model,
                    input_tokens=self.turn_input_tokens,
                    output_tokens=self.turn_output_tokens
                )
                app_logger.debug(f"[conversation_with_tools] Turn {self.current_turn_number} cost: ${turn_cost:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate turn cost: {e}", exc_info=True)

            # Calculate session cost (cumulative up to and including this turn)
            session_cost_usd = 0.0
            try:
                previous_session_cost = self._calculate_session_cost_at_turn(session_data)
                session_cost_usd = previous_session_cost + turn_cost  # Add current turn
                app_logger.debug(f"[conversation_with_tools] Session cost at turn {self.current_turn_number}: ${session_cost_usd:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate session cost: {e}", exc_info=True)

            # Save turn data to workflow_history for session reload
            turn_summary = {
                "turn": self.current_turn_number,
                "user_query": self.original_user_input,
                "final_summary_text": response_text,  # Clean text for LLM context
                "final_summary_html": final_html,  # Formatted HTML for session reload
                "status": "success" if success else "failed",
                "is_session_primer": self.is_session_primer,  # Flag for RAG case filtering
                "execution_trace": [],
                "tools_used": tools_used,
                "conversation_agent_events": result.get("collected_events", []),
                "system_events": system_events,  # Session name generation and other system operations (UI replay only)
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": self.current_provider,
                "model": self.current_model,
                "profile_tag": profile_tag,
                "profile_type": "conversation_with_tools",
                "duration_ms": duration_ms,
                "session_id": self.session_id,
                "turn_input_tokens": self.turn_input_tokens,  # Cumulative turn total (includes all LLM calls like reranking)
                "turn_output_tokens": self.turn_output_tokens,  # Cumulative turn total
                "turn_cost": turn_cost,  # NEW - Cost at time of execution
                "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                # Session totals at the time of this turn (for plan reload)
                "session_input_tokens": session_input_tokens,
                "session_output_tokens": session_output_tokens,
                # Knowledge retrieval tracking for session reload
                "knowledge_accessed": knowledge_accessed,
                "knowledge_retrieval_event": knowledge_retrieval_event_data,
                # UI-only: Full document chunks for plan reload display (not sent to LLM)
                "knowledge_chunks_ui": knowledge_chunks if knowledge_enabled else [],
                # Pre-processing skills applied to this turn
                "skills_applied": self.skill_result.to_applied_list() if self.skill_result and self.skill_result.has_content else []
            }

            await session_manager.update_last_turn_data(self.user_uuid, self.session_id, turn_summary)
            app_logger.info(f"✅ conversation_with_tools execution completed: {len(tools_used)} tools used")

        except Exception as e:
            app_logger.error(f"conversation_with_tools execution error: {e}", exc_info=True)
            error_msg = f"Agent execution failed: {str(e)}"
            yield self._format_sse_with_depth({"step": "Error", "error": error_msg}, "error")

            # Get session data for session cost calculation
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)

            # Calculate turn cost for error case
            turn_cost = 0.0
            try:
                from trusted_data_agent.core.cost_manager import CostManager
                cost_manager = CostManager()
                turn_cost = cost_manager.calculate_cost(
                    provider=self.current_provider,
                    model=self.current_model,
                    input_tokens=self.turn_input_tokens,
                    output_tokens=self.turn_output_tokens
                )
                app_logger.debug(f"[conversation_with_tools-error] Turn {self.current_turn_number} cost: ${turn_cost:.6f}")
            except Exception as cost_err:
                app_logger.warning(f"Failed to calculate turn cost for error case: {cost_err}")

            # Calculate session cost (cumulative up to and including this turn)
            session_cost_usd = 0.0
            try:
                previous_session_cost = self._calculate_session_cost_at_turn(session_data)
                session_cost_usd = previous_session_cost + turn_cost
                app_logger.debug(f"[conversation_with_tools-error] Session cost at turn {self.current_turn_number}: ${session_cost_usd:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate session cost for error case: {e}")

            # Save error turn data
            turn_summary = {
                "turn": self.current_turn_number,
                "user_query": self.original_user_input,
                "final_summary_text": error_msg,
                "status": "failed",
                "is_session_primer": self.is_session_primer,  # Flag for RAG case filtering
                "error": str(e),
                "profile_tag": profile_config.get("tag", "CONV"),
                "profile_type": "conversation_with_tools",
                "turn_input_tokens": self.turn_input_tokens,  # Accumulated tokens up to failure
                "turn_output_tokens": self.turn_output_tokens,
                "turn_cost": turn_cost,  # NEW - Cost at time of error
                "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "skills_applied": self.skill_result.to_applied_list() if self.skill_result and self.skill_result.has_content else []
            }
            await session_manager.update_last_turn_data(self.user_uuid, self.session_id, turn_summary)

    def _format_canvas_context(self) -> Optional[str]:
        """Format open canvas state as context string for LLM injection.

        Returns:
            Formatted context string or None if no canvas is open.
        """
        if not self.canvas_context:
            return None
        title = self.canvas_context.get("title", "Canvas")
        language = self.canvas_context.get("language", "text")
        content = self.canvas_context.get("content", "")
        modified = self.canvas_context.get("modified", False)

        status = "modified by user" if modified else "as generated"
        return (
            f"# Open Canvas: {title}\n"
            f"Language: {language} | Status: {status}\n"
            f"The user has this canvas open in the side panel. "
            f"When they refer to \"the canvas\", \"the code\", \"the page\", or \"it\", they mean this content.\n"
            f"If asked to modify it, use TDA_Canvas with the same title to update it.\n"
            f"```{language}\n{content}\n```"
        )

    async def _build_user_message_for_conversation(self, knowledge_context: Optional[str] = None, document_context: Optional[str] = None) -> str:
        """Build user message for LLM-only direct execution.

        System prompt is handled separately via system_prompt_override parameter.
        This method builds only the user-facing content: document context + knowledge context + conversation history + current query.

        IMPORTANT: This retrieves conversation history from session_id, which is
        SHARED across all profile switches. This means LLM-only profiles can
        reference and build upon results from previous tool-enabled turns.

        Example flow:
          Turn 1 (@SQL): "Query products table" → Returns SQL results
          Turn 2 (@CHAT): "Summarize those results" → Sees SQL results in history

        Args:
            knowledge_context: Optional knowledge context to inject before conversation history
            document_context: Optional uploaded document context to inject

        Returns:
            User message string with documents + knowledge + history + current query
        """
        # Get session history (includes ALL previous turns regardless of profile)
        try:
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)
            session_history = session_data.get('chat_object', []) if session_data else []

            # Format last 10 messages for context, filtering out invalid messages
            history_text = "\n".join([
                f"{'User' if msg.get('role') == 'user' else 'Assistant'}: {msg.get('content', '')}"
                for msg in session_history[-10:]
                if msg.get("isValid") is not False  # Skip messages marked as invalid
            ])
        except Exception as e:
            app_logger.error(f"Failed to load session history: {e}")
            history_text = "(No conversation history available)"

        # Build user message (WITHOUT system prompt)
        user_message_parts = []

        # Inject open canvas context if present (bidirectional context)
        canvas_ctx = self._format_canvas_context()
        if canvas_ctx:
            user_message_parts.append(canvas_ctx)

        # Inject uploaded document context if present
        if document_context:
            user_message_parts.append(f"# Uploaded Documents\n{document_context}")

        # Inject knowledge context if retrieved
        if knowledge_context:
            user_message_parts.append(knowledge_context)

        # Add conversation history and current query
        user_message_parts.append(f"""Previous conversation:
{history_text}

User: {self.original_user_input}""")

        return "\n".join(user_message_parts)

    async def _build_user_message_for_rag_synthesis(self, knowledge_context: str, document_context: Optional[str] = None) -> str:
        """Build user message for RAG focused synthesis with knowledge + history.

        Args:
            knowledge_context: Formatted knowledge context from retrieval
            document_context: Optional uploaded document context to inject

        Returns:
            User message string with documents + knowledge + optional history + current query
        """
        parts = []

        # Inject open canvas context if present (bidirectional context)
        canvas_ctx = self._format_canvas_context()
        if canvas_ctx:
            parts.append(canvas_ctx)

        # Inject uploaded document context if present
        if document_context:
            parts.append(f"# Uploaded Documents\n{document_context}")

        # Knowledge context (most important)
        if knowledge_context:
            parts.append(knowledge_context)

        # Conversation history (for follow-ups) - only if history not disabled
        if not self.disabled_history:
            try:
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                session_history = session_data.get('chat_object', []) if session_data else []

                if session_history:
                    # Format last 10 messages for context, filtering out invalid messages
                    history_text = "\n".join([
                        f"{'User' if msg.get('role') == 'user' else 'Assistant'}: {msg.get('content', '')}"
                        for msg in session_history[-10:]
                        if msg.get("isValid") is not False  # Skip messages marked as invalid
                    ])
                    if history_text:
                        parts.append(f"\n--- CONVERSATION HISTORY ---\n{history_text}\n")
            except Exception as e:
                app_logger.error(f"Error retrieving conversation history for RAG synthesis: {e}", exc_info=True)
                # Continue without history (graceful degradation)

        # Current query
        parts.append(f"\n--- CURRENT QUERY ---\n{self.original_user_input}\n")

        return "\n".join(parts)

    def _get_profile_config(self) -> Dict[str, Any]:
        """Get current profile configuration (with override support)."""
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()

        if self.profile_override_id:
            profiles = config_manager.get_profiles(self.user_uuid)
            override = next((p for p in profiles if p['id'] == self.profile_override_id), None)
            if override:
                return override

        default_profile_id = config_manager.get_default_profile_id(self.user_uuid)
        if default_profile_id:
            default = config_manager.get_profile(default_profile_id, self.user_uuid)
            if default:
                return default

        return {}


    def _format_knowledge_for_prompt(
        self,
        results: List[Dict[str, Any]],
        max_tokens: int = 2000
    ) -> str:
        """Format knowledge documents for prompt injection with token limiting."""
        if not results:
            return ""

        formatted_docs = []
        total_chars = 0
        char_limit = max_tokens * 4  # 1 token ≈ 4 chars

        for doc in results:
            content = doc.get("content", "")
            metadata = doc.get("metadata", {})
            # Get collection_name from document level (matching RAG retriever behavior)
            collection_name = doc.get("collection_name", "Unknown")

            # Try title first (user-friendly name), then filename
            source = metadata.get("title") or metadata.get("filename")

            # If no title or filename, fall back to collection name
            if not source:
                source = collection_name if collection_name != "Unknown" else "Unknown Source"

            doc_text = f"""
Source: {source} (Collection: {collection_name})
Content: {content}
---"""

            if total_chars + len(doc_text) > char_limit:
                app_logger.info(f"Knowledge context truncated at {len(formatted_docs)} documents")
                break

            formatted_docs.append(doc_text)
            total_chars += len(doc_text)

        return "\n".join(formatted_docs)


    async def _rerank_knowledge_with_llm(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        max_docs: int
    ) -> List[Dict[str, Any]]:
        """Rerank knowledge documents using LLM for improved relevance."""
        if not documents or not self.llm_handler:
            return documents

        docs_text = "\n\n".join([
            f"Document {i+1}:\n{doc.get('content', '')[:500]}"
            for i, doc in enumerate(documents)
        ])

        rerank_prompt = f"""You are helping rank documents by relevance to a query.

Query: {query}

Documents:
{docs_text}

Rank these documents by relevance to the query. Return ONLY a JSON array of document numbers in order of relevance (most relevant first).
Example: [3, 1, 5, 2, 4]

Response:"""

        try:
            response_text, _, _ = await self._call_llm_and_update_tokens(
                prompt=rerank_prompt,
                reason="Knowledge Reranking",
                source="knowledge_retrieval"
            )

            import json
            import re
            match = re.search(r'\[[\d,\s]+\]', response_text)
            if match:
                ranking = json.loads(match.group(0))
                reranked = []
                for doc_num in ranking[:max_docs]:
                    if 0 < doc_num <= len(documents):
                        reranked.append(documents[doc_num - 1])
                return reranked if reranked else documents[:max_docs]

        except Exception as e:
            app_logger.warning(f"Reranking failed, using original order: {e}")

        return documents[:max_docs]


    def _emit_lifecycle_event(self, event_type: str, event_data: dict):
        """
        Emit lifecycle event with standardized structure.

        This helper creates lifecycle events (execution_start, execution_complete,
        execution_error, execution_cancelled) with consistent payload structure across
        all profile types.

        Args:
            event_type: Type of lifecycle event ('execution_start', 'execution_complete', etc.)
            event_data: Event-specific data to include in payload

        Returns:
            Formatted SSE event dict
        """
        # Build base payload with common fields
        base_payload = {
            "profile_type": event_data.get("profile_type", "tool_enabled"),
            "session_id": self.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "turn_id": self.current_turn_number,
            "profile_tag": event_data.get("profile_tag", self.active_profile_id),
            "provider": self.current_provider,
            "model": self.current_model,
        }

        # Merge with event-specific data
        full_payload = {**base_payload, **event_data}

        # Return formatted SSE event
        return self._format_sse_with_depth({"type": event_type, "payload": full_payload}, event="notification")


    def _classify_error(self, exception: Exception) -> str:
        """
        Classify exception into user-friendly error type.

        This helper categorizes exceptions for better error reporting and tracking.

        Args:
            exception: The exception to classify

        Returns:
            String error type ('rate_limit', 'quota_exceeded', 'llm_error', 'tool_error', 'system_error')
        """
        error_str = str(exception).lower()

        if "rate limit" in error_str or "429" in error_str:
            return "rate_limit"
        elif "quota" in error_str or "insufficient" in error_str:
            return "quota_exceeded"
        elif "llm" in error_str or "model" in error_str or "anthropic" in error_str or "openai" in error_str:
            return "llm_error"
        elif "tool" in error_str or "mcp" in error_str:
            return "tool_error"
        elif "cancelled" in error_str or "canceled" in error_str:
            return "cancelled"
        else:
            return "system_error"


    async def run(self):
        """The main, unified execution loop for the agent."""
        final_answer_override = None
        
        # --- CONSUMPTION ENFORCEMENT START ---
        # Check rate limits and token quotas BEFORE execution
        try:
            from trusted_data_agent.auth.database import get_db_session
            from trusted_data_agent.auth.consumption_manager import ConsumptionManager
            
            with get_db_session() as db_session:
                manager = ConsumptionManager(db_session)
                
                # Check rate limits
                rate_allowed, rate_reason = manager.check_rate_limits(self.user_uuid)
                if not rate_allowed:
                    error_msg = f"Rate limit exceeded: {rate_reason}"
                    app_logger.warning(f"Blocking execution for user {self.user_uuid}: {error_msg}")
                    raise ValueError(error_msg)
                
                # Check token quotas
                quota_allowed, quota_reason = manager.check_token_quota(self.user_uuid)
                if not quota_allowed:
                    error_msg = f"Token quota exceeded: {quota_reason}"
                    app_logger.warning(f"Blocking execution for user {self.user_uuid}: {error_msg}")
                    raise ValueError(error_msg)
                
                app_logger.debug(f"Consumption checks passed for user {self.user_uuid}")
        except ValueError:
            # Re-raise quota/rate limit errors
            raise
        except Exception as e:
            # Non-critical: If enforcement fails, allow execution (fail-open)
            app_logger.error(f"Failed to check consumption limits for user {self.user_uuid}: {e}")
        # --- CONSUMPTION ENFORCEMENT END ---
        
        # --- LLM-ONLY PROFILE: DIRECT EXECUTION PATH START ---
        # Detect if using LLM-only profile and bypass planner if so
        profile_type = self._detect_profile_type()
        # Check if llm_only profile has MCP tools enabled (routes to LangChain agent path instead)
        profile_config = self._get_profile_config()
        use_mcp_tools = profile_config.get("useMcpTools", False)
        # Check if profile has active component tools (e.g., TDA_Charting) — platform feature
        # Component tools require tool-calling capability, so profiles with active components
        # auto-upgrade to the conversation agent path (LangChain) even without MCP tools.
        from trusted_data_agent.components.manager import get_component_manager as _get_comp_mgr
        _comp_mgr = _get_comp_mgr()
        has_component_tools = _comp_mgr.has_active_tool_components(profile_config)
        # Only pure llm_only (without MCP tools AND without component tools) goes through direct execution
        is_llm_only = (profile_type == "llm_only" and not use_mcp_tools and not has_component_tools)

        # --- Document upload: Load document context with multimodal routing ---
        if self.attachments:
            self.multimodal_content, text_fallback = load_multimodal_document_content(
                self.user_uuid, self.session_id, self.attachments,
                self.current_provider, self.current_model
            )
            # Always set text context (for planning, text-only files, and as fallback)
            self.document_context = text_fallback
            if not self.document_context and not self.multimodal_content:
                # Pure fallback: use text extraction for everything
                self.document_context, doc_trunc_events = load_document_context(self.user_uuid, self.session_id, self.attachments)
                for evt in doc_trunc_events:
                    event_data = {"step": "Context Optimization", "type": "context_optimization", "details": evt}
                    self._log_system_event(event_data)
                    yield self._format_sse_with_depth(event_data)

            if self.multimodal_content:
                app_logger.info(f"Native multimodal: {len(self.multimodal_content)} block(s) for {self.current_provider}")
            if self.document_context:
                app_logger.info(f"Document context loaded: {len(self.document_context):,} chars from {len(self.attachments)} attachment(s)")

        # --- MODIFICATION START: Calculate turn number from workflow_history ---
        # All profile types (llm_only, rag_focused, tool_enabled) use workflow_history for consistency
        self.current_turn_number = 1
        session_data = await session_manager.get_session(self.user_uuid, self.session_id)

        if session_data and isinstance(session_data.get("last_turn_data", {}).get("workflow_history"), list):
            self.current_turn_number = len(session_data["last_turn_data"]["workflow_history"]) + 1

        is_rag_focused = (profile_type == "rag_focused")
        profile_label = "rag_focused" if is_rag_focused else ("llm_only" if is_llm_only else "tool_enabled")
        app_logger.info(f"PlanExecutor initialized for {profile_label} turn: {self.current_turn_number}")
        # --- MODIFICATION END ---

        # --- PROFILE LLM INSTANCE: Create profile-specific LLM client when provider differs ---
        # The global APP_STATE['llm'] is set at login from the user's default profile.
        # When the active profile (via @TAG override) uses a different LLM provider,
        # we need a matching client instance. This is stored on self.profile_llm_instance
        # (local to this executor, no global state modification) and used by _call_llm_and_update_tokens.
        # The tool_enabled path has its own override mechanism at line ~3400, so this
        # primarily serves llm_only, rag_focused, and conversation_with_tools profiles.
        current_user_provider = get_user_provider(self.user_uuid)
        current_user_model = get_user_model(self.user_uuid)
        if self.current_provider and (self.current_provider != current_user_provider or self.current_model != current_user_model):
            app_logger.info(f"🔄 Profile uses different LLM than default: {self.current_provider}/{self.current_model} vs {current_user_provider}/{current_user_model}")
            try:
                from trusted_data_agent.llm.client_factory import create_llm_client
                from trusted_data_agent.core.configuration_service import retrieve_credentials_for_provider

                credentials_result = await retrieve_credentials_for_provider(self.user_uuid, self.current_provider)
                credentials = credentials_result.get("credentials", {})

                if credentials:
                    # Merge with profile LLM config credentials if available
                    try:
                        from trusted_data_agent.core.config_manager import get_config_manager
                        config_manager = get_config_manager()
                        if self.active_profile_id:
                            profiles = config_manager.get_profiles(self.user_uuid)
                            active_profile = next((p for p in profiles if p.get("id") == self.active_profile_id), None)
                            if active_profile:
                                llm_config_id = active_profile.get('llmConfigurationId')
                                if llm_config_id:
                                    llm_configs = config_manager.get_llm_configurations(self.user_uuid)
                                    llm_config = next((cfg for cfg in llm_configs if cfg['id'] == llm_config_id), None)
                                    if llm_config and llm_config.get('credentials'):
                                        credentials = {**credentials, **llm_config['credentials']}
                    except Exception as e:
                        app_logger.debug(f"Could not merge profile LLM config credentials: {e}")

                    self.profile_llm_instance = await create_llm_client(self.current_provider, self.current_model, credentials)
                    app_logger.info(f"✅ Created profile-specific LLM instance: {self.current_provider}/{self.current_model}")
                else:
                    app_logger.warning(f"No credentials found for profile provider {self.current_provider}, falling back to global LLM instance")
            except Exception as e:
                app_logger.warning(f"Failed to create profile-specific LLM instance for {self.current_provider}/{self.current_model}: {e}")
                app_logger.warning(f"Falling back to global LLM instance — provider branching in call_llm_api will still use correct provider path")
        # --- PROFILE LLM INSTANCE END ---

        # --- DUAL-MODEL LLM INSTANCES: Create strategic and tactical clients ---
        # When dual-model is active, create separate client instances for each model
        # because they may use different providers (e.g., Google for strategic, Friendli for tactical)
        if self.is_dual_model_active:
            try:
                from trusted_data_agent.llm.client_factory import create_llm_client
                from trusted_data_agent.auth.encryption import decrypt_credentials

                # Create strategic LLM instance
                # Credentials are stored per-provider in user_credentials table, not in LLM configs
                strategic_creds = decrypt_credentials(self.user_uuid, self.strategic_provider)
                if not strategic_creds:
                    raise ValueError(f"No credentials found for strategic model provider: {self.strategic_provider}")

                self.strategic_llm_instance = await create_llm_client(
                    self.strategic_provider,
                    self.strategic_model,
                    strategic_creds
                )
                app_logger.info(f"✅ Created strategic LLM instance: {self.strategic_provider}/{self.strategic_model}")

                # Create tactical LLM instance
                # Credentials are stored per-provider in user_credentials table, not in LLM configs
                tactical_creds = decrypt_credentials(self.user_uuid, self.tactical_provider)
                if not tactical_creds:
                    raise ValueError(f"No credentials found for tactical model provider: {self.tactical_provider}")

                self.tactical_llm_instance = await create_llm_client(
                    self.tactical_provider,
                    self.tactical_model,
                    tactical_creds
                )
                app_logger.info(f"✅ Created tactical LLM instance: {self.tactical_provider}/{self.tactical_model}")

            except Exception as e:
                app_logger.error(f"Failed to create dual-model LLM instances: {e}")
                # Fall back to single-model mode - reset provider/model to base
                app_logger.warning(f"Dual-model disabled, falling back to single model: {self.current_provider}/{self.current_model}")
                self.is_dual_model_active = False
                self.strategic_llm_instance = None
                self.tactical_llm_instance = None
                self.strategic_provider = self.current_provider
                self.strategic_model = self.current_model
                self.tactical_provider = self.current_provider
                self.tactical_model = self.current_model
                app_logger.warning(f"Dual-model disabled, falling back to single model: {self.current_provider}/{self.current_model}")
        # --- DUAL-MODEL LLM INSTANCES END ---

        # --- Save dual-model configuration to session for UI display ---
        if self.is_dual_model_active and session_data:
            try:
                session_data["is_dual_model_active"] = True
                session_data["strategic_provider"] = self.strategic_provider
                session_data["strategic_model"] = self.strategic_model
                session_data["tactical_provider"] = self.tactical_provider
                session_data["tactical_model"] = self.tactical_model
                await session_manager._save_session(self.user_uuid, self.session_id, session_data)
                app_logger.debug(f"[Dual-Model] Saved configuration to session: strategic={self.strategic_provider}/{self.strategic_model}, tactical={self.tactical_provider}/{self.tactical_model}")
            except Exception as e:
                app_logger.warning(f"Failed to save dual-model configuration to session: {e}")
        elif session_data:
            # Clear dual-model metadata when switching to single-model (e.g., profile override expires)
            try:
                session_data["is_dual_model_active"] = False
                # Remove dual-model specific fields to prevent stale UI indicators
                session_data.pop("strategic_provider", None)
                session_data.pop("strategic_model", None)
                session_data.pop("tactical_provider", None)
                session_data.pop("tactical_model", None)
                await session_manager._save_session(self.user_uuid, self.session_id, session_data)
                app_logger.debug("[Dual-Model] Cleared dual-model metadata (switched to single-model)")
            except Exception as e:
                app_logger.warning(f"Failed to clear dual-model metadata: {e}")
        # --- Dual-model configuration saved ---

        if is_llm_only:
            # DIRECT EXECUTION PATH - Bypass planner entirely
            app_logger.info("🗨️ LLM-only profile detected - direct execution mode")

            # Initialize event collection for plan reload (similar to rag_focused)
            llm_execution_events = []

            # Get profile configuration early for event details
            profile_config = self._get_profile_config()
            profile_tag = profile_config.get("tag", "CHAT")
            profile_name = profile_config.get("name", "Conversation")

            # Get conversation context stats
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)
            history_length = len(session_data.get("session_history", [])) if session_data else 0
            turn_number = self.current_turn_number

            # Get knowledge config
            knowledge_config = profile_config.get("knowledgeConfig", {})
            knowledge_enabled = knowledge_config.get("enabled", False)
            knowledge_collections = knowledge_config.get("collections", [])
            knowledge_collection_names = [c.get("name", "Unknown") for c in knowledge_collections] if knowledge_enabled else []

            # NOTE: Don't emit llm_execution event yet - wait until we have the actual prompts
            # Store metadata for now, will emit after loading prompts

            # --- PHASE 2: Emit execution_start lifecycle event for llm_only ---
            try:
                start_event = self._emit_lifecycle_event("execution_start", {
                    "profile_type": "llm_only",
                    "profile_tag": profile_tag,
                    "query": self.original_user_input,
                    "history_length": history_length,
                    "knowledge_enabled": knowledge_enabled,
                    "knowledge_collections": len(knowledge_collections) if knowledge_enabled else 0
                })
                yield start_event
                app_logger.info("✅ Emitted execution_start event for llm_only profile")
            except Exception as e:
                # Silent failure - don't break execution
                app_logger.warning(f"Failed to emit execution_start event: {e}")
            # --- PHASE 2 END ---

            # --- NEW: Knowledge Retrieval for LLM-Only ---
            knowledge_context_str = None
            knowledge_accessed = []

            if knowledge_enabled and self.rag_retriever:
                app_logger.info("🔍 Knowledge retrieval enabled for llm_only profile")

                try:
                    knowledge_collections = knowledge_config.get("collections", [])
                    # Use three-tier configuration (global -> profile -> locks)
                    from trusted_data_agent.core.config_manager import get_config_manager
                    config_manager = get_config_manager()
                    effective_config = config_manager.get_effective_knowledge_config(knowledge_config)
                    max_docs = effective_config.get("maxDocs", APP_CONFIG.KNOWLEDGE_RAG_NUM_DOCS)
                    min_relevance = effective_config.get("minRelevanceScore", APP_CONFIG.KNOWLEDGE_MIN_RELEVANCE_SCORE)
                    max_tokens = effective_config.get("maxTokens", APP_CONFIG.KNOWLEDGE_MAX_TOKENS)

                    if knowledge_collections:
                        collection_ids = [c["id"] for c in knowledge_collections]

                        # Create access context (same as planner)
                        from trusted_data_agent.agent.rag_access_context import RAGAccessContext
                        rag_context = RAGAccessContext(
                            user_id=self.user_uuid,
                            retriever=self.rag_retriever
                        )

                        # Retrieve knowledge documents
                        all_results = self.rag_retriever.retrieve_examples(
                            query=self.original_user_input,
                            k=max_docs * len(knowledge_collections),
                            min_score=min_relevance,
                            allowed_collection_ids=set(collection_ids),
                            rag_context=rag_context,
                            repository_type="knowledge"  # Filter for knowledge only
                        )

                        if all_results:
                            # Apply reranking if configured
                            reranked_results = all_results
                            for coll_config in knowledge_collections:
                                if coll_config.get("reranking", False):
                                    coll_results = [r for r in all_results
                                                  if r.get("metadata", {}).get("collection_id") == coll_config["id"]]
                                    if coll_results and self.llm_handler:
                                        reranked = await self._rerank_knowledge_with_llm(
                                            query=self.original_user_input,
                                            documents=coll_results,
                                            max_docs=max_docs
                                        )
                                        reranked_results = [r for r in reranked_results
                                                          if r.get("metadata", {}).get("collection_id") != coll_config["id"]]
                                        reranked_results.extend(reranked)

                            # Limit total documents
                            final_results = reranked_results[:max_docs]

                            # Enrich documents with collection_name at document level (matching RAG retriever behavior)
                            for doc in final_results:
                                # If collection_name is missing, fetch from collection metadata
                                if not doc.get("collection_name"):
                                    coll_id = doc.get("collection_id")
                                    if coll_id and self.rag_retriever:
                                        coll_meta = self.rag_retriever.get_collection_metadata(coll_id)
                                        if coll_meta:
                                            doc["collection_name"] = coll_meta.get("name", "Unknown")
                                            app_logger.info(f"Enriched doc with collection_name: {doc['collection_name']}")

                            # Format knowledge context
                            knowledge_docs = self._format_knowledge_for_prompt(final_results, max_tokens)

                            if knowledge_docs.strip():
                                knowledge_context_str = f"""

--- KNOWLEDGE CONTEXT ---
The following domain knowledge may be relevant to this conversation:

{knowledge_docs}

(End of Knowledge Context)
"""

                                # Track accessed collections (get collection_name from document level)
                                knowledge_accessed = []
                                for r in final_results:
                                    r_metadata = r.get("metadata", {})
                                    r_collection_name = r.get("collection_name", "Unknown")

                                    # Try title first (user-friendly name), then filename
                                    source_name = r_metadata.get("title") or r_metadata.get("filename")

                                    # If no title or filename, check if this is an imported collection
                                    if not source_name:
                                        if "(Imported)" in r_collection_name or r_metadata.get("source") == "import":
                                            source_name = "No Document Source (Imported)"
                                        else:
                                            source_name = "Unknown Source"

                                    knowledge_accessed.append({
                                        "collection_id": r.get("collection_id"),
                                        "collection_name": r_collection_name,
                                        "source": source_name
                                    })

                                # Build detailed chunks metadata (matching planner.py format)
                                knowledge_chunks = []
                                collection_names = set()
                                for doc in final_results:
                                    # Get collection_name from document level, not metadata
                                    collection_name = doc.get("collection_name", "Unknown")
                                    collection_names.add(collection_name)

                                    # Get metadata for source info
                                    doc_metadata = doc.get("metadata", {})

                                    # Try title first (user-friendly name), then filename
                                    source_name = doc_metadata.get("title") or doc_metadata.get("filename")

                                    # If no title or filename, check if this is an imported collection
                                    if not source_name:
                                        if "(Imported)" in collection_name or doc_metadata.get("source") == "import":
                                            source_name = "No Document Source (Imported)"
                                        else:
                                            source_name = "Unknown Source"

                                    knowledge_chunks.append({
                                        "source": source_name,
                                        "content": doc.get("content", ""),
                                        "similarity_score": doc.get("similarity_score", 0),
                                        "document_id": doc.get("document_id"),
                                        "chunk_index": doc.get("chunk_index", 0)
                                    })

                                # Build event details matching planner.py format
                                event_details = {
                                    "summary": f"Retrieved {len(final_results)} relevant document(s) from {len(collection_names)} knowledge collection(s)",
                                    "collections": list(collection_names),
                                    "document_count": len(final_results),
                                    "chunks": knowledge_chunks
                                }

                                # Emit SSE event with specific event type (like genie does)
                                event_data = {
                                    "step": "Knowledge Retrieved",
                                    "type": "knowledge_retrieval",
                                    "details": event_details
                                }
                                self._log_system_event(event_data)
                                yield self._format_sse_with_depth(event_data, "knowledge_retrieval")

                                # Collect event for plan reload
                                llm_execution_events.append({
                                    "type": "knowledge_retrieval",
                                    "payload": event_details  # Store just details for knowledge events
                                })

                except Exception as e:
                    app_logger.error(f"Error during knowledge retrieval for llm_only: {e}", exc_info=True)
                    # Continue without knowledge (graceful degradation)

            # Load system prompt separately (NOT embedded in user message)
            from trusted_data_agent.agent.prompt_loader import get_prompt_loader
            prompt_loader = get_prompt_loader()
            system_prompt = prompt_loader.get_prompt("CONVERSATION_EXECUTION")

            if not system_prompt:
                # Fallback if prompt not found
                system_prompt = "You are a helpful AI assistant. Provide natural, conversational responses."
                app_logger.warning("CONVERSATION_EXECUTION prompt not found, using fallback")

            # --- Inject component instructions ---
            from trusted_data_agent.components.manager import get_component_instructions_for_prompt
            comp_section = get_component_instructions_for_prompt(
                self.active_profile_id, self.user_uuid, session_data
            )
            system_prompt = system_prompt.replace('{component_instructions_section}', comp_section)

            # --- Inject skill content (pre-processing) ---
            if self.skill_result and self.skill_result.has_content:
                sp_block = self.skill_result.get_system_prompt_block()
                if sp_block:
                    system_prompt = f"{system_prompt}\n\n{sp_block}"

            # Load document context from uploaded files
            doc_context = None
            if self.attachments:
                doc_context, doc_trunc_events = load_document_context(self.user_uuid, self.session_id, self.attachments)
                for evt in doc_trunc_events:
                    event_data = {"step": "Context Optimization", "type": "context_optimization", "details": evt}
                    self._log_system_event(event_data)
                    yield self._format_sse_with_depth(event_data)

            # Build user message (WITHOUT system prompt)
            user_message = await self._build_user_message_for_conversation(
                knowledge_context=knowledge_context_str,
                document_context=doc_context
            )

            # Inject user_context skill content into user message
            if self.skill_result and self.skill_result.has_content:
                uc_block = self.skill_result.get_user_context_block()
                if uc_block:
                    user_message = f"{uc_block}\n\n{user_message}"

            # NOW emit llm_execution event with complete information
            event_data = {
                "step": "Calling LLM for Execution",
                "type": "llm_execution",
                "details": {
                    "profile_tag": profile_tag,
                    "profile_name": profile_name,
                    "turn_number": turn_number,
                    "history_length": history_length,
                    "knowledge_enabled": knowledge_enabled,
                    "knowledge_collections": knowledge_collection_names,
                    "model": f"{self.current_provider}/{self.current_model}",
                    "session_id": self.session_id,
                    "user_message": user_message
                }
            }
            self._log_system_event(event_data)
            yield self._format_sse_with_depth(event_data, "llm_execution")

            # Collect event for plan reload (without system prompt to save space)
            llm_execution_events.append({
                "type": "llm_execution",
                "payload": {
                    "profile_tag": profile_tag,
                    "profile_name": profile_name,
                    "turn_number": turn_number,
                    "history_length": history_length,
                    "knowledge_enabled": knowledge_enabled,
                    "knowledge_collections": knowledge_collection_names,
                    "model": f"{self.current_provider}/{self.current_model}",
                    "session_id": self.session_id,
                    "user_message": user_message
                }
            })

            # CRITICAL: Create clean dependencies without tools/prompts for llm_only
            # This prevents the LLM from seeing tool definitions and trying to use them
            clean_dependencies = {
                'STATE': {
                    'llm': self.dependencies['STATE']['llm'],
                    'mcp_tools': {},  # Empty tools
                    'structured_tools': {},  # Empty structured tools
                    'structured_prompts': {},  # Empty structured prompts
                    'prompts_context': ''  # No prompts context
                }
            }

            # Temporarily swap dependencies for this call
            original_dependencies = self.dependencies
            self.dependencies = clean_dependencies

            try:
                # Signal LLM busy for status indicator dots
                yield self._format_sse_with_depth({"target": "llm", "state": "busy"}, "status_indicator_update")

                # Call LLM with proper system/user separation
                # System prompt passed via override, user message contains only content
                response_text, input_tokens, output_tokens = await self._call_llm_and_update_tokens(
                    prompt=user_message,  # User message only (knowledge + history + query)
                    reason="Direct LLM Execution (Conversation Profile)",
                    system_prompt_override=system_prompt,  # System prompt via override (correct architecture)
                    source=self.source,
                    multimodal_content=self.multimodal_content
                )
            finally:
                # Restore original dependencies
                self.dependencies = original_dependencies

            # Signal LLM idle after call completes
            yield self._format_sse_with_depth({"target": "llm", "state": "idle"}, "status_indicator_update")

            # Emit LLM execution complete event (like RAG's rag_llm_step)
            llm_complete_event = {
                "step": "LLM Execution Complete",
                "type": "llm_execution_complete",
                "details": {
                    "summary": f"Generated response using {self.current_provider}/{self.current_model}",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model": f"{self.current_provider}/{self.current_model}",
                    "provider": self.current_provider,
                    "model_name": self.current_model,
                    "response_length": len(response_text),
                    "knowledge_used": len(knowledge_accessed) if knowledge_accessed else 0,
                    "session_id": self.session_id,
                    "response_text": response_text,  # Include actual response for expandable view
                    "cost_usd": self._last_call_metadata.get("cost_usd", 0)
                }
            }
            self._log_system_event(llm_complete_event)
            yield self._format_sse_with_depth(llm_complete_event, "llm_execution_complete")

            # Collect event for plan reload
            llm_execution_events.append({
                "type": "llm_execution_complete",
                "payload": {
                    "summary": f"Generated response using {self.current_provider}/{self.current_model}",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model": f"{self.current_provider}/{self.current_model}",
                    "provider": self.current_provider,
                    "model_name": self.current_model,
                    "response_length": len(response_text),
                    "knowledge_used": len(knowledge_accessed) if knowledge_accessed else 0,
                    "session_id": self.session_id,
                    "response_text": response_text,  # Include actual response for expandable view
                    "cost_usd": self._last_call_metadata.get("cost_usd", 0)
                }
            })

            # Emit token update event for UI
            updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
            if updated_session:
                yield self._format_sse_with_depth({
                    "statement_input": input_tokens,
                    "statement_output": output_tokens,
                    "turn_input": self.turn_input_tokens,
                    "turn_output": self.turn_output_tokens,
                    "total_input": updated_session.get("input_tokens", 0),
                    "total_output": updated_session.get("output_tokens", 0),
                    "call_id": str(uuid.uuid4()),
                    "cost_usd": self._last_call_metadata.get("cost_usd", 0)
                }, "token_update")

            # Store as final answer
            self.final_summary_text = response_text

            # Format the response using OutputFormatter's markdown renderer
            # Use llm_response_text path which has proper markdown formatting
            formatter_kwargs = {
                "llm_response_text": response_text,  # Triggers markdown rendering
                "collected_data": self.structured_collected_data,
                "original_user_input": self.original_user_input,
                "active_prompt_name": None  # No active prompt for llm_only
            }
            formatter = OutputFormatter(**formatter_kwargs)
            final_html, tts_payload = formatter.render()

            # Format and emit final answer event (UI expects 'final_answer' type)
            event_data = {
                "step": "Finished",
                "final_answer": final_html,  # Send formatted HTML
                "final_answer_text": response_text,  # Also include clean text
                "turn_id": self.current_turn_number,
                "session_id": self.session_id,  # Include session_id for filtering when switching sessions
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "tts_payload": tts_payload,
                "source": self.source,
                "is_session_primer": self.is_session_primer
            }
            self._log_system_event(event_data)
            yield self._format_sse_with_depth(event_data, "final_answer")

            # Save to session (with formatted HTML for UI)
            await session_manager.add_message_to_histories(
                self.user_uuid,
                self.session_id,
                'assistant',
                content=response_text,  # Clean text for LLM consumption
                html_content=final_html,  # Formatted HTML for UI display
                is_session_primer=self.is_session_primer
            )

            # Cost tracking for llm_only profiles
            # Note: Cost manager doesn't have log_interaction_cost method
            # Cost is already calculated and logged via _call_llm_and_update_tokens
            # No additional logging needed here

            # Collect system events for plan reload (like session name generation)
            system_events = []

            # Generate session name for first turn (using unified generator)
            if self.current_turn_number == 1:
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                if session_data and session_data.get("name") == "New Chat":
                    app_logger.info(f"First turn detected for session {self.session_id}. Attempting to generate name.")

                    async for result in self._generate_and_emit_session_name():
                        if isinstance(result, str):
                            # SSE event - yield to frontend
                            yield result
                        else:
                            # Final result tuple: (name, input_tokens, output_tokens, collected_events)
                            new_name, name_input_tokens, name_output_tokens, name_events = result
                            system_events.extend(name_events)

                            # Add session name tokens to turn totals and session totals
                            if name_input_tokens > 0 or name_output_tokens > 0:
                                self.turn_input_tokens += name_input_tokens
                                self.turn_output_tokens += name_output_tokens
                                await session_manager.update_token_count(
                                    self.user_uuid, self.session_id, name_input_tokens, name_output_tokens
                                )
                                # Emit token_update event so UI reflects updated session totals
                                updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
                                if updated_session:
                                    from trusted_data_agent.core.cost_manager import CostManager as _CM2
                                    _name_cost = _CM2().calculate_cost(
                                        provider=self.current_provider or "Unknown",
                                        model=self.current_model or "Unknown",
                                        input_tokens=name_input_tokens,
                                        output_tokens=name_output_tokens
                                    )
                                    yield self._format_sse_with_depth({
                                        "statement_input": name_input_tokens,
                                        "statement_output": name_output_tokens,
                                        "turn_input": self.turn_input_tokens,
                                        "turn_output": self.turn_output_tokens,
                                        "total_input": updated_session.get("input_tokens", 0),
                                        "total_output": updated_session.get("output_tokens", 0),
                                        "call_id": "session_name_generation",
                                        "cost_usd": _name_cost
                                    }, "token_update")
                                # Update turn token counts in workflow_history for reload
                                await session_manager.update_turn_token_counts(
                                    self.user_uuid, self.session_id, self.current_turn_number,
                                    self.turn_input_tokens, self.turn_output_tokens
                                )

                            if new_name != "New Chat":
                                try:
                                    await session_manager.update_session_name(self.user_uuid, self.session_id, new_name)
                                    app_logger.info(f"Session name updated to: '{new_name}'")
                                except Exception as e:
                                    app_logger.error(f"Failed to update session name: {e}")

            # Create dummy workflow_history entry for consistency
            # This ensures turn reload, analytics, and cost tracking work the same for all profile types
            profile_tag = self._get_current_profile_tag()

            # Update session-level profile_tags_used array (same as tool-enabled profiles)
            await session_manager.update_models_used(
                self.user_uuid,
                self.session_id,
                self.current_provider,
                self.current_model,
                profile_tag
            )
            app_logger.info(f"✅ Updated session {self.session_id} with llm_only profile_tag={profile_tag}")

            # Send SSE notification to update UI sidebar in real-time
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)
            if session_data:
                # Build dual_model_info from session metadata (for header display)
                dual_model_info = None
                if session_data.get("is_dual_model_active"):
                    dual_model_info = {
                        "strategicProvider": session_data.get("strategic_provider"),
                        "strategicModel": session_data.get("strategic_model"),
                        "tacticalProvider": session_data.get("tactical_provider"),
                        "tacticalModel": session_data.get("tactical_model")
                    }

                notification_payload = {
                    "session_id": self.session_id,
                    "models_used": session_data.get("models_used", []),
                    "profile_tags_used": session_data.get("profile_tags_used", []),
                    "last_updated": session_data.get("last_updated"),
                    "provider": self.current_provider,
                    "model": self.current_model,
                    "name": session_data.get("name", "Unnamed Session"),
                    "dual_model_info": dual_model_info
                }
                app_logger.info(f"🔔 [LLM-only] Sending session_model_update SSE: profile_tags={notification_payload['profile_tags_used']}, dual_model={dual_model_info is not None}")
                yield self._format_sse_with_depth({
                    "type": "session_model_update",
                    "payload": notification_payload
                }, event="notification")

            # Get session token totals (needed for plan reload display)
            session_input_tokens = session_data.get("input_tokens", 0) if session_data else 0
            session_output_tokens = session_data.get("output_tokens", 0) if session_data else 0

            # Calculate turn cost for persistence
            turn_cost = 0.0
            try:
                from trusted_data_agent.core.cost_manager import CostManager
                cost_manager = CostManager()
                turn_cost = cost_manager.calculate_cost(
                    provider=self.current_provider,
                    model=self.current_model,
                    input_tokens=self.turn_input_tokens,
                    output_tokens=self.turn_output_tokens
                )
                app_logger.debug(f"[llm_only] Turn {self.current_turn_number} cost: ${turn_cost:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate turn cost: {e}", exc_info=True)

            # Calculate session cost (cumulative up to and including this turn)
            session_cost_usd = 0.0
            try:
                previous_session_cost = self._calculate_session_cost_at_turn(session_data)
                session_cost_usd = previous_session_cost + turn_cost
                app_logger.debug(f"[llm_only] Session cost at turn {self.current_turn_number}: ${session_cost_usd:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate session cost: {e}", exc_info=True)

            turn_summary = {
                "turn": self.current_turn_number,
                "user_query": self.original_user_input,
                "final_summary_text": response_text,
                "status": "success",
                "is_session_primer": self.is_session_primer,  # Flag for RAG case filtering
                "execution_trace": [],  # No tool executions for llm_only
                "raw_llm_plan": None,  # No plan for llm_only
                "original_plan": None,  # No plan for llm_only
                "system_events": system_events,  # Session name generation and other system operations (UI replay only)
                "knowledge_events": llm_execution_events,  # Intermediate execution events for plan reload (matching rag_focused)
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": self.current_provider,
                "model": self.current_model,
                "profile_tag": profile_tag,
                "profile_type": "llm_only",  # Mark as llm_only for turn reload
                "task_id": self.task_id if hasattr(self, 'task_id') else None,
                "turn_input_tokens": self.turn_input_tokens,  # Cumulative turn total (includes all LLM calls like reranking)
                "turn_output_tokens": self.turn_output_tokens,  # Cumulative turn total
                "turn_cost": turn_cost,  # NEW - Cost at time of execution
                "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                "session_id": self.session_id,
                # Session totals at the time of this turn (for plan reload)
                "session_input_tokens": session_input_tokens,
                "session_output_tokens": session_output_tokens,
                "rag_source_collection_id": None,  # LLM-only doesn't use RAG
                "case_id": None,
                "knowledge_accessed": knowledge_accessed,  # Track knowledge collections accessed
                "knowledge_retrieval_event": {
                    "enabled": knowledge_enabled,
                    "retrieved": len(knowledge_accessed) > 0,
                    "document_count": len(knowledge_accessed)
                } if knowledge_enabled else None,
                "skills_applied": self.skill_result.to_applied_list() if self.skill_result and self.skill_result.has_content else []
            }

            await session_manager.update_last_turn_data(self.user_uuid, self.session_id, turn_summary)
            app_logger.debug(f"Saved llm_only turn data to workflow_history for turn {self.current_turn_number}")

            # --- PHASE 2: Emit execution_complete lifecycle event for llm_only ---
            try:
                # Calculate turn cost for completion card
                from trusted_data_agent.core.cost_manager import CostManager
                _cost_mgr = CostManager()
                _turn_cost = _cost_mgr.calculate_cost(
                    provider=self.current_provider or "Unknown",
                    model=self.current_model or "Unknown",
                    input_tokens=self.turn_input_tokens,
                    output_tokens=self.turn_output_tokens
                )
                complete_event = self._emit_lifecycle_event("execution_complete", {
                    "profile_type": "llm_only",
                    "profile_tag": profile_tag,
                    "total_input_tokens": self.turn_input_tokens,
                    "total_output_tokens": self.turn_output_tokens,
                    "knowledge_accessed": len(knowledge_accessed) > 0,
                    "cost_usd": _turn_cost,
                    "success": True
                })
                yield complete_event
                app_logger.info("✅ Emitted execution_complete event for llm_only profile")
            except Exception as e:
                # Silent failure - don't break execution
                app_logger.warning(f"Failed to emit execution_complete event: {e}")
            # --- PHASE 2 END ---

            app_logger.info("✅ LLM-only execution completed successfully")
            return
        # --- LLM-ONLY PROFILE: DIRECT EXECUTION PATH END ---

        # --- CONVERSATION WITH TOOLS: LANGCHAIN AGENT PATH ---
        # Routes here when llm_only profile has MCP tools OR active component tools.
        # Component tools are a platform feature available to all profile types.
        # Note: profile_config, use_mcp_tools, has_component_tools already computed at beginning of execute()
        is_conversation_with_tools = (profile_type == "llm_only" and (use_mcp_tools or has_component_tools))
        if is_conversation_with_tools:
            tool_reason = "MCP Tools" if use_mcp_tools else "Component Tools"
            app_logger.info(f"🔧 Conversation profile with {tool_reason} - LangChain agent mode")

            # Note: Lifecycle events (execution_start/execution_complete) are NOT emitted here.
            # The conversation_agent_start/conversation_agent_complete events from ConversationAgentExecutor
            # carry all necessary data (query, profile_type, profile_tag, turn_id, tokens, tools_used)
            # to render a single combined start/end card in the Live Status panel.

            async for event in self._execute_conversation_with_tools():
                yield event

            return
        # --- CONVERSATION WITH TOOLS END ---

        # --- RAG FOCUSED EXECUTION PATH ---
        is_rag_focused = self._is_rag_focused_profile()
        if is_rag_focused:
            app_logger.info("🔍 RAG-focused profile - mandatory knowledge retrieval")

            # Collect events for plan reload (similar to genie_events and conversation_agent_events)
            # Initialize BEFORE lifecycle emission so we can store the start event
            knowledge_events = []

            # --- PHASE 2: Emit execution_start lifecycle event for rag_focused ---
            try:
                profile_config = self._get_profile_config()
                knowledge_config = profile_config.get("knowledgeConfig", {})
                knowledge_collections = knowledge_config.get("collections", [])

                execution_start_payload = {
                    "profile_type": "rag_focused",
                    "profile_tag": self._get_current_profile_tag(),
                    "query": self.original_user_input,
                    "knowledge_collections": len(knowledge_collections)
                }
                start_event = self._emit_lifecycle_event("execution_start", execution_start_payload)
                yield start_event

                # Store lifecycle start event for reload
                knowledge_events.append({
                    "type": "execution_start",
                    "payload": execution_start_payload
                })

                app_logger.info("✅ Emitted execution_start event for rag_focused profile")
            except Exception as e:
                # Silent failure - don't break execution
                app_logger.warning(f"Failed to emit execution_start event: {e}")
            # --- PHASE 2 END ---

            # --- MANDATORY Knowledge Retrieval ---
            retrieval_start_time = time.time()

            profile_config = self._get_profile_config()
            knowledge_config = profile_config.get("knowledgeConfig", {})
            knowledge_collections = knowledge_config.get("collections", [])

            if not knowledge_collections:
                error_msg = "RAG focused profile has no knowledge collections configured."
                yield self._format_sse_with_depth({"step": "Finished", "error": error_msg}, "error")
                return

            # Check if RAG retriever is available
            if not self.rag_retriever:
                error_msg = "Knowledge retrieval is not available. RAG system may not be initialized."
                yield self._format_sse_with_depth({"step": "Finished", "error": error_msg, "error_type": "rag_not_available"}, "error")
                return

            # Retrieve knowledge (REQUIRED) - using three-tier configuration (global -> profile -> locks)
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            effective_config = config_manager.get_effective_knowledge_config(knowledge_config)
            max_docs = effective_config.get("maxDocs", APP_CONFIG.KNOWLEDGE_RAG_NUM_DOCS)
            min_relevance = effective_config.get("minRelevanceScore", APP_CONFIG.KNOWLEDGE_MIN_RELEVANCE_SCORE)
            max_tokens = effective_config.get("maxTokens", APP_CONFIG.KNOWLEDGE_MAX_TOKENS)
            max_chunks_per_doc = effective_config.get("maxChunksPerDocument", APP_CONFIG.KNOWLEDGE_MAX_CHUNKS_PER_DOC)
            freshness_weight = effective_config.get("freshnessWeight", APP_CONFIG.KNOWLEDGE_FRESHNESS_WEIGHT)
            freshness_decay_rate = effective_config.get("freshnessDecayRate", APP_CONFIG.KNOWLEDGE_FRESHNESS_DECAY_RATE)
            synthesis_prompt_override = effective_config.get("synthesisPromptOverride", "")

            app_logger.info(f"[RAG] Effective config: maxDocs={max_docs}, minRelevance={min_relevance}, "
                           f"maxTokens={max_tokens}, maxChunksPerDoc={max_chunks_per_doc}, "
                           f"freshnessWeight={freshness_weight}, freshnessDecay={freshness_decay_rate}, "
                           f"synthesisPrompt={'yes (' + str(len(synthesis_prompt_override)) + ' chars)' if synthesis_prompt_override else 'no'}")

            # Emit start event (fetch actual collection names from metadata)
            collection_names_for_start = []
            for coll_config in knowledge_collections:
                coll_id = coll_config.get("id")
                if coll_id and self.rag_retriever:
                    coll_meta = self.rag_retriever.get_collection_metadata(coll_id)
                    if coll_meta:
                        collection_names_for_start.append(coll_meta.get("name", coll_id))
                    else:
                        # Fallback: try to get name from collection DB table directly
                        try:
                            from trusted_data_agent.core.collection_db import get_collection_db
                            coll_db = get_collection_db()
                            coll_info = coll_db.get_collection_by_id(coll_id)
                            if coll_info and coll_info.get("name"):
                                collection_names_for_start.append(coll_info["name"])
                            else:
                                collection_names_for_start.append(coll_config.get("name", coll_id))
                        except Exception as e:
                            logger.warning(f"Failed to fetch collection name for {coll_id}: {e}")
                            collection_names_for_start.append(coll_config.get("name", coll_id))
                else:
                    collection_names_for_start.append(coll_config.get("name", coll_id or "Unknown"))

            start_event_payload = {
                "collections": collection_names_for_start,
                "max_docs": max_docs,
                "session_id": self.session_id
            }
            knowledge_events.append({"type": "knowledge_retrieval_start", "payload": start_event_payload})
            yield self._format_sse_with_depth({
                "type": "knowledge_retrieval_start",
                "payload": start_event_payload
            }, event="notification")

            from trusted_data_agent.agent.rag_access_context import RAGAccessContext
            rag_context = RAGAccessContext(user_id=self.user_uuid, retriever=self.rag_retriever)

            all_results = self.rag_retriever.retrieve_examples(
                query=self.original_user_input,
                k=max_docs * len(knowledge_collections),
                min_score=min_relevance,
                allowed_collection_ids=set([c["id"] for c in knowledge_collections]),
                rag_context=rag_context,
                repository_type="knowledge",  # Only knowledge, not planner
                max_chunks_per_doc=max_chunks_per_doc,
                freshness_weight=freshness_weight,
                freshness_decay_rate=freshness_decay_rate
            )

            app_logger.info(f"[RAG] Retrieved {len(all_results)} chunks from {len(knowledge_collections)} collection(s)")
            for idx, r in enumerate(all_results[:5]):
                sim = r.get('similarity_score', 0)
                adj = r.get('adjusted_score', sim)
                fresh = r.get('freshness_score', 'N/A')
                title = r.get('metadata', {}).get('title', 'unknown')[:50]
                doc_id = r.get('document_id', 'N/A')
                fresh_str = f" fresh={fresh:.3f}" if isinstance(fresh, (int, float)) else ""
                app_logger.info(f"[RAG]   #{idx+1}: adj={adj:.4f} sim={sim:.4f}{fresh_str} title={title} doc={doc_id}")

            if not all_results:
                # NO KNOWLEDGE FOUND - Treat as valid response, not error
                retrieval_duration_ms = int((time.time() - retrieval_start_time) * 1000)
                collection_names = set([c.get("name", "Unknown") for c in knowledge_collections])

                no_results_message = """<div class="no-knowledge-found">
    <p><strong>No relevant knowledge found</strong> for your query.</p>
    <p class="text-gray-400 text-sm mt-2">Try rephrasing your question or check your knowledge repositories.</p>
</div>"""
                no_results_text = "No relevant knowledge found. Try rephrasing or check your knowledge repositories."

                # Emit knowledge retrieval complete event (with 0 documents)
                retrieval_complete_payload = {
                    "collection_names": list(collection_names),
                    "document_count": 0,
                    "duration_ms": retrieval_duration_ms,
                    "session_id": self.session_id
                }
                knowledge_events.append({"type": "knowledge_retrieval_complete", "payload": retrieval_complete_payload})
                yield self._format_sse_with_depth({
                    "type": "knowledge_retrieval_complete",
                    "payload": retrieval_complete_payload
                }, event="notification")

                # Save to conversation history
                await session_manager.add_message_to_histories(
                    self.user_uuid, self.session_id, 'assistant',
                    content=no_results_text,
                    html_content=no_results_message,
                    is_session_primer=self.is_session_primer
                )

                # Update models_used for session tracking
                profile_tag = self._get_current_profile_tag()
                await session_manager.update_models_used(
                    self.user_uuid,
                    self.session_id,
                    self.current_provider,
                    self.current_model,
                    profile_tag
                )

                # Get session data for token totals
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                session_input_tokens = session_data.get("input_tokens", 0) if session_data else 0
                session_output_tokens = session_data.get("output_tokens", 0) if session_data else 0

                # System events (for session name generation on first turn)
                system_events = []

                # Generate session name for first turn
                if self.current_turn_number == 1:
                    session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                    if session_data and session_data.get("name") == "New Chat":
                        async for result in self._generate_and_emit_session_name():
                            if isinstance(result, str):
                                yield result
                            else:
                                new_name, name_input_tokens, name_output_tokens, name_events = result
                                system_events.extend(name_events)

                                # Add session name tokens to turn totals and session totals
                                if name_input_tokens > 0 or name_output_tokens > 0:
                                    self.turn_input_tokens += name_input_tokens
                                    self.turn_output_tokens += name_output_tokens
                                    await session_manager.update_token_count(
                                        self.user_uuid, self.session_id, name_input_tokens, name_output_tokens
                                    )
                                    # Emit token_update event so UI reflects updated session totals
                                    updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
                                    if updated_session:
                                        from trusted_data_agent.core.cost_manager import CostManager as _CM
                                        _name_cost = _CM().calculate_cost(
                                            provider=self.current_provider or "Unknown",
                                            model=self.current_model or "Unknown",
                                            input_tokens=name_input_tokens,
                                            output_tokens=name_output_tokens
                                        )
                                        yield self._format_sse_with_depth({
                                            "statement_input": name_input_tokens,
                                            "statement_output": name_output_tokens,
                                            "turn_input": self.turn_input_tokens,
                                            "turn_output": self.turn_output_tokens,
                                            "total_input": updated_session.get("input_tokens", 0),
                                            "total_output": updated_session.get("output_tokens", 0),
                                            "call_id": "session_name_generation",
                                            "cost_usd": _name_cost
                                        }, "token_update")
                                    # Update turn token counts in workflow_history for reload
                                    await session_manager.update_turn_token_counts(
                                        self.user_uuid, self.session_id, self.current_turn_number,
                                        self.turn_input_tokens, self.turn_output_tokens
                                    )

                                if new_name != "New Chat":
                                    try:
                                        await session_manager.update_session_name(self.user_uuid, self.session_id, new_name)
                                        yield self._format_sse_with_depth({
                                            "session_id": self.session_id,
                                            "newName": new_name
                                        }, "session_name_update")
                                    except Exception as name_e:
                                        app_logger.error(f"Failed to save session name: {name_e}")

                # Emit token_update event after session name generation (if any tokens were consumed)
                # This ensures the UI status window shows updated session totals
                if self.turn_input_tokens > 0 or self.turn_output_tokens > 0:
                    # Re-fetch session to get updated token counts after session name generation
                    session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                    if session_data:
                        yield self._format_sse_with_depth({
                            "statement_input": 0,  # No new statement tokens in "no results" path
                            "statement_output": 0,
                            "turn_input": self.turn_input_tokens,
                            "turn_output": self.turn_output_tokens,
                            "total_input": session_data.get("input_tokens", 0),
                            "total_output": session_data.get("output_tokens", 0),
                            "call_id": "rag_no_results"
                        }, "token_update")

                # Store execution_complete in knowledge_events for reload (BEFORE turn_summary)
                # No LLM synthesis for no-results case, so synthesis_duration_ms is 0
                # Calculate turn cost for completion card
                from trusted_data_agent.core.cost_manager import CostManager
                _cost_mgr = CostManager()
                _turn_cost = _cost_mgr.calculate_cost(
                    provider=self.current_provider or "Unknown",
                    model=self.current_model or "Unknown",
                    input_tokens=self.turn_input_tokens,
                    output_tokens=self.turn_output_tokens
                )
                execution_complete_payload = {
                    "profile_type": "rag_focused",
                    "profile_tag": profile_tag,
                    "collections_searched": len(collection_names),
                    "documents_retrieved": 0,
                    "no_knowledge_found": True,
                    "total_input_tokens": self.turn_input_tokens,
                    "total_output_tokens": self.turn_output_tokens,
                    "retrieval_duration_ms": retrieval_duration_ms,
                    "synthesis_duration_ms": 0,
                    "total_duration_ms": retrieval_duration_ms,  # Only retrieval, no synthesis
                    "cost_usd": _turn_cost,
                    "success": True
                }
                knowledge_events.append({
                    "type": "execution_complete",
                    "payload": execution_complete_payload
                })

                # Calculate session cost (cumulative up to and including this turn)
                session_cost_usd = 0.0
                try:
                    previous_session_cost = self._calculate_session_cost_at_turn(session_data)
                    session_cost_usd = previous_session_cost + _turn_cost
                    app_logger.debug(f"[rag_focused-no-results] Session cost at turn {self.current_turn_number}: ${session_cost_usd:.6f}")
                except Exception as e:
                    app_logger.warning(f"Failed to calculate session cost: {e}", exc_info=True)

                # Build turn summary for workflow_history
                turn_summary = {
                    "turn": self.current_turn_number,
                    "user_query": self.original_user_input,
                    "final_summary_text": no_results_text,
                    "status": "success",  # NOT "error"
                    "is_session_primer": self.is_session_primer,  # Flag for RAG case filtering
                    "no_knowledge_found": True,  # Flag for UI indication
                    "execution_trace": [],
                    "raw_llm_plan": None,
                    "original_plan": None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "provider": self.current_provider,
                    "model": self.current_model,
                    "profile_tag": profile_tag,
                    "profile_type": "rag_focused",
                    "task_id": self.task_id if hasattr(self, 'task_id') else None,
                    "turn_input_tokens": self.turn_input_tokens,
                    "turn_output_tokens": self.turn_output_tokens,
                    "turn_cost": _turn_cost,  # NEW - Cost at time of execution (already calculated above)
                    "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                    "session_id": self.session_id,
                    "session_input_tokens": session_input_tokens,
                    "session_output_tokens": session_output_tokens,
                    "knowledge_retrieval_event": {
                        "enabled": True,
                        "retrieved": False,
                        "document_count": 0,
                        "collections": list(collection_names),
                        "duration_ms": retrieval_duration_ms,
                        "summary": f"Searched {len(collection_names)} collection(s), no relevant documents found"
                    },
                    "knowledge_events": knowledge_events,
                    "system_events": system_events,
                    "skills_applied": self.skill_result.to_applied_list() if self.skill_result and self.skill_result.has_content else []
                }

                # Save turn data to workflow_history
                await session_manager.update_last_turn_data(self.user_uuid, self.session_id, turn_summary)
                app_logger.debug(f"Saved rag_focused (no results) turn data for turn {self.current_turn_number}")

                # Send session update notification
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                if session_data:
                    yield self._format_sse_with_depth({
                        "type": "session_model_update",
                        "payload": {
                            "session_id": self.session_id,
                            "models_used": session_data.get("models_used", []),
                            "profile_tags_used": session_data.get("profile_tags_used", []),
                            "last_updated": session_data.get("last_updated"),
                            "provider": self.current_provider,
                            "model": self.current_model,
                            "name": session_data.get("name", "Unnamed Session"),
                        }
                    }, event="notification")

                # Emit final_answer (NOT error) with turn_id for badge rendering
                yield self._format_sse_with_depth({
                    "step": "Finished",
                    "final_answer": no_results_message,
                    "final_answer_text": no_results_text,
                    "turn_id": self.current_turn_number,
                    "session_id": self.session_id,
                    "no_knowledge_found": True,
                    "is_session_primer": self.is_session_primer
                }, "final_answer")

                # Emit lifecycle event (already stored in knowledge_events above for reload)
                try:
                    complete_event = self._emit_lifecycle_event("execution_complete", execution_complete_payload)
                    yield complete_event
                except Exception as e:
                    app_logger.warning(f"Failed to emit execution_complete event: {e}")

                app_logger.info("✅ RAG-focused execution completed (no knowledge found)")
                return

            # Apply reranking if configured (reuse existing code from llm_only)
            reranked_results = all_results
            for coll_config in knowledge_collections:
                if coll_config.get("reranking", False):
                    coll_results = [r for r in all_results
                                  if r.get("metadata", {}).get("collection_id") == coll_config["id"]]
                    if coll_results and self.llm_handler:
                        # Get actual collection name from metadata
                        coll_id = coll_config.get("id")
                        coll_name = "Unknown"
                        if coll_id and self.rag_retriever:
                            coll_meta = self.rag_retriever.get_collection_metadata(coll_id)
                            if coll_meta:
                                coll_name = coll_meta.get("name", "Unknown")
                            else:
                                coll_name = coll_config.get("name", "Unknown")
                        else:
                            coll_name = coll_config.get("name", "Unknown")

                        # Emit reranking start event
                        rerank_start_payload = {
                            "collection": coll_name,
                            "document_count": len(coll_results),
                            "session_id": self.session_id
                        }
                        knowledge_events.append({"type": "knowledge_reranking_start", "payload": rerank_start_payload})
                        yield self._format_sse_with_depth({
                            "type": "knowledge_reranking_start",
                            "payload": rerank_start_payload
                        }, event="notification")

                        reranked = await self._rerank_knowledge_with_llm(
                            query=self.original_user_input,
                            documents=coll_results,
                            max_docs=max_docs
                        )

                        # Emit reranking complete event
                        rerank_complete_payload = {
                            "collection": coll_name,
                            "reranked_count": len(reranked),
                            "session_id": self.session_id
                        }
                        knowledge_events.append({"type": "knowledge_reranking_complete", "payload": rerank_complete_payload})
                        yield self._format_sse_with_depth({
                            "type": "knowledge_reranking_complete",
                            "payload": rerank_complete_payload
                        }, event="notification")

                        reranked_results = [r for r in reranked_results
                                          if r.get("metadata", {}).get("collection_id") != coll_config["id"]]
                        reranked_results.extend(reranked)

            # Limit total documents
            final_results = reranked_results[:max_docs]

            # Enrich documents with collection_name
            for doc in final_results:
                if not doc.get("collection_name"):
                    coll_id = doc.get("collection_id")
                    if coll_id and self.rag_retriever:
                        coll_meta = self.rag_retriever.get_collection_metadata(coll_id)
                        if coll_meta:
                            doc["collection_name"] = coll_meta.get("name", "Unknown")

            # Format knowledge context for LLM
            knowledge_context = self._format_knowledge_for_prompt(final_results, max_tokens)

            # Build detailed event for Live Status panel (matching llm_only format)
            knowledge_chunks = []
            collection_names = set()
            for doc in final_results:
                collection_name = doc.get("collection_name", "Unknown")
                collection_names.add(collection_name)
                doc_metadata = doc.get("metadata", {})

                # Try title first (user-friendly name), then filename
                source_name = doc_metadata.get("title") or doc_metadata.get("filename")

                # If no title or filename, check if this is an imported collection
                if not source_name:
                    if "(Imported)" in collection_name or doc_metadata.get("source") == "import":
                        source_name = "No Document Source (Imported)"
                    else:
                        source_name = "Unknown Source"

                knowledge_chunks.append({
                    "source": source_name,
                    "content": doc.get("content", ""),
                    "similarity_score": doc.get("similarity_score", 0),
                    "document_id": doc.get("document_id"),
                    "chunk_index": doc.get("chunk_index", 0)
                })

            # Calculate retrieval duration
            retrieval_duration_ms = int((time.time() - retrieval_start_time) * 1000)

            # Emit completion event for Live Status panel (replaces old single event)
            # Include chunks for live status window display
            event_details = {
                "summary": f"Retrieved {len(final_results)} relevant document(s) from {len(collection_names)} knowledge collection(s)",
                "collections": list(collection_names),
                "document_count": len(final_results),
                "duration_ms": retrieval_duration_ms,
                "chunks": knowledge_chunks  # Include full chunks for UI display
            }

            knowledge_events.append({"type": "knowledge_retrieval_complete", "payload": event_details})
            yield self._format_sse_with_depth({
                "type": "knowledge_retrieval_complete",
                "payload": event_details
            }, event="notification")

            # --- LLM Synthesis ---
            from trusted_data_agent.agent.prompt_loader import get_prompt_loader
            prompt_loader = get_prompt_loader()
            system_prompt = prompt_loader.get_prompt("RAG_FOCUSED_EXECUTION")

            # Use fallback if prompt not found, empty, or is a placeholder (decryption failed)
            if not system_prompt or "[ENCRYPTED CONTENT]" in system_prompt:
                system_prompt = "You are a knowledge base assistant. Answer using only the provided documents."
                app_logger.warning("RAG_FOCUSED_EXECUTION prompt not available (decryption failed or not found), using fallback")

            # Apply synthesis prompt override from profile/global settings (if configured)
            if synthesis_prompt_override and synthesis_prompt_override.strip():
                system_prompt = synthesis_prompt_override.strip()
                app_logger.info(f"[RAG] Using synthesis prompt override ({len(system_prompt)} chars)")

            # --- Inject component instructions ---
            from trusted_data_agent.components.manager import get_component_instructions_for_prompt
            comp_section = get_component_instructions_for_prompt(
                self.active_profile_id, self.user_uuid, session_data
            )
            system_prompt = system_prompt.replace('{component_instructions_section}', comp_section)

            # --- Inject skill content (pre-processing) ---
            if self.skill_result and self.skill_result.has_content:
                sp_block = self.skill_result.get_system_prompt_block()
                if sp_block:
                    system_prompt = f"{system_prompt}\n\n{sp_block}"

            # Load document context from uploaded files
            rag_doc_context = None
            if self.attachments:
                rag_doc_context, doc_trunc_events = load_document_context(self.user_uuid, self.session_id, self.attachments)
                for evt in doc_trunc_events:
                    event_data = {"step": "Context Optimization", "type": "context_optimization", "details": evt}
                    self._log_system_event(event_data)
                    yield self._format_sse_with_depth(event_data)

            user_message = await self._build_user_message_for_rag_synthesis(
                knowledge_context=knowledge_context,
                document_context=rag_doc_context
            )

            # Inject user_context skill content into user message
            if self.skill_result and self.skill_result.has_content:
                uc_block = self.skill_result.get_user_context_block()
                if uc_block:
                    user_message = f"{uc_block}\n\n{user_message}"

            # Emit "Calling LLM" event with call_id for token tracking
            call_id = str(uuid.uuid4())
            llm_start_time = time.time()

            yield self._format_sse_with_depth({
                "step": "Calling LLM for Knowledge Synthesis",
                "type": "system_message",
                "details": {
                    "summary": "Synthesizing answer from retrieved knowledge",
                    "call_id": call_id,
                    "document_count": len(final_results),
                    "collections": list(collection_names)
                }
            })

            # Set LLM busy indicator
            yield self._format_sse_with_depth({"target": "llm", "state": "busy"}, "status_indicator_update")

            # Check for active component tools — auto-upgrade synthesis to agent mode
            from trusted_data_agent.components.manager import get_component_langchain_tools as _get_rag_comp_tools
            rag_component_tools = _get_rag_comp_tools(self.active_profile_id, self.user_uuid, session_id=self.session_id)

            rag_component_payloads = []  # Component payloads extracted from agent result (if any)

            if rag_component_tools:
                # --- RAG + Component Tools: Agent-based synthesis ---
                # Use ConversationAgentExecutor for synthesis with component tools
                # (e.g., LLM can call TDA_Charting to visualize retrieved knowledge)
                app_logger.info(f"[RAG] Component tools active ({len(rag_component_tools)}) — agent-based synthesis")
                from trusted_data_agent.llm.langchain_adapter import create_langchain_llm
                from trusted_data_agent.agent.conversation_agent import ConversationAgentExecutor

                llm_config_id = profile_config.get("llmConfigurationId")
                rag_llm_instance = create_langchain_llm(llm_config_id, self.user_uuid, thinking_budget=self.thinking_budget)

                session_data_for_history = await session_manager.get_session(self.user_uuid, self.session_id)
                rag_conv_history = []
                if session_data_for_history:
                    chat_obj = session_data_for_history.get("chat_object", [])
                    rag_conv_history = [m for m in chat_obj[-10:] if m.get("content", "").strip() != self.original_user_input.strip()]

                rag_agent = ConversationAgentExecutor(
                    profile=profile_config,
                    user_uuid=self.user_uuid,
                    session_id=self.session_id,
                    llm_instance=rag_llm_instance,
                    mcp_tools=rag_component_tools,
                    async_event_handler=self.event_handler,
                    max_iterations=3,
                    conversation_history=rag_conv_history,
                    knowledge_context=knowledge_context,
                    document_context=rag_doc_context,
                    multimodal_content=self.multimodal_content,
                    turn_number=self.current_turn_number,
                    provider=self.current_provider if hasattr(self, 'current_provider') else None,
                    model=self.current_model if hasattr(self, 'current_model') else None,
                )

                agent_result = await rag_agent.execute(self.original_user_input)
                response_text = agent_result.get("response", "")
                input_tokens = agent_result.get("input_tokens", 0)
                output_tokens = agent_result.get("output_tokens", 0)

                # CRITICAL: ConversationAgentExecutor uses LangChain directly (not llm_handler)
                # so we must explicitly update turn counters and persist session token counts.
                # Without this, the token_update event reads stale session data (0/0).
                self.turn_input_tokens += input_tokens
                self.turn_output_tokens += output_tokens
                if input_tokens > 0 or output_tokens > 0:
                    await session_manager.update_token_count(
                        self.user_uuid, self.session_id,
                        input_tokens, output_tokens
                    )

                # Store agent events for plan reload
                for evt in rag_agent.collected_events:
                    knowledge_events.append(evt)

                # Extract component payloads for HTML generation (chart, code, etc.)
                rag_component_payloads = agent_result.get("component_payloads", [])
            else:
                # --- Standard RAG: Direct LLM synthesis (no tools) ---
                response_text, input_tokens, output_tokens = await self._call_llm_and_update_tokens(
                    prompt=user_message,
                    reason="RAG Focused Synthesis",
                    system_prompt_override=system_prompt,
                    multimodal_content=self.multimodal_content
                )

            # Calculate LLM call duration
            llm_duration_ms = int((time.time() - llm_start_time) * 1000)

            # Set LLM idle indicator
            yield self._format_sse_with_depth({"target": "llm", "state": "idle"}, "status_indicator_update")

            # Explicitly update session token counts and emit token_update event
            # This ensures the status window shows correct session totals during live execution
            # Note: _call_llm_and_update_tokens already calls update_token_count internally via handler.py,
            # but we need to ensure it completes and fetch updated session data before emitting the event
            # Calculate cost for RAG LLM synthesis call (before token_update so it's included)
            from trusted_data_agent.core.cost_manager import CostManager
            cost_manager = CostManager()
            call_cost = cost_manager.calculate_cost(
                provider=self.current_provider if hasattr(self, 'current_provider') else "Unknown",
                model=self.current_model if hasattr(self, 'current_model') else "Unknown",
                input_tokens=input_tokens,
                output_tokens=output_tokens
            )

            if input_tokens > 0 or output_tokens > 0:
                # Re-fetch session to ensure token counts are current
                # The handler already updated tokens, but we need the latest persisted values
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)

                if session_data:
                    yield self._format_sse_with_depth({
                        "statement_input": input_tokens,
                        "statement_output": output_tokens,
                        "turn_input": self.turn_input_tokens,
                        "turn_output": self.turn_output_tokens,
                        "total_input": session_data.get("input_tokens", 0),
                        "total_output": session_data.get("output_tokens", 0),
                        "call_id": call_id,
                        "cost_usd": call_cost
                    }, "token_update")

            # Emit RAG LLM step event for plan reload (similar to conversation_llm_step)
            rag_llm_step_payload = {
                "step_name": "Knowledge Synthesis",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": llm_duration_ms,
                "model": f"{self.current_provider}/{self.current_model}" if hasattr(self, 'current_provider') and hasattr(self, 'current_model') else "Unknown",
                "session_id": self.session_id,
                "cost_usd": call_cost  # NEW: Track cost for RAG synthesis
            }
            knowledge_events.append({"type": "rag_llm_step", "payload": rag_llm_step_payload})
            yield self._format_sse_with_depth({
                "type": "rag_llm_step",
                "payload": rag_llm_step_payload
            }, event="notification")

            # Emit tool execution result event for LLM synthesis
            # This shows the synthesis as a proper tool step with token tracking
            synthesis_result_data = {
                "status": "success",
                "metadata": {
                    "tool_name": "LLM_Synthesis",
                    "call_id": call_id,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "model": f"{self.current_provider}/{self.current_model}" if hasattr(self, 'current_provider') and hasattr(self, 'current_model') else "Unknown"
                },
                "results": [{
                    "response": response_text[:500] + "..." if len(response_text) > 500 else response_text,
                    "full_length": len(response_text)
                }]
            }
            yield self._format_sse_with_depth({
                "step": "LLM Synthesis Results",
                "details": synthesis_result_data,
                "tool_name": "LLM_Synthesis"
            }, "tool_result")

            # Store tool execution result for event reload
            knowledge_events.append({
                "type": "tool_result",
                "payload": {
                    "step": "LLM Synthesis Results",
                    "details": synthesis_result_data,
                    "tool_name": "LLM_Synthesis"
                }
            })

            # Calculate total knowledge search time (retrieval + synthesis)
            total_knowledge_search_time_ms = int((time.time() - retrieval_start_time) * 1000)

            # Emit Knowledge Search Complete summary event (similar to Tools Complete)
            knowledge_search_complete_payload = {
                "status": "complete",
                "collections_searched": len(collection_names),
                "collection_names": list(collection_names),
                "documents_retrieved": len(final_results),
                "total_time_ms": total_knowledge_search_time_ms,
                "retrieval_time_ms": retrieval_duration_ms,
                "synthesis_time_ms": llm_duration_ms,
                "synthesis_tokens_in": input_tokens,
                "synthesis_tokens_out": output_tokens,
                "session_id": self.session_id
            }
            # NOTE: Don't store knowledge_search_complete in knowledge_events - it's redundant with execution_complete
            # which already contains the same KPIs. Only emit for live streaming.
            yield self._format_sse_with_depth({
                "type": "knowledge_search_complete",
                "payload": knowledge_search_complete_payload
            }, event="notification")

            # --- Format Response with Sources ---
            formatter = OutputFormatter(
                llm_response_text=response_text,
                collected_data=self.structured_collected_data,
                rag_focused_sources=final_results  # NEW: Pass sources
            )
            final_html, tts_payload = formatter.render()

            # Append component rendering HTML (chart, code, audio, video, etc.)
            from trusted_data_agent.components.utils import generate_component_html
            final_html += generate_component_html(rag_component_payloads)

            # Emit final answer
            yield self._format_sse_with_depth({
                "step": "Finished",
                "final_answer": final_html,
                "final_answer_text": response_text,  # Clean text for parent genie coordinators
                "turn_id": self.current_turn_number,  # Include turn_id for frontend badge rendering
                "session_id": self.session_id,  # Include session_id for filtering when switching sessions
                "tts_payload": tts_payload,
                "source": self.source,
                "knowledge_sources": [{"collection_id": r.get("collection_id"),
                                       "similarity_score": r.get("similarity_score")}
                                      for r in final_results],
                "is_session_primer": self.is_session_primer
            }, "final_answer")

            # Save to session
            await session_manager.add_message_to_histories(
                self.user_uuid, self.session_id, 'assistant',
                content=response_text, html_content=final_html,
                is_session_primer=self.is_session_primer
            )

            # Create workflow_history entry for turn reload consistency
            profile_tag = self._get_current_profile_tag()

            # Update session-level profile_tags_used array (same as other profile types)
            await session_manager.update_models_used(
                self.user_uuid,
                self.session_id,
                self.current_provider,
                self.current_model,
                profile_tag
            )
            app_logger.info(f"✅ Updated session {self.session_id} with rag_focused profile_tag={profile_tag}")

            # Send SSE notification to update UI sidebar in real-time
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)
            if session_data:
                # Build dual_model_info from session metadata (for header display)
                dual_model_info = None
                if session_data.get("is_dual_model_active"):
                    dual_model_info = {
                        "strategicProvider": session_data.get("strategic_provider"),
                        "strategicModel": session_data.get("strategic_model"),
                        "tacticalProvider": session_data.get("tactical_provider"),
                        "tacticalModel": session_data.get("tactical_model")
                    }

                notification_payload = {
                    "session_id": self.session_id,
                    "models_used": session_data.get("models_used", []),
                    "profile_tags_used": session_data.get("profile_tags_used", []),
                    "last_updated": session_data.get("last_updated"),
                    "provider": self.current_provider,
                    "model": self.current_model,
                    "name": session_data.get("name", "Unnamed Session"),
                    "dual_model_info": dual_model_info
                }
                app_logger.info(f"🔔 [RAG Focused] Sending session_model_update SSE: profile_tags={notification_payload['profile_tags_used']}, dual_model={dual_model_info is not None}")
                yield self._format_sse_with_depth({
                    "type": "session_model_update",
                    "payload": notification_payload
                }, event="notification")

            # Track which knowledge collections were accessed
            knowledge_accessed = list(set([r.get("collection_id") for r in final_results if r.get("collection_id")]))

            # Note: retrieval_duration_ms already calculated earlier (line ~1991)

            # Get session data for session token totals (needed for plan reload display)
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)
            session_input_tokens = session_data.get("input_tokens", 0) if session_data else 0
            session_output_tokens = session_data.get("output_tokens", 0) if session_data else 0

            # Collect system events for plan reload (like session name generation)
            system_events = []

            # Calculate total duration (retrieval + synthesis)
            total_duration_ms = retrieval_duration_ms + llm_duration_ms

            # Store execution_complete in knowledge_events for reload (BEFORE turn_summary)
            # Calculate turn cost for completion card
            from trusted_data_agent.core.cost_manager import CostManager
            _cost_mgr = CostManager()
            _turn_cost = _cost_mgr.calculate_cost(
                provider=self.current_provider or "Unknown",
                model=self.current_model or "Unknown",
                input_tokens=self.turn_input_tokens,
                output_tokens=self.turn_output_tokens
            )
            execution_complete_payload = {
                "profile_type": "rag_focused",
                "profile_tag": profile_tag,
                "collections_searched": len(collection_names),
                "documents_retrieved": len(final_results),
                "total_input_tokens": self.turn_input_tokens,
                "total_output_tokens": self.turn_output_tokens,
                "retrieval_duration_ms": retrieval_duration_ms,
                "synthesis_duration_ms": llm_duration_ms,
                "total_duration_ms": total_duration_ms,
                "cost_usd": _turn_cost,
                "success": True
            }
            knowledge_events.append({
                "type": "execution_complete",
                "payload": execution_complete_payload
            })

            # Calculate session cost (cumulative up to and including this turn)
            session_cost_usd = 0.0
            try:
                previous_session_cost = self._calculate_session_cost_at_turn(session_data)
                session_cost_usd = previous_session_cost + _turn_cost
                app_logger.debug(f"[rag_focused] Session cost at turn {self.current_turn_number}: ${session_cost_usd:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate session cost: {e}", exc_info=True)

            turn_summary = {
                "turn": self.current_turn_number,
                "user_query": self.original_user_input,
                "final_summary_text": response_text,
                "status": "success",
                "is_session_primer": self.is_session_primer,  # Flag for RAG case filtering
                "execution_trace": [],  # No tool executions for rag_focused
                "raw_llm_plan": None,  # No plan for rag_focused
                "original_plan": None,  # No plan for rag_focused
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": self.current_provider,
                "model": self.current_model,
                "profile_tag": profile_tag,
                "profile_type": "rag_focused",  # Mark as rag_focused for turn reload
                "task_id": self.task_id if hasattr(self, 'task_id') else None,
                "turn_input_tokens": self.turn_input_tokens,  # Cumulative turn total (includes all LLM calls like reranking)
                "turn_output_tokens": self.turn_output_tokens,  # Cumulative turn total
                "turn_cost": _turn_cost,  # NEW - Cost at time of execution (already calculated above)
                "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                "session_id": self.session_id,
                # Session totals at the time of this turn (for plan reload)
                "session_input_tokens": session_input_tokens,
                "session_output_tokens": session_output_tokens,
                "rag_source_collection_id": knowledge_accessed[0] if knowledge_accessed else None,
                "case_id": None,
                "knowledge_accessed": knowledge_accessed,  # Track knowledge collections accessed
                "knowledge_events": knowledge_events,  # Store all events for plan reload (like genie_events)
                "knowledge_retrieval_event": {
                    "enabled": True,  # Always true for rag_focused
                    "retrieved": len(knowledge_accessed) > 0,
                    "document_count": len(final_results),
                    "collections": list(collection_names),  # Include collection names
                    "duration_ms": retrieval_duration_ms,  # Add duration for plan reload
                    "summary": f"Retrieved {len(final_results)} relevant document(s) from {len(collection_names)} knowledge collection(s)",
                    "chunks": knowledge_chunks  # Include full chunks for UI display
                },
                # UI-only: Full document chunks for plan reload display (not sent to LLM)
                "knowledge_chunks_ui": knowledge_chunks,
                "system_events": system_events,
                "skills_applied": self.skill_result.to_applied_list() if self.skill_result and self.skill_result.has_content else []
            }

            await session_manager.update_last_turn_data(self.user_uuid, self.session_id, turn_summary)
            app_logger.debug(f"Saved rag_focused turn data to workflow_history for turn {self.current_turn_number}")

            # --- PHASE 2: Emit execution_complete lifecycle event (already stored in knowledge_events) ---
            try:
                complete_event = self._emit_lifecycle_event("execution_complete", execution_complete_payload)
                yield complete_event
                app_logger.info("✅ Emitted execution_complete event for rag_focused profile")
            except Exception as e:
                # Silent failure - don't break execution
                app_logger.warning(f"Failed to emit execution_complete event: {e}")
            # --- PHASE 2 END ---

            # --- Session Name Generation (AFTER execution_complete) ---
            # Generate session name for first turn (using unified generator)
            if self.current_turn_number == 1:
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                if session_data and session_data.get("name") == "New Chat":
                    app_logger.info(f"First turn detected for session {self.session_id}. Attempting to generate name.")

                    async for result in self._generate_and_emit_session_name():
                        if isinstance(result, str):
                            # SSE event - yield to frontend
                            yield result
                        else:
                            # Final result tuple: (name, input_tokens, output_tokens, collected_events)
                            new_name, name_input_tokens, name_output_tokens, name_events = result
                            system_events.extend(name_events)

                            # Add session name tokens to turn totals and session totals
                            if name_input_tokens > 0 or name_output_tokens > 0:
                                self.turn_input_tokens += name_input_tokens
                                self.turn_output_tokens += name_output_tokens
                                await session_manager.update_token_count(
                                    self.user_uuid, self.session_id, name_input_tokens, name_output_tokens
                                )
                                # Emit token_update event so UI reflects updated session totals
                                updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
                                if updated_session:
                                    _name_cost = CostManager().calculate_cost(
                                        provider=self.current_provider or "Unknown",
                                        model=self.current_model or "Unknown",
                                        input_tokens=name_input_tokens,
                                        output_tokens=name_output_tokens
                                    )
                                    yield self._format_sse_with_depth({
                                        "statement_input": name_input_tokens,
                                        "statement_output": name_output_tokens,
                                        "turn_input": self.turn_input_tokens,
                                        "turn_output": self.turn_output_tokens,
                                        "total_input": updated_session.get("input_tokens", 0),
                                        "total_output": updated_session.get("output_tokens", 0),
                                        "call_id": "session_name_generation",
                                        "cost_usd": _name_cost
                                    }, "token_update")
                                # Update turn token counts in workflow_history for reload
                                # (turn_summary was saved before session name generation in rag_focused path)
                                await session_manager.update_turn_token_counts(
                                    self.user_uuid, self.session_id, self.current_turn_number,
                                    self.turn_input_tokens, self.turn_output_tokens
                                )

                            if new_name != "New Chat":
                                try:
                                    await session_manager.update_session_name(self.user_uuid, self.session_id, new_name)
                                    yield self._format_sse_with_depth({
                                        "session_id": self.session_id,
                                        "newName": new_name
                                    }, "session_name_update")
                                    app_logger.info(f"Successfully updated session {self.session_id} name to '{new_name}'.")
                                except Exception as name_e:
                                    app_logger.error(f"Failed to save or emit updated session name '{new_name}': {name_e}", exc_info=True)

                            # Update turn data with session name events for reload
                            # (turn_summary was saved before session name generation)
                            if name_events:
                                try:
                                    await session_manager.update_turn_system_events(
                                        self.user_uuid, self.session_id, self.current_turn_number, system_events
                                    )
                                    app_logger.debug(f"Updated turn {self.current_turn_number} with session name events for reload")
                                except Exception as e:
                                    app_logger.warning(f"Failed to update turn with session name events: {e}")
            # --- Session Name Generation END ---

            app_logger.info("✅ RAG-focused execution completed successfully")
            return
        # --- RAG FOCUSED EXECUTION PATH END ---

        # --- MODIFICATION START: Setup temporary profile override if requested ---
        temp_llm_instance = None
        temp_mcp_client = None
        
        # Debug log to verify profile_override_id is being passed
        if self.profile_override_id:
            app_logger.debug(f"Profile override detected: {self.profile_override_id}")
        else:
            app_logger.info(f"ℹ️  No profile override - using default profile configuration")
            # Set effective MCP server ID to the default (for RAG storage)
            self.effective_mcp_server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID

        if self.profile_override_id:
            try:
                from trusted_data_agent.core.config_manager import get_config_manager
                from langchain_mcp_adapters.client import MultiServerMCPClient
                import boto3

                config_manager = get_config_manager()
                profiles = config_manager.get_profiles(self.user_uuid)
                override_profile = next((p for p in profiles if p.get("id") == self.profile_override_id), None)
                
                if not override_profile:
                    app_logger.warning(f"Profile override ID {self.profile_override_id} not found. Using default profile.")
                else:
                    # Store original state BEFORE logging (to capture default profile info)
                    self.original_llm = APP_STATE.get('llm')
                    self.original_mcp_tools = APP_STATE.get('mcp_tools')
                    self.original_mcp_prompts = APP_STATE.get('mcp_prompts')
                    self.original_structured_tools = APP_STATE.get('structured_tools')
                    self.original_structured_prompts = APP_STATE.get('structured_prompts')
                    self.original_provider = get_user_provider(self.user_uuid)
                    self.original_model = get_user_model(self.user_uuid)
                    
                    # Save provider-specific details
                    if self.original_provider == "Friendli":
                        self.original_provider_details['friendli'] = getattr(APP_CONFIG, 'CURRENT_FRIENDLI_DETAILS', None)
                    elif self.original_provider == "Azure":
                        self.original_provider_details['azure'] = getattr(APP_CONFIG, 'CURRENT_AZURE_DEPLOYMENT_DETAILS', None)
                    elif self.original_provider == "Amazon":
                        self.original_provider_details['aws_region'] = getattr(APP_CONFIG, 'CURRENT_AWS_REGION', None)
                        self.original_provider_details['aws_model_provider'] = getattr(APP_CONFIG, 'CURRENT_MODEL_PROVIDER_IN_PROFILE', None)
                    original_provider = self.original_provider
                    original_model = self.original_model
                    
                    app_logger.info(f"Profile override: {original_provider}/{original_model} -> @{override_profile.get('tag', 'N/A')} ({override_profile.get('name', 'Unknown')})")
                    
                    # Get override profile's LLM configuration
                    override_llm_config_id = override_profile.get('llmConfigurationId')
                    if override_llm_config_id:
                        # CRITICAL: Pass user_uuid to get user's updated LLM configs (not bootstrap defaults)
                        llm_configs = config_manager.get_llm_configurations(self.user_uuid)
                        override_llm_config = next((cfg for cfg in llm_configs if cfg['id'] == override_llm_config_id), None)
                        
                        if override_llm_config:
                            provider = override_llm_config.get('provider')
                            model = override_llm_config.get('model')
                            credentials = override_llm_config.get('credentials', {})
                            
                            app_logger.debug(f"Creating temporary LLM instance: {provider}/{model} (config: {override_llm_config_id})")
                            
                            # Load stored credentials from encrypted database (authentication always enabled)
                            from trusted_data_agent.auth.models import User
                            from trusted_data_agent.auth.database import get_db_session
                            from trusted_data_agent.core.configuration_service import retrieve_credentials_for_provider
                            
                            try:
                                # Get user_id from database using user_uuid (not from request context)
                                with get_db_session() as session:
                                    user = session.query(User).filter_by(id=self.user_uuid).first()
                                    if user:
                                        stored_result = await retrieve_credentials_for_provider(user.id, provider)
                                        if stored_result.get("credentials"):
                                            credentials = {**stored_result["credentials"], **credentials}
                                        else:
                                            app_logger.warning(f"No stored credentials found for {provider} (status: {stored_result.get('status')})")
                                    else:
                                        app_logger.warning(f"User not found for uuid {self.user_uuid}, cannot load stored credentials")
                            except Exception as e:
                                app_logger.error(f"Error loading stored credentials: {e}", exc_info=True)
                            
                            # Create temporary LLM instance using shared factory
                            from trusted_data_agent.llm.client_factory import create_llm_client, get_provider_config_details
                            
                            try:
                                temp_llm_instance = await create_llm_client(provider, model, credentials)
                                
                                # Only update if LLM instance was created successfully
                                # Update APP_CONFIG and executor's cached values for this turn
                                set_user_provider(provider, self.user_uuid)
                                set_user_model(model, self.user_uuid)
                                self.current_provider = provider
                                self.current_model = model
                                
                                # Apply provider-specific configuration details
                                provider_details = get_provider_config_details(provider, model, credentials)
                                for key, value in provider_details.items():
                                    setattr(APP_CONFIG, key, value)
                                
                                APP_STATE['llm'] = temp_llm_instance
                                app_logger.debug(f"Override LLM instance created: {provider}/{model}")
                            except Exception as llm_error:
                                app_logger.error(f"❌ Failed to create LLM instance for profile override: {llm_error}")
                                app_logger.error(f"   Provider: {provider}, Model: {model}")
                                app_logger.error(f"   Credentials present: {bool(credentials)}")
                                app_logger.error(f"   Continuing with default profile")
                                raise  # Re-raise to trigger outer exception handler
                    
                    # Get override profile's MCP server configuration
                    override_mcp_server_id = override_profile.get('mcpServerId')
                    override_profile_type = override_profile.get("profile_type", "tool_enabled")

                    app_logger.debug(f"Override MCP setup: type={override_profile_type}, server={override_mcp_server_id}")

                    if override_profile_type == "llm_only":
                        # LLM-only profile: Skip MCP setup entirely
                        app_logger.info(f"🗨️ LLM-only profile - skipping MCP")
                    elif override_mcp_server_id:
                        # CRITICAL: Pass user_uuid to load user's config from database, not bootstrap template
                        mcp_servers = config_manager.get_mcp_servers(self.user_uuid)
                        override_mcp_server = next((srv for srv in mcp_servers if srv['id'] == override_mcp_server_id), None)

                        if override_mcp_server:
                            server_name = override_mcp_server.get('name')  # For logging only

                            # Check transport type
                            transport_config = override_mcp_server.get('transport', {})
                            transport_type = transport_config.get('type', 'http')  # Default to HTTP for backwards compat

                            app_logger.debug(f"Creating temporary MCP client: {server_name} ({transport_type})")

                            if transport_type == 'stdio':
                                # STDIO transport: use command/args from transport config
                                command = transport_config.get('command')
                                args = transport_config.get('args', [])
                                env = transport_config.get('env', {})

                                # CRITICAL: Use server ID as key, not name
                                # CRITICAL: Must include "transport" key for langchain_mcp_adapters
                                temp_server_configs = {
                                    override_mcp_server_id: {
                                        "transport": "stdio",
                                        "command": command,
                                        "args": args,
                                        "env": env
                                    }
                                }
                                temp_mcp_client = MultiServerMCPClient(temp_server_configs)
                            else:
                                # HTTP transport (original code path)
                                host = override_mcp_server.get('host')
                                port = override_mcp_server.get('port')
                                path = override_mcp_server.get('path')

                                mcp_server_url = f"http://{host}:{port}{path}"
                                # CRITICAL: Use server ID as key, not name
                                temp_server_configs = {override_mcp_server_id: {"url": mcp_server_url, "transport": "streamable_http"}}
                                temp_mcp_client = MultiServerMCPClient(temp_server_configs)

                            # CRITICAL: Track the override MCP server ID for RAG case storage
                            self.effective_mcp_server_id = override_mcp_server_id

                            # Load and process tools AND prompts using the same method as configuration_service
                            from langchain_mcp_adapters.tools import load_mcp_tools
                            from trusted_data_agent.mcp_adapter.adapter import CLIENT_SIDE_TOOLS
                            loaded_override_prompts = []
                            async with temp_mcp_client.session(override_mcp_server_id) as session:
                                all_processed_tools = await load_mcp_tools(session)
                                # Also load prompts from the override MCP server
                                try:
                                    list_prompts_result = await session.list_prompts()
                                    if hasattr(list_prompts_result, 'prompts'):
                                        loaded_override_prompts = list_prompts_result.prompts
                                except Exception as e:
                                    app_logger.warning(f"   Failed to load prompts from override MCP server: {e}")

                            # CRITICAL FIX: Add CLIENT_SIDE_TOOLS to all_processed_tools
                            # load_mcp_tools only loads server tools, but CLIENT_SIDE_TOOLS (TDA_FinalReport, etc.)
                            # are core system tools that must always be available for FASTPATH optimization
                            class SimpleTool:
                                def __init__(self, **kwargs):
                                    self.__dict__.update(kwargs)

                            for tool_def in CLIENT_SIDE_TOOLS:
                                all_processed_tools.append(SimpleTool(**tool_def))

                            app_logger.debug(f"Loaded {len(all_processed_tools)} tools (MCP + {len(CLIENT_SIDE_TOOLS)} client-side)")

                            # Get enabled tool and prompt names for this profile
                            # CRITICAL: Must pass user_uuid to load user-specific profile config (not bootstrap template)
                            enabled_tool_names = set(config_manager.get_profile_enabled_tools(self.profile_override_id, self.user_uuid))
                            enabled_prompt_names = set(config_manager.get_profile_enabled_prompts(self.profile_override_id, self.user_uuid))

                            # CRITICAL FIX: Handle wildcard "*" in enabled_tool_names
                            # If profile has tools: ["*"], expand to include ALL tool names from MCP server
                            # The wildcard means "all tools" - ignore disabled flags in classification_results
                            if "*" in enabled_tool_names:
                                # Expand wildcard to all available tool names (including TDA_ tools)
                                enabled_tool_names = {tool.name for tool in all_processed_tools}
                                app_logger.info(f"   Wildcard '*' expanded to {len(enabled_tool_names)} tools from MCP server")

                            # Same for prompts
                            if "*" in enabled_prompt_names:
                                if loaded_override_prompts:
                                    enabled_prompt_names = {p.name for p in loaded_override_prompts}
                                elif self.original_mcp_prompts:
                                    enabled_prompt_names = set(self.original_mcp_prompts.keys())
                                app_logger.info(f"   Wildcard '*' expanded to {len(enabled_prompt_names)} prompts")

                            # Filter to only enabled tools (prompts handled separately via original structure)
                            # CRITICAL FIX: Always include TDA client-side tools (reporting, synthesis) regardless of profile filtering
                            # These are core system tools, not MCP server tools, and must always be available for FASTPATH optimization
                            TDA_CORE_TOOLS = {"TDA_FinalReport", "TDA_ComplexPromptReport", "TDA_ContextReport", "TDA_LLMTask", "TDA_LLMFilter", "TDA_CurrentDate", "TDA_DateRange"}
                            filtered_tools = [tool for tool in all_processed_tools if tool.name in enabled_tool_names or tool.name in TDA_CORE_TOOLS]

                            # Convert to dictionary with tool names as keys (matching normal structure)
                            filtered_tools_dict = {tool.name: tool for tool in filtered_tools}

                            # Build mcp_prompts from override MCP server's loaded prompts (not from original)
                            # The original mcp_prompts may be empty if the default profile didn't load MCP
                            if loaded_override_prompts:
                                all_override_prompts_dict = {p.name: p for p in loaded_override_prompts}
                                filtered_prompts_dict = {name: prompt for name, prompt in all_override_prompts_dict.items()
                                                        if name in enabled_prompt_names}
                            else:
                                # Fallback to original if MCP prompt loading failed
                                filtered_prompts_dict = {name: prompt for name, prompt in (self.original_mcp_prompts or {}).items()
                                                        if name in enabled_prompt_names}

                            # CRITICAL FIX: Build structured_tools from scratch for the override MCP server
                            # We can't filter original_structured_tools because it's from a DIFFERENT MCP server!
                            # The override profile uses "time" MCP server, not the default "Teradata MCP" server
                            filtered_structured_tools = {}

                            # Get classification results from override profile to determine categories
                            classification_results = override_profile.get("classification_results", {})
                            classified_tools = classification_results.get("tools", {})

                            if classified_tools:
                                # Use classification categories from profile
                                for category, tools_list in classified_tools.items():
                                    filtered_category_tools = []
                                    for tool_info in tools_list:
                                        tool_name = tool_info.get("name")
                                        # Include if tool is in our enabled set AND was successfully loaded from MCP
                                        if tool_name in enabled_tool_names and tool_name in filtered_tools_dict:
                                            filtered_category_tools.append({
                                                "name": tool_name,
                                                "description": tool_info.get("description", ""),
                                                "arguments": tool_info.get("arguments", []),
                                                "disabled": False  # Always enable since it's in enabled_tool_names
                                            })
                                    if filtered_category_tools:
                                        filtered_structured_tools[category] = filtered_category_tools
                            else:
                                # Fallback: create a single "All Tools" category
                                all_tools_category = []
                                for tool in filtered_tools:
                                    all_tools_category.append({
                                        "name": tool.name,
                                        "description": tool.description or "",
                                        "arguments": [],
                                        "disabled": False
                                    })
                                if all_tools_category:
                                    filtered_structured_tools["All Tools"] = all_tools_category

                            # CRITICAL FIX: Inject TDA_* client-side tools into structured_tools.
                            # These tools are in filtered_tools_dict (protected by TDA_CORE_TOOLS)
                            # but NOT in classification_results (they're not MCP server tools).
                            # Without this, TDA_* tools appear deactivated in the resource panel
                            # and invisible to the planner during profile overrides.
                            from trusted_data_agent.mcp_adapter.adapter import CLIENT_SIDE_TOOLS
                            system_tools_category = []
                            for tool_def in CLIENT_SIDE_TOOLS:
                                tool_name_cs = tool_def["name"]
                                if tool_name_cs in filtered_tools_dict:
                                    processed_args = []
                                    for arg_name, arg_details in tool_def.get("args", {}).items():
                                        if isinstance(arg_details, dict):
                                            processed_args.append({
                                                "name": arg_name,
                                                "type": arg_details.get("type", "any"),
                                                "description": arg_details.get("description", "No description."),
                                                "required": arg_details.get("required", False)
                                            })
                                    system_tools_category.append({
                                        "name": tool_name_cs,
                                        "description": tool_def.get("description", ""),
                                        "arguments": processed_args,
                                        "disabled": False
                                    })
                            if system_tools_category:
                                filtered_structured_tools["System Tools"] = system_tools_category

                            app_logger.info(f"   Built structured_tools from override MCP server: {len(filtered_structured_tools)} categories")

                            # Rebuild structured_prompts from override MCP server (not from original)
                            # CRITICAL FIX: Prioritize freshly loaded prompts over potentially stale classification
                            # Classification results may be incomplete or outdated, causing prompt lookup failures
                            filtered_structured_prompts = {}
                            classified_prompts = classification_results.get("prompts", {})

                            if loaded_override_prompts:
                                # FIXED: Include ALL prompts (enabled and disabled) so they can be executed from resource panel
                                # Deactivated prompts should still be executable via resource panel, just not used in regular conversation
                                from trusted_data_agent.mcp_adapter.adapter import _extract_prompt_type_from_description
                                all_prompts_category = []
                                for prompt_obj in loaded_override_prompts:
                                    # Include ALL prompts, mark as disabled if not in enabled list
                                    is_disabled = prompt_obj.name not in enabled_prompt_names
                                    cleaned_desc, prompt_type = _extract_prompt_type_from_description(prompt_obj.description)
                                    processed_args = []
                                    if hasattr(prompt_obj, 'arguments') and prompt_obj.arguments:
                                        for arg in prompt_obj.arguments:
                                            arg_dict = arg.model_dump()
                                            processed_args.append(arg_dict)
                                    all_prompts_category.append({
                                        "name": prompt_obj.name,
                                        "description": cleaned_desc or "No description available.",
                                        "arguments": processed_args,
                                        "disabled": is_disabled,
                                        "prompt_type": prompt_type
                                    })
                                if all_prompts_category:
                                    filtered_structured_prompts["All Prompts"] = all_prompts_category
                            elif classified_prompts:
                                # Fallback: use classification categories from profile if MCP loading failed
                                # Include ALL prompts, mark disabled flag appropriately
                                for category, prompts_list in classified_prompts.items():
                                    category_prompts = []
                                    for prompt_info in prompts_list:
                                        prompt_copy = dict(prompt_info)
                                        prompt_copy['disabled'] = prompt_info.get('name') not in enabled_prompt_names
                                        category_prompts.append(prompt_copy)
                                    if category_prompts:
                                        filtered_structured_prompts[category] = category_prompts
                            else:
                                # Last resort: use original prompts (mark disabled flag appropriately)
                                for category, prompts_list in (self.original_structured_prompts or {}).items():
                                    category_prompts = []
                                    for prompt_info in prompts_list:
                                        prompt_copy = dict(prompt_info)
                                        prompt_copy['disabled'] = prompt_info.get('name') not in enabled_prompt_names
                                        category_prompts.append(prompt_copy)
                                    if category_prompts:
                                        filtered_structured_prompts[category] = category_prompts
                            
                            # CRITICAL FIX: Update current_server_id_by_user for tool execution
                            # The mcp_adapter uses get_user_mcp_server_id() which reads this dict
                            # Save original for restoration
                            current_server_id_by_user = APP_STATE.setdefault("current_server_id_by_user", {})
                            self.original_server_id = current_server_id_by_user.get(self.user_uuid)
                            current_server_id_by_user[self.user_uuid] = override_mcp_server_id

                            APP_STATE['mcp_client'] = temp_mcp_client
                            APP_STATE['mcp_tools'] = filtered_tools_dict
                            APP_STATE['mcp_prompts'] = filtered_prompts_dict
                            APP_STATE['structured_tools'] = filtered_structured_tools
                            APP_STATE['structured_prompts'] = filtered_structured_prompts

                            # CRITICAL FIX: Rebuild tools_context and prompts_context after filtering
                            # The planner uses these context strings to show the LLM available tools/prompts
                            # Without this rebuild, the LLM sees the OLD/DEFAULT tools, not the override profile's tools
                            tools_context, prompts_context = rebuild_tools_and_prompts_context()
                            APP_STATE['tools_context'] = tools_context
                            APP_STATE['prompts_context'] = prompts_context

                            app_logger.info(f"Profile override applied: {len(filtered_tools_dict)} tools, {len(filtered_prompts_dict)} prompts")
                        else:
                            app_logger.warning(f"❌ MCP server {override_mcp_server_id} not found in config!")
                            app_logger.warning(f"   Profile override will continue with LLM only (no tools)")
                    elif not override_mcp_server_id:
                        app_logger.info(f"ℹ️  Profile has no MCP server configured - LLM only mode")

            except Exception as e:
                app_logger.error(f"Failed to apply profile override: {e}", exc_info=True)

                # CRITICAL: Restore original LLM instance before continuing
                # If profile override LLM creation failed, APP_STATE['llm'] may be None
                # Restore it to the original LLM instance so execution can continue
                if self.original_llm is not None:
                    APP_STATE['llm'] = self.original_llm
                    app_logger.info(f"Restored original LLM after profile override failure")
                else:
                    app_logger.error(f"❌ Cannot restore LLM - original LLM was None (default profile may not be configured)")

                # CRITICAL: Restore original provider/model before they get saved to session
                # The override attempt may have changed self.current_provider and self.current_model
                # but since it failed, we need to restore them to the original values
                if self.original_provider and self.original_model:
                    app_logger.info(f"🔄 Restoring provider/model from {self.current_provider}/{self.current_model} to {self.original_provider}/{self.original_model}")
                    self.current_provider = self.original_provider
                    self.current_model = self.original_model
                    set_user_provider(self.original_provider, self.user_uuid)
                    set_user_model(self.original_model, self.user_uuid)
                
                # Send warning banner notification to user via SSE
                from trusted_data_agent.core.config_manager import get_config_manager
                config_manager = get_config_manager()
                override_profile = None
                if self.profile_override_id:
                    profiles = config_manager.get_profiles(self.user_uuid)
                    override_profile = next((p for p in profiles if p.get("id") == self.profile_override_id), None)
                
                # Get default profile tag for notification
                default_profile_tag = self._get_active_profile_tag()
                
                # Clear profile_override_id NOW so subsequent calls use default profile
                app_logger.info(f"🔄 Clearing profile_override_id to use default profile tag: {default_profile_tag}")
                self.profile_override_id = None
                
                if override_profile:
                    # Send notification as SSE event to show banner in header
                    notification_data = {
                        "type": "profile_override_failed",
                        "payload": {
                            "override_profile_name": override_profile.get('name', 'Unknown'),
                            "override_profile_tag": override_profile.get('tag', 'N/A'),
                            "default_profile_tag": default_profile_tag,
                            "error_message": str(e)
                        }
                    }
                    app_logger.debug(f"Sending profile_override_failed notification")
                    yield self._format_sse_with_depth(notification_data, event="notification")
                
                # Continue with default profile if override fails
                # Note: Do NOT call update_models_used here - it will be called below with the restored default values
        # --- MODIFICATION END ---

        # Update session with correct provider/model/profile_tag at the start of execution
        # This ensures the session data is correct before any LLM calls
        profile_tag = self._get_current_profile_tag()
        await session_manager.update_models_used(self.user_uuid, self.session_id, self.current_provider, self.current_model, profile_tag)
        
        # Send immediate SSE notification so UI updates in real-time
        session_data = await session_manager.get_session(self.user_uuid, self.session_id)
        if session_data:
            # Include dual-model info if active
            dual_model_info = None
            if session_data.get("is_dual_model_active"):
                dual_model_info = {
                    "strategicProvider": session_data.get("strategic_provider"),
                    "strategicModel": session_data.get("strategic_model"),
                    "tacticalProvider": session_data.get("tactical_provider"),
                    "tacticalModel": session_data.get("tactical_model")
                }

            notification_payload = {
                "session_id": self.session_id,
                "models_used": session_data.get("models_used", []),
                "profile_tags_used": session_data.get("profile_tags_used", []),
                "last_updated": session_data.get("last_updated"),
                "provider": self.current_provider,
                "model": self.current_model,
                "name": session_data.get("name", "Unnamed Session"),
                "dual_model_info": dual_model_info
            }
            app_logger.debug(f"Sending session_model_update: {notification_payload['provider']}/{notification_payload['model']}")
            yield self._format_sse_with_depth({
                "type": "session_model_update",
                "payload": notification_payload
            }, event="notification")
        else:
            app_logger.warning(f"Could not send session_model_update - session_data is None for {self.session_id}")

        # Check for cancellation before starting execution
        self._check_cancellation()

        # --- PHASE 2: Emit execution_start lifecycle event for tool_enabled ---
        if not is_llm_only and not is_rag_focused:
            # Initialize event collection array (similar to knowledge_events for RAG)
            # Events are: 1) Yielded as SSE for live UI updates, 2) Collected for session persistence, 3) Replayed during historical turn reload
            self.tool_enabled_events = []

            try:
                start_event_payload = {
                    "profile_type": "tool_enabled",
                    "profile_tag": profile_tag,
                    "query": self.original_user_input,
                    "has_context": bool(self.previous_turn_data),
                    "is_replay": bool(self.plan_to_execute)
                }

                start_event = self._emit_lifecycle_event("execution_start", start_event_payload)
                yield start_event

                # Collect event for persistence (matches pattern from RAG/Genie profiles)
                self.tool_enabled_events.append({
                    "type": "execution_start",
                    "payload": start_event_payload,
                    "metadata": {"execution_depth": self.execution_depth}
                })

                app_logger.info("✅ Emitted execution_start event for tool_enabled profile")
            except Exception as e:
                # Silent failure - don't break execution
                app_logger.warning(f"Failed to emit execution_start event: {e}")
        # --- PHASE 2 END ---

        # Track execution start time for duration calculation (tool_enabled profiles)
        if not is_llm_only and not is_rag_focused:
            self.tool_enabled_start_time = time.time()

        # --- Canvas bidirectional context: Prepend for tool_enabled planning ---
        canvas_ctx = self._format_canvas_context()
        if canvas_ctx:
            self.original_user_input = f"{canvas_ctx}\n\n{self.original_user_input}"
            app_logger.info(f"Prepended canvas context to user input for tool_enabled planning")

        # --- Document upload: Prepend document context for tool_enabled planning ---
        # By this point, llm_only, conversation_with_tools, and rag_focused have all returned.
        # Augment original_user_input so the Planner sees document context in strategic planning.
        if self.document_context:
            self.original_user_input = f"[User has uploaded documents]\n{self.document_context}\n\n[User's question]\n{self.original_user_input}"
            app_logger.info(f"Prepended document context ({len(self.document_context):,} chars) to user input for tool_enabled planning")

        try:
            # --- MODIFICATION START: Handle Replay ---
            if self.plan_to_execute:
                app_logger.info(f"Starting replay execution for user {self.user_uuid}, session {self.session_id}.")
                self.meta_plan = copy.deepcopy(self.plan_to_execute) # Use the provided plan
                self.state = self.AgentState.EXECUTING # Skip planning
                # Inject a status event indicating replay
                replay_type_text = "Optimized" if "optimized" in str(self.is_replay).lower() else "Original" # Basic type check
                # Find the turn ID where this plan originally came from
                original_turn_id = "..." # Default if not found
                if session_data and isinstance(session_data.get("last_turn_data", {}).get("workflow_history"), list):
                    for idx, turn in enumerate(session_data["last_turn_data"]["workflow_history"]):
                        if turn.get("original_plan") == self.plan_to_execute:
                            original_turn_id = str(idx + 1)
                            break

                event_data = {
                    "step": f"🔄 Replaying {replay_type_text} Plan (from Turn {original_turn_id})",
                    "type": "system_message",
                    "details": f"Re-executing {'optimized' if replay_type_text == 'Optimized' else 'original'} plan..."
                }
                self._log_system_event(event_data)
                yield self._format_sse_with_depth(event_data)
            # --- MODIFICATION END ---
            else:
                if self.is_delegated_task:
                    async for event in self._run_delegated_prompt():
                        yield event
                    # _run_delegated_prompt() plans + executes via _run_plan() which
                    # sets state=SUMMARIZING, but the normal summarization phase at
                    # the bottom of run() is unreachable due to the early return.
                    # Call _handle_summarization() explicitly so the sub-executor
                    # emits execution_complete (and honours is_synthesis_from_history).
                    if self.state == self.AgentState.SUMMARIZING:
                        async for event in self._handle_summarization(final_answer_override):
                            yield event
                    return # Exit early for delegated tasks

                # --- Planning Phase ---
                if self.state == self.AgentState.PLANNING:
                    # Check for cancellation before starting planning
                    self._check_cancellation()

                    # --- MODIFICATION START: Pass RAG retriever instance to Planner ---
                    # Create a wrapped event handler that captures RAG collection info and knowledge retrieval
                    async def rag_aware_event_handler(data, event_name):
                        if event_name == "rag_retrieval" and data and 'collection_id' in data.get('full_case_data', {}).get('metadata', {}):
                            # Store the collection ID and case ID from the retrieved RAG case
                            self.rag_source_collection_id = data['full_case_data']['metadata']['collection_id']
                            self.rag_source_case_id = data.get('case_id')  # Capture case_id for feedback tracking
                            app_logger.debug(f"RAG example retrieved from collection {self.rag_source_collection_id}, case_id: {self.rag_source_case_id}")
                        
                        # --- PHASE 2: Track knowledge repository access ---
                        elif event_name == "knowledge_retrieval":
                            collections = data.get("collections", [])
                            document_count = data.get("document_count", 0)
                            
                            # Store knowledge access info for turn summary
                            for collection_name in collections:
                                self.knowledge_accessed.append({
                                    "collection_name": collection_name,
                                    "document_count": document_count,
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
                            
                            # Store the full event for replay when plan is reloaded
                            self.knowledge_retrieval_event = data
                            app_logger.info(f"Tracked knowledge retrieval: {len(collections)} collection(s), {document_count} document(s)")
                            app_logger.debug(f"Stored knowledge_retrieval_event with {len(data.get('chunks', []))} chunks")
                        # --- PHASE 2 END ---
                        
                        # Pass through to the original event handler
                        if self.event_handler:
                            await self.event_handler(data, event_name)
                    
                    planner = Planner(self, rag_retriever_instance=self.rag_retriever, event_handler=rag_aware_event_handler)
                    # --- MODIFICATION END ---
                    should_replan = False
                    planning_is_disabled_history = self.disabled_history

                    replan_attempt = 0
                    max_replans = 1
                    while True:
                        replan_context = None
                        is_replan = replan_attempt > 0

                        if is_replan:
                            prompts_in_plan = {p['executable_prompt'] for p in (self.meta_plan or []) if 'executable_prompt' in p}
                            granted_prompts_in_plan = {p for p in prompts_in_plan if p in APP_CONFIG.GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING}
                            non_granted_prompts_to_deconstruct = {p for p in prompts_in_plan if p not in granted_prompts_in_plan}

                            context_parts = ["\n--- CONTEXT FOR RE-PLANNING ---"]
                            deconstruction_instruction = (
                                "Your previous plan was inefficient because it contained high-level prompts that must be broken down. "
                                "You MUST create a new, more detailed plan that achieves the same overall goal."
                            )
                            context_parts.append(deconstruction_instruction)
                            if granted_prompts_in_plan:
                                preservation_rule = (
                                    f"\n**CRITICAL PRESERVATION RULE:** The following prompts are explicitly granted and you **MUST** "
                                    f"include them as phases in the new plan: `{list(granted_prompts_in_plan)}`. "
                                    "You should rebuild the other parts of the plan around these required steps.\n"
                                )
                                context_parts.append(preservation_rule)
                            if non_granted_prompts_to_deconstruct:
                                deconstruction_directive = (
                                    "\n**CRITICAL REPLANNING DIRECTIVE:** You **MUST** replicate the logical goal of the following discarded prompt(s) "
                                    "using **only basic tools**. To help you, here are their original goals:"
                                )
                                context_parts.append(deconstruction_directive)
                                for prompt_name in non_granted_prompts_to_deconstruct:
                                    prompt_info = self._get_prompt_info(prompt_name)
                                    if prompt_info:
                                        context_parts.append(f"- The goal of the discarded prompt `{prompt_name}` was: \"{prompt_info.get('description', 'No description.')}\"")
                            replan_context = "\n".join(context_parts)

                        async for event in planner.generate_and_refine_plan(
                            force_disable_history=planning_is_disabled_history,
                            replan_context=replan_context
                        ):
                            # --- MODIFICATION START: Capture and log planner corrections ---
                            # Check if the yielded event is a system correction and log it to the history.
                            if "system_correction" in event.lower() or '"type": "workaround"' in event.lower():
                                try:
                                    # The event is a JSON string, parse it.
                                    event_data = json.loads(event.replace("data: ", "").strip())
                                    self.turn_action_history.append({"action": "system_correction", "result": event_data})
                                except json.JSONDecodeError:
                                    app_logger.warning(f"Could not parse planner event for history logging: {event}")
                            # --- MODIFICATION END ---
                            yield event

                        # --- MODIFICATION START: Store original plan AFTER refinement ---
                        # Store the plan that was actually generated and refined before any execution begins
                        self.original_plan_for_history = copy.deepcopy(self.meta_plan)
                        app_logger.debug("Stored original plan (post-refinement) for history.")
                        # --- MODIFICATION END ---

                        # --- MODIFICATION START: Inject knowledge context into workflow_state for hybrid plans ---
                        # This allows TDA_FinalReport to access both gathered data AND knowledge context
                        if hasattr(planner, '_last_knowledge_context') and planner._last_knowledge_context:
                            self.workflow_state['_knowledge_context'] = planner._last_knowledge_context
                            app_logger.info("Injected knowledge context into workflow_state for final report access.")
                        # --- MODIFICATION END ---

                        plan_has_prompt = self.meta_plan and any('executable_prompt' in phase for phase in self.meta_plan)
                        replan_triggered = False
                        if plan_has_prompt:
                            prompts_in_plan = {phase['executable_prompt'] for phase in self.meta_plan if 'executable_prompt' in phase}
                            non_granted_prompts = [p for p in prompts_in_plan if p not in APP_CONFIG.GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING]
                            has_other_significant_tool = any('executable_prompt' not in phase and phase.get('relevant_tools') != ['TDA_LLMTask'] for phase in self.meta_plan)
                            is_single_phase_prompt = len(self.meta_plan) == 1
                            if has_other_significant_tool and not is_single_phase_prompt and non_granted_prompts:
                                replan_triggered = True

                        if self.execution_depth == 0 and replan_triggered and replan_attempt < max_replans:
                            replan_attempt += 1
                            event_data = {
                                "step": "Re-planning for Efficiency", "type": "plan_optimization",
                                "details": {
                                    "summary": "Initial plan uses a sub-prompt alongside other tools. Agent is re-planning to create a more efficient, tool-only workflow.",
                                    "original_plan": copy.deepcopy(self.meta_plan) # Log the plan *before* this replan
                                }
                            }
                            self._log_system_event(event_data)
                            yield self._format_sse_with_depth(event_data)
                            continue # Loop back to replan
                        break # Exit planning loop

                    # Handle single prompt plan expansion (if applicable)
                    self.is_single_prompt_plan = (self.meta_plan and len(self.meta_plan) == 1 and 'executable_prompt' in self.meta_plan[0] and not self.is_delegated_task)

                    if self.is_single_prompt_plan:
                        async for event in self._handle_single_prompt_plan(planner):
                            yield event
                        # --- MODIFICATION START: Re-capture plan if single prompt expansion happened ---
                        # If the plan was expanded from a single prompt, update the stored original plan
                        self.original_plan_for_history = copy.deepcopy(self.meta_plan)
                        app_logger.debug("Re-stored plan after single-prompt expansion for history.")
                        # --- MODIFICATION END ---


                    # Check for conversational plan
                    if self.is_conversational_plan:
                        app_logger.info("Detected a conversational plan. Bypassing execution.")
                        self.state = self.AgentState.SUMMARIZING
                    else:
                        self.state = self.AgentState.EXECUTING

            # --- Execution Phase ---
            try:
                if self.state == self.AgentState.EXECUTING:
                    async for event in self._run_plan(): yield event
            except DefinitiveToolError as e:
                app_logger.error(f"Execution halted by definitive tool error: {e.friendly_message}")
                event_data = {"step": "Unrecoverable Error", "details": e.friendly_message, "type": "error"}
                self._log_system_event(event_data, "tool_result")
                yield self._format_sse_with_depth(event_data, "tool_result")
                final_answer_override = f"I could not complete the request. Reason: {e.friendly_message}"
                self.state = self.AgentState.SUMMARIZING # Go to summarization even on error

            # --- Summarization Phase ---
            if self.state == self.AgentState.SUMMARIZING:
                async for event in self._handle_summarization(final_answer_override):
                    yield event

        except asyncio.CancelledError:
            # Handle cancellation specifically
            app_logger.info(f"PlanExecutor execution cancelled for user {self.user_uuid}, session {self.session_id}.")
            self.state = self.AgentState.ERROR  # Mark as error to prevent normal history update
            # Yield a specific event to the frontend - include turn_id for badge creation
            event_data = {
                "step": "Execution Stopped",
                "details": "The process was stopped by the user.",
                "type": "cancelled",
                "turn_id": self.current_turn_number,
                "session_id": self.session_id
            }
            self._log_system_event(event_data, "cancelled")
            yield self._format_sse_with_depth(event_data, "cancelled")

            # --- PHASE 2: Emit execution_cancelled lifecycle event (all profiles) ---
            try:
                profile_type = self._detect_profile_type()
                # Emit for all profile types (tool_enabled, llm_only, rag_focused)
                cancelled_event = self._emit_lifecycle_event("execution_cancelled", {
                    "profile_type": profile_type,
                    "profile_tag": self._get_current_profile_tag(),
                    "phases_completed": len([a for a in self.turn_action_history if isinstance(a.get("action"), dict) and a["action"].get("tool_name") != "TDA_SystemLog"]),
                    "cancellation_stage": self.state.name,
                    "partial_input_tokens": self.turn_input_tokens,
                    "partial_output_tokens": self.turn_output_tokens
                })
                yield cancelled_event
                app_logger.info(f"✅ Emitted execution_cancelled event for {profile_type} profile")
            except Exception as e:
                # Silent failure - don't break cancellation flow
                app_logger.warning(f"Failed to emit execution_cancelled event: {e}")
            # --- PHASE 2 END ---

            # Save partial turn data before re-raising
            await self._save_partial_turn_data(
                status="cancelled",
                error_message="Execution stopped by user",
                error_details="The user cancelled the execution before completion."
            )

            # Re-raise so the caller (routes.py) knows it was cancelled
            raise

        except Exception as e:
            # Handle other general exceptions
            root_exception = unwrap_exception(e)
            app_logger.error(f"Error in state {self.state.name} for user {self.user_uuid}, session {self.session_id}: {root_exception}", exc_info=True)
            self.state = self.AgentState.ERROR
            event_data = {
                "error": "Execution stopped due to an unrecoverable error.",
                "details": str(root_exception),
                "step": "Unrecoverable Error",
                "type": "error",
                "turn_id": self.current_turn_number,
                "session_id": self.session_id
            }
            self._log_system_event(event_data, "error")
            yield self._format_sse_with_depth(event_data, "error")

            # --- PHASE 2: Emit execution_error lifecycle event (all profiles) ---
            try:
                profile_type = self._detect_profile_type()
                # Emit for all profile types (tool_enabled, llm_only, rag_focused)
                error_type = self._classify_error(root_exception)
                error_event = self._emit_lifecycle_event("execution_error", {
                    "profile_type": profile_type,
                    "profile_tag": self._get_current_profile_tag(),
                    "error_message": str(root_exception),
                    "error_type": error_type,
                    "error_stage": self.state.name,
                    "phases_completed": len([a for a in self.turn_action_history if isinstance(a.get("action"), dict) and a["action"].get("tool_name") != "TDA_SystemLog"]),
                    "partial_input_tokens": self.turn_input_tokens,
                    "partial_output_tokens": self.turn_output_tokens,
                    "success": False
                })
                yield error_event
                app_logger.info(f"✅ Emitted execution_error event for {profile_type} profile (error_type: {error_type})")
            except Exception as e:
                # Silent failure - don't break error handling flow
                app_logger.warning(f"Failed to emit execution_error event: {e}")
            # --- PHASE 2 END ---

            # Save partial turn data for error case
            await self._save_partial_turn_data(
                status="error",
                error_message="Execution stopped due to an unrecoverable error.",
                error_details=str(root_exception)
            )

        finally:
            # --- MODIFICATION START: Restore original MCP/LLM state if profile was overridden ---
            if self.profile_override_id:
                try:
                    from trusted_data_agent.core.config_manager import get_config_manager
                    config_manager = get_config_manager()
                    default_profile_id = config_manager.get_default_profile_id(self.user_uuid)
                    default_profile_name = "Default Profile"
                    if default_profile_id:
                        profiles = config_manager.get_profiles(self.user_uuid)
                        default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
                        if default_profile:
                            default_profile_name = f"{default_profile.get('name')} (Tag: @{default_profile.get('tag', 'N/A')})"
                    
                    app_logger.info(f"Reverting to default profile: {default_profile_name}")
                    
                    if self.original_llm is not None:
                        APP_STATE['llm'] = self.original_llm
                        if self.original_provider:
                            set_user_provider(self.original_provider, self.user_uuid)
                        if self.original_model:
                            set_user_model(self.original_model, self.user_uuid)
                        
                        # Restore provider-specific details
                        if self.original_provider == "Friendli" and 'friendli' in self.original_provider_details:
                            set_user_friendli_details(self.original_provider_details['friendli'], self.user_uuid)
                        elif self.original_provider == "Azure" and 'azure' in self.original_provider_details:
                            set_user_azure_deployment_details(self.original_provider_details['azure'], self.user_uuid)
                        elif self.original_provider == "Amazon":
                            if 'aws_region' in self.original_provider_details:
                                set_user_aws_region(self.original_provider_details['aws_region'], self.user_uuid)
                            if 'aws_model_provider' in self.original_provider_details:
                                set_user_model_provider_in_profile(self.original_provider_details['aws_model_provider'], self.user_uuid)
                        
                        app_logger.debug(f"Restored LLM: {self.original_provider}/{self.original_model}")
                    
                    if self.original_mcp_tools is not None:
                        APP_STATE['mcp_tools'] = self.original_mcp_tools
                    
                    if self.original_mcp_prompts is not None:
                        APP_STATE['mcp_prompts'] = self.original_mcp_prompts
                    
                    if self.original_structured_tools is not None:
                        APP_STATE['structured_tools'] = self.original_structured_tools
                    
                    if self.original_structured_prompts is not None:
                        APP_STATE['structured_prompts'] = self.original_structured_prompts

                    # CRITICAL FIX: Restore original current_server_id_by_user
                    # This ensures tool execution uses the correct MCP server after override
                    if self.original_server_id is not None:
                        current_server_id_by_user = APP_STATE.setdefault("current_server_id_by_user", {})
                        current_server_id_by_user[self.user_uuid] = self.original_server_id

                    # CRITICAL FIX: Rebuild tools_context and prompts_context after restoring original state
                    # This ensures subsequent queries in the same session see the correct default profile tools
                    if self.original_mcp_tools is not None or self.original_structured_tools is not None:
                        tools_context, prompts_context = rebuild_tools_and_prompts_context()
                        APP_STATE['tools_context'] = tools_context
                        APP_STATE['prompts_context'] = prompts_context

                    # Close temporary MCP client if created
                    if temp_mcp_client:
                        try:
                            # Note: MultiServerMCPClient may not have explicit close method
                            # But context managers handle cleanup automatically
                            pass
                        except Exception as cleanup_error:
                            app_logger.warning(f"⚠️  Error closing temporary MCP client: {cleanup_error}")
                    
                    app_logger.info(f"Reverted to default profile")
                    
                except Exception as restore_error:
                    app_logger.error(f"❌ Error restoring original state after profile override: {restore_error}", exc_info=True)
            # --- MODIFICATION END ---
            
            # --- Cleanup Phase (Always runs) ---
            # --- MODIFICATION START: Only top-level executor (depth 0) saves history ---
            # Update history only if the execution wasn't cancelled, errored,
            # AND this is the top-level executor instance.
            if self.state != self.AgentState.ERROR and self.execution_depth == 0:
            # --- MODIFICATION END ---
                # --- MODIFICATION START: Include model/provider and use self.current_turn_number ---
                # Get profile tag from default profile (or override if active)
                profile_tag = self._get_current_profile_tag()

                # Get session data for session token totals (needed for plan reload display)
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                session_input_tokens = session_data.get("input_tokens", 0) if session_data else 0
                session_output_tokens = session_data.get("output_tokens", 0) if session_data else 0

                # Collect system events for plan reload (like session name generation)
                # CRITICAL: Use the collected events from session name generation (stored in self.session_name_events)
                # These events were collected during the actual generation process and include accurate token counts
                system_events = self.session_name_events if hasattr(self, 'session_name_events') else []

                if system_events:
                    app_logger.debug(f"Using {len(system_events)} collected session name events for workflow history")

                # Pre-build execution_complete event for persistence BEFORE constructing turn_summary.
                # The actual SSE emission happens later (after final_answer yield), but we need
                # the event data stored in tool_enabled_events now so it's included in the saved turn.
                if hasattr(self, 'tool_enabled_events') and hasattr(self, 'tool_enabled_start_time'):
                    duration_ms = int((time.time() - self.tool_enabled_start_time) * 1000)
                    # Calculate cost for persisted execution_complete (used by historical reload)
                    _pre_cost = 0
                    try:
                        from trusted_data_agent.core.cost_manager import CostManager
                        _pre_cost = CostManager().calculate_cost(
                            provider=self.current_provider or "Unknown",
                            model=self.current_model or "Unknown",
                            input_tokens=self.turn_input_tokens,
                            output_tokens=self.turn_output_tokens
                        )
                    except Exception:
                        pass
                    self.tool_enabled_events.append({
                        "type": "execution_complete",
                        "payload": {
                            "profile_type": "tool_enabled",
                            "profile_tag": self._get_current_profile_tag(),
                            "phases_executed": len([a for a in self.turn_action_history if isinstance(a.get("action"), dict) and a["action"].get("tool_name") != "TDA_SystemLog"]),
                            "total_input_tokens": self.turn_input_tokens,
                            "total_output_tokens": self.turn_output_tokens,
                            "duration_ms": duration_ms,
                            "cost_usd": _pre_cost,
                            "success": True
                        },
                        "metadata": {"execution_depth": self.execution_depth}
                    })

                # Calculate turn cost for persistence (fixes historical reload $0 cost bug)
                turn_cost = 0  # Default
                try:
                    from trusted_data_agent.core.cost_manager import CostManager
                    cost_manager = CostManager()
                    turn_cost = cost_manager.calculate_cost(
                        provider=self.current_provider,
                        model=self.current_model,
                        input_tokens=self.turn_input_tokens,
                        output_tokens=self.turn_output_tokens
                    )
                    app_logger.debug(f"Calculated turn cost for persistence: ${turn_cost:.6f}")
                except Exception as e:
                    app_logger.warning(f"Failed to calculate turn cost for persistence: {e}")

                # Calculate session cost (cumulative up to and including this turn)
                session_cost_usd = 0.0
                try:
                    previous_session_cost = self._calculate_session_cost_at_turn(session_data)
                    session_cost_usd = previous_session_cost + turn_cost
                    app_logger.debug(f"[tool_enabled] Session cost at turn {self.current_turn_number}: ${session_cost_usd:.6f}")
                except Exception as e:
                    app_logger.warning(f"Failed to calculate session cost: {e}", exc_info=True)

                turn_summary = {
                    "turn": self.current_turn_number, # Use the authoritative instance variable
                    "user_query": self.original_user_input, # Store the original query
                    "is_session_primer": self.is_session_primer,  # Flag for RAG case filtering
                    "raw_llm_plan": self.raw_llm_plan,  # LLM's raw output before preprocessing/rewrites
                    "original_plan": self.original_plan_for_history, # Plan after all rewrite passes (what was actually executed)
                    "execution_trace": self.turn_action_history,
                    "final_summary": self.final_summary_text,
                    "system_events": system_events,  # Session name generation and other system operations (UI replay only)
                    "tool_enabled_events": getattr(self, 'tool_enabled_events', []),  # Lifecycle events for tool_enabled profiles (execution_start, execution_complete)
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "provider": self.current_provider, # Add snapshot of provider (for backwards compatibility)
                    "model": self.current_model,       # Add snapshot of model (for backwards compatibility)
                    "profile_tag": profile_tag,        # Add snapshot of profile tag
                    "task_id": self.task_id,            # Add the task_id
                    "turn_input_tokens": self.turn_input_tokens,
                    "turn_output_tokens": self.turn_output_tokens,
                    "turn_cost": turn_cost,  # Add turn cost for historical reload (fixes $0 cost bug)
                    "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                    # Session totals at the time of this turn (for plan reload)
                    "session_input_tokens": session_input_tokens,
                    "session_output_tokens": session_output_tokens,
                    # --- MODIFICATION START: Add session_id and mcp_server_id for RAG worker ---
                    "session_id": self.session_id,
                    "mcp_server_id": self.effective_mcp_server_id or APP_CONFIG.CURRENT_MCP_SERVER_ID,  # Use effective MCP ID (override aware)
                    "user_uuid": self.user_uuid,  # Add user UUID for RAG access control
                    # --- MODIFICATION END ---
                    # --- MODIFICATION START: Add RAG source collection ID and case ID ---
                    "rag_source_collection_id": self.rag_source_collection_id,
                    "case_id": self.rag_source_case_id,  # Add case_id for feedback tracking
                    # --- MODIFICATION END ---
                    # --- PHASE 2: Add knowledge repository tracking ---
                    "knowledge_accessed": self.knowledge_accessed,  # List of knowledge collections used
                    "knowledge_retrieval_event": self.knowledge_retrieval_event,  # Full event for replay on reload
                    # --- PHASE 2 END ---
                    # Status fields for consistency with partial turn data
                    "status": "success",
                    "is_partial": False,
                    # Duration tracking for tool_enabled profile (calculated from start time)
                    "duration_ms": int((time.time() - self.tool_enabled_start_time) * 1000) if hasattr(self, 'tool_enabled_start_time') else 0,
                    "skills_applied": self.skill_result.to_applied_list() if self.skill_result and self.skill_result.has_content else []
                }
                # --- MODIFICATION END ---
                await session_manager.update_last_turn_data(self.user_uuid, self.session_id, turn_summary)
                app_logger.debug(f"Saved last turn data to session {self.session_id} for user {self.user_uuid}")

                # --- MODIFICATION START: Add "Producer" logic to send turn to RAG worker ---
                # Skip RAG processing for temporary API sessions (e.g., prompt execution, question generation)
                # Check the source parameter to determine if this is a temporary/utility execution
                skip_rag_for_temp_sessions = self.source in [
                    "prompt_library_raw",
                    "question_generator"
                ]

                if APP_CONFIG.RAG_ENABLED and APP_STATE.get('rag_processing_queue') and self.rag_retriever and not skip_rag_for_temp_sessions:
                    try:
                        app_logger.debug(f"Adding turn {self.current_turn_number} to RAG processing queue.")
                        # Add user_uuid to turn_summary for session updates
                        turn_summary['user_uuid'] = self.user_uuid
                        # Put the summary in the queue. This is non-blocking and instantaneous.
                        await APP_STATE['rag_processing_queue'].put(turn_summary)
                    except Exception as e:
                        # Log error if queue.put fails, but don't crash the executor
                        app_logger.error(f"Failed to add turn summary to RAG processing queue: {e}", exc_info=True)
                elif skip_rag_for_temp_sessions:
                    app_logger.debug(f"Skipping RAG processing for temporary execution with source: {self.source}")
                # --- MODIFICATION END ---

            else:
                 # --- MODIFICATION START: Update log message to include depth ---
                 app_logger.info(
                     f"Skipping history save for user {self.user_uuid}, session {self.session_id}. "
                     f"Final state: {self.state.name}, Execution Depth: {self.execution_depth}"
                 )
                 # --- MODIFICATION END ---
    # --- END of run method ---

    async def _save_partial_turn_data(self, status: str, error_message: str = None, error_details: str = None):
        """
        Saves partial turn data for cancelled/error turns.

        This ensures that even failed turns have retrievable data for the UI,
        including accumulated tokens and any execution trace up to the failure point.

        Args:
            status: One of "cancelled", "error"
            error_message: Human-readable error message (optional)
            error_details: Technical error details (optional)
        """
        # Only save for top-level executor
        if self.execution_depth != 0:
            app_logger.debug(f"Skipping partial turn save for nested executor (depth={self.execution_depth})")
            return

        try:
            profile_tag = self._get_current_profile_tag()

            # Get session data for session token totals (needed for plan reload display)
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)
            session_input_tokens = session_data.get("input_tokens", 0) if session_data else 0
            session_output_tokens = session_data.get("output_tokens", 0) if session_data else 0

            # Calculate turn cost for partial/error turn
            turn_cost = 0.0
            try:
                from trusted_data_agent.core.cost_manager import CostManager
                cost_manager = CostManager()
                turn_cost = cost_manager.calculate_cost(
                    provider=self.current_provider,
                    model=self.current_model,
                    input_tokens=self.turn_input_tokens,
                    output_tokens=self.turn_output_tokens
                )
                app_logger.debug(f"[tool_enabled-partial] Turn {self.current_turn_number} cost: ${turn_cost:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate turn cost for partial turn: {e}")

            # Calculate session cost (cumulative up to and including this turn)
            session_cost_usd = 0.0
            try:
                previous_session_cost = self._calculate_session_cost_at_turn(session_data)
                session_cost_usd = previous_session_cost + turn_cost
                app_logger.debug(f"[tool_enabled-partial] Session cost at turn {self.current_turn_number}: ${session_cost_usd:.6f}")
            except Exception as e:
                app_logger.warning(f"Failed to calculate session cost for partial turn: {e}")

            turn_summary = {
                "turn": self.current_turn_number,
                "user_query": self.original_user_input,
                "is_session_primer": self.is_session_primer,  # Flag for RAG case filtering
                "raw_llm_plan": self.raw_llm_plan,  # LLM's raw output (None if error before planning)
                "original_plan": self.original_plan_for_history,  # May be None if error before planning
                "execution_trace": self.turn_action_history,  # Partial trace up to failure
                "final_summary": None,  # No final summary for failed turns
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": self.current_provider,
                "model": self.current_model,
                "profile_tag": profile_tag,
                "task_id": self.task_id,
                "turn_input_tokens": self.turn_input_tokens,  # Accumulated tokens up to failure
                "turn_output_tokens": self.turn_output_tokens,
                "turn_cost": turn_cost,  # NEW - Cost at time of error/cancellation
                "session_cost_usd": session_cost_usd,  # NEW - Cumulative cost snapshot
                # Session totals at the time of this turn (for plan reload)
                "session_input_tokens": session_input_tokens,
                "session_output_tokens": session_output_tokens,
                "session_id": self.session_id,
                "mcp_server_id": self.effective_mcp_server_id or APP_CONFIG.CURRENT_MCP_SERVER_ID,
                "user_uuid": self.user_uuid,
                "rag_source_collection_id": getattr(self, 'rag_source_collection_id', None),
                "case_id": getattr(self, 'rag_source_case_id', None),
                "knowledge_accessed": getattr(self, 'knowledge_accessed', []),
                "knowledge_retrieval_event": getattr(self, 'knowledge_retrieval_event', None),
                "tool_enabled_events": getattr(self, 'tool_enabled_events', []),  # Partial lifecycle events for tool_enabled profiles
                # Status fields for partial data
                "status": status,  # "cancelled" or "error"
                "error_message": error_message,
                "error_details": error_details,
                "is_partial": True,  # Flag to indicate incomplete execution
                "skills_applied": self.skill_result.to_applied_list() if self.skill_result and self.skill_result.has_content else []
            }

            await session_manager.update_last_turn_data(self.user_uuid, self.session_id, turn_summary)
            app_logger.info(f"Saved partial turn data (status={status}) for turn {self.current_turn_number}")

            # Save the cancelled/error message to conversation history so it appears on session reload
            status_tag = "CANCELLED" if status == "cancelled" else "ERROR"
            assistant_message = f'<span class="{status}-tag">{status_tag}</span> {error_message or "Execution did not complete."}'
            await session_manager.add_message_to_histories(
                self.user_uuid,
                self.session_id,
                role='assistant',
                content=error_message or "Execution did not complete.",  # Plain text for LLM
                html_content=assistant_message,  # HTML with tag for UI
                profile_tag=profile_tag
            )
            app_logger.info(f"Saved {status} message to conversation history for turn {self.current_turn_number}")

            # NOTE: Do NOT add to RAG processing queue for failed turns
            # Failed turns should not be used as champion cases

        except Exception as e:
            app_logger.error(f"Failed to save partial turn data: {e}", exc_info=True)
            # Don't re-raise - this is best-effort cleanup

    async def _handle_single_prompt_plan(self, planner: Planner):
        """Orchestrates the logic for expanding a single-prompt plan."""
        single_phase = self.meta_plan[0]
        prompt_name = single_phase.get('executable_prompt')
        prompt_args = single_phase.get('arguments', {})

        # TDA_ContextReport is a client-side tool, not an MCP prompt.
        # If LLM put it in executable_prompt, convert to relevant_tools and exit.
        # This allows the normal tool execution path to handle it (e.g., for knowledge queries).
        if prompt_name == 'TDA_ContextReport':
            app_logger.info(f"PLAN CORRECTION: '{prompt_name}' is a tool, not a prompt. Converting to tool execution.")
            single_phase['relevant_tools'] = [prompt_name]
            if 'executable_prompt' in single_phase:
                del single_phase['executable_prompt']
            self.is_single_prompt_plan = False
            return  # Exit - plan will be executed as a tool call

        event_data = {
            "step": "System Correction", "type": "workaround",
            "details": f"Single Prompt('{prompt_name}') identified. Expanding plan in-process to improve efficiency."
        }
        self._log_system_event(event_data)
        yield self._format_sse_with_depth(event_data)

        prompt_info = self._get_prompt_info(prompt_name)
        if prompt_info:
            required_args = {arg['name'] for arg in prompt_info.get('arguments', []) if arg.get('required')}
            missing_args = required_args - set(prompt_args.keys())

            if missing_args:
                event_data = {
                    "step": "System Correction", "type": "workaround",
                    "details": f"Prompt '{prompt_name}' is missing required arguments: {missing_args}. Attempting to extract from user query."
                }
                self._log_system_event(event_data)
                yield self._format_sse_with_depth(event_data)

                enrichment_prompt = (
                    f"You are an expert argument extractor. From the user's query, extract the values for the following missing arguments: {list(missing_args)}. "
                    f"User Query: \"{self.original_user_input}\"\n"
                    "Respond with only a single, valid JSON object mapping the argument names to their extracted values."
                )
                reason = f"Extracting missing arguments for prompt '{prompt_name}'"

                call_id = str(uuid.uuid4())
                event_data = {
                    "step": "Calling LLM for Argument Enrichment",
                    "type": "system_message",
                    "details": {"summary": reason, "call_id": call_id}
                }
                self._log_system_event(event_data)
                yield self._format_sse_with_depth(event_data)
                yield self._format_sse_with_depth({"target": "llm", "state": "busy"}, "status_indicator_update")

                response_text, input_tokens, output_tokens = await self._call_llm_and_update_tokens(
                    prompt=enrichment_prompt, reason=reason,
                    system_prompt_override="You are a JSON-only responding assistant.",
                    raise_on_error=True,
                    source=self.source
                )

                # Log post-LLM system_message with tokens + cost for historical replay
                enrichment_log_event = {
                    "step": "Calling LLM for Argument Enrichment",
                    "type": "system_message",
                    "details": {
                        "summary": reason,
                        "call_id": call_id,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_usd": self._last_call_metadata.get("cost_usd", 0)
                    }
                }
                self._log_system_event(enrichment_log_event)

                updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
                if updated_session:
                    yield self._format_sse_with_depth({
                        "statement_input": input_tokens, "statement_output": output_tokens,
                        "turn_input": self.turn_input_tokens,
                        "turn_output": self.turn_output_tokens,
                        "total_input": updated_session.get("input_tokens", 0),
                        "total_output": updated_session.get("output_tokens", 0),
                        "call_id": call_id,
                        "cost_usd": self._last_call_metadata.get("cost_usd", 0)
                    }, "token_update")

                yield self._format_sse_with_depth({"target": "llm", "state": "idle"}, "status_indicator_update")

                try:
                    extracted_args = json.loads(response_text)
                    prompt_args.update(extracted_args)
                    app_logger.info(f"Successfully enriched arguments: {extracted_args}")
                except (json.JSONDecodeError, AttributeError) as e:
                    app_logger.error(f"Failed to parse extracted arguments: {e}. The prompt may fail.")

        self.active_prompt_name = prompt_name
        self.prompt_arguments = self._resolve_arguments(prompt_args)
        self.prompt_type = prompt_info.get("prompt_type", "reporting") if prompt_info else "reporting"

        # Regenerate the plan based on the expanded prompt
        async for event in planner.generate_and_refine_plan():
            yield event

    async def _run_plan(self):
        """Executes the generated meta-plan, delegating to the PhaseExecutor."""
        if not self.meta_plan:
            raise RuntimeError("Cannot execute plan: meta_plan is not generated.")

        phase_executor = PhaseExecutor(self) # Pass self (PlanExecutor instance)

        # Skip final summary check (remains unchanged)
        if not APP_CONFIG.SUB_PROMPT_FORCE_SUMMARY and self.execution_depth > 0 and len(self.meta_plan) > 1:
            last_phase = self.meta_plan[-1]
            last_phase_tools = last_phase.get('relevant_tools', [])
            is_final_report_phase = any(tool in ["TDA_FinalReport", "TDA_ComplexPromptReport"] for tool in last_phase_tools)

            if is_final_report_phase:
                app_logger.info(f"Sub-process (depth {self.execution_depth}) is skipping its final summary phase.")
                event_data = {
                    "step": "Plan Optimization", "type": "plan_optimization",
                    "details": "Sub-process is skipping its final summary task to prevent redundant work. The main process will generate the final report."
                }
                self._log_system_event(event_data)
                yield self._format_sse_with_depth(event_data)
                self.meta_plan = self.meta_plan[:-1]


        while self.current_phase_index < len(self.meta_plan):
            # Check for cancellation before each phase
            self._check_cancellation()

            current_phase = self.meta_plan[self.current_phase_index]
            is_delegated_prompt_phase = 'executable_prompt' in current_phase and self.execution_depth < self.MAX_EXECUTION_DEPTH

            # --- MODIFICATION START: Add replay status prefix ---
            replay_prefix = ""
            if self.is_replay:
                replay_type_text = "Optimized" if "optimized" in str(self.is_replay).lower() else "Original"
                # Find original turn ID (similar logic as in run method)
                original_turn_id = "..."
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                if session_data and isinstance(session_data.get("last_turn_data", {}).get("workflow_history"), list):
                    for idx, turn in enumerate(session_data["last_turn_data"]["workflow_history"]):
                        if turn.get("original_plan") == self.plan_to_execute: # Compare against the plan being replayed
                            original_turn_id = str(idx + 1)
                            break
                replay_prefix = f"🔄 Replay ({replay_type_text} from Turn {original_turn_id}): "
            # --- MODIFICATION END ---


            if is_delegated_prompt_phase:
                prompt_name = current_phase.get('executable_prompt')
                prompt_args = current_phase.get('arguments', {})
                
                # Safeguard: Skip if prompt_name is None or empty (shouldn't happen after planner cleanup, but defensive)
                if not prompt_name or prompt_name in ['None', 'null', '']:
                    app_logger.warning(f"Skipping delegated prompt phase with invalid prompt_name: '{prompt_name}'. Phase: {current_phase}")
                    error_event = {
                        "step": "Plan Optimization",
                        "details": f"Skipping invalid prompt execution step. The plan phase contained an unusable prompt reference.",
                        "type": "workaround"
                    }
                    self._log_system_event(error_event)
                    yield self._format_sse_with_depth(error_event)
                    self.current_phase_index += 1
                    continue
                
                # Send phase_start event for delegated prompt phases
                phase_num = current_phase.get("phase", self.current_phase_index + 1)
                phase_goal = current_phase.get("goal", "No goal defined.")
                event_data = {
                    "step": f"Starting Plan Phase {phase_num}/{len(self.meta_plan)}",
                    "type": "phase_start",
                    "details": {
                        "phase_num": phase_num,
                        "total_phases": len(self.meta_plan),
                        "goal": phase_goal,
                        "phase_details": current_phase,
                        "execution_depth": self.execution_depth
                    }
                }
                self._log_system_event(event_data)
                yield self._format_sse_with_depth(event_data)
                
                async for event in self._run_sub_prompt(prompt_name, prompt_args):
                    yield event
                
                # Send phase_end event after sub-prompt completes
                event_data = {
                    "step": f"Ending Plan Phase {phase_num}/{len(self.meta_plan)}",
                    "type": "phase_end",
                    "details": {"phase_num": phase_num, "total_phases": len(self.meta_plan), "status": "completed", "execution_depth": self.execution_depth}
                }
                self._log_system_event(event_data)
                yield self._format_sse_with_depth(event_data)
            else:
                # --- MODIFICATION START: Pass replay prefix conceptually ---
                # PhaseExecutor needs modification to accept and use this prefix
                # For now, just logging it here. Actual prefixing requires PhaseExecutor changes.
                if replay_prefix:
                    app_logger.debug(f"Passing replay prefix to PhaseExecutor: '{replay_prefix}'")
                async for event in phase_executor.execute_phase(current_phase): # Assuming execute_phase will handle the prefix internally
                    yield event
                # --- MODIFICATION END ---

            self.current_phase_index += 1

        app_logger.debug("Meta-plan has been fully executed. Transitioning to summarization.")
        self.state = self.AgentState.SUMMARIZING

    async def _run_sub_prompt(self, prompt_name: str, prompt_args: dict, is_delegated_task: bool = False):
        """
        Creates and runs a sub-executor for a delegated prompt, adopting its
        final state upon completion to ensure a continuous and complete workflow.
        """
        # Safety check: Don't execute if prompt_name is invalid (final defensive layer)
        if not prompt_name or prompt_name in ['None', 'null', '']:
            error_event = {
                "step": "Plan Optimization",
                "details": f"Skipping execution of invalid prompt reference. The system prevented an error.",
                "type": "workaround"
            }
            self._log_system_event(error_event)
            yield self._format_sse_with_depth(error_event)
            app_logger.error(f"Attempted to run sub-prompt with invalid name: '{prompt_name}'")
            return
        
        event_data = {
            "step": "Prompt Execution Granted",
            "details": f"Executing prompt '{prompt_name}' as part of the plan.",
            "type": "workaround"
        }
        self._log_system_event(event_data)
        yield self._format_sse_with_depth(event_data)

        force_disable_sub_history = is_delegated_task
        if force_disable_sub_history:
            app_logger.info(f"Token Optimization: Disabling history for delegated recovery task '{prompt_name}'.")

        sub_executor = PlanExecutor(
            session_id=self.session_id,
            user_uuid=self.user_uuid,
            original_user_input=f"Executing prompt: {prompt_name}",
            dependencies=self.dependencies,
            active_prompt_name=prompt_name,
            prompt_arguments=prompt_args,
            execution_depth=self.execution_depth + 1,
            disabled_history=self.disabled_history or force_disable_sub_history,
            previous_turn_data=self.previous_turn_data,
            source="prompt_library",
            is_delegated_task=is_delegated_task,
            force_final_summary=APP_CONFIG.SUB_PROMPT_FORCE_SUMMARY,
            event_handler=self.event_handler,
            profile_override_id=self.profile_override_id
        )

        sub_executor.workflow_state = self.workflow_state
        sub_executor.structured_collected_data = self.structured_collected_data

        # Inherit parent's turn token counts so nested execution accumulates correctly
        sub_executor.turn_input_tokens = self.turn_input_tokens
        sub_executor.turn_output_tokens = self.turn_output_tokens



        async for event in sub_executor.run():
            yield event

        self.structured_collected_data = sub_executor.structured_collected_data
        self.workflow_state = sub_executor.workflow_state

        # --- MODIFICATION START: Append sub-trace, don't overwrite ---
        if sub_executor.turn_action_history:
            self.turn_action_history.extend(sub_executor.turn_action_history)
        # --- MODIFICATION END ---

        # Merge sub-executor's lifecycle events for reload persistence
        if hasattr(sub_executor, 'tool_enabled_events') and hasattr(self, 'tool_enabled_events'):
            self.tool_enabled_events.extend(sub_executor.tool_enabled_events)

        self.last_tool_output = sub_executor.last_tool_output

        # Copy sub_executor's turn tokens back to parent (they now include parent's original + sub's additions)
        self.turn_input_tokens = sub_executor.turn_input_tokens
        self.turn_output_tokens = sub_executor.turn_output_tokens
        


        if sub_executor.state == self.AgentState.ERROR:
            app_logger.error(f"Sub-executor for prompt '{prompt_name}' failed.")
            if not self.last_tool_output or self.last_tool_output.get("status") != "error":
                self.last_tool_output = {"status": "error", "error_message": f"Sub-prompt '{prompt_name}' failed."}
        else:
             if self.last_tool_output is None:
                self.last_tool_output = {"status": "success"}

    async def _run_delegated_prompt(self):
        """
        Executes a single, delegated prompt by immediately expanding it into a
        concrete plan. This is used for sub-executors created during
        self-correction to avoid redundant planning and recursion.
        """
        if not self.active_prompt_name:
            app_logger.error("Delegated task started without an active_prompt_name.")
            self.state = self.AgentState.ERROR
            return

        # --- MODIFICATION START: Pass RAG retriever instance to Planner ---
        planner = Planner(self, rag_retriever_instance=self.rag_retriever)
        # --- MODIFICATION END ---
        app_logger.info(f"Delegated task: Directly expanding prompt '{self.active_prompt_name}' into a concrete plan.")

        async for event in planner.generate_and_refine_plan():
            yield event
        # --- MODIFICATION START: Store plan for history even in delegated ---
        # Ensure the plan generated for the delegated task is also stored
        self.original_plan_for_history = copy.deepcopy(self.meta_plan)
        app_logger.info("Stored delegated prompt plan for history.")
        # --- MODIFICATION END ---


        self.state = self.AgentState.EXECUTING
        async for event in self._run_plan():
            yield event

    async def _handle_summarization(self, final_answer_override: str | None):
        """Orchestrates the final summarization and answer formatting."""
        final_content = None

        # Summarization logic remains largely the same
        if self.is_synthesis_from_history:
            app_logger.info("Bypassing summarization. Using direct synthesized answer from planner.")
            synthesized_answer = "Could not extract synthesized answer."
            if self.last_tool_output and isinstance(self.last_tool_output.get("results"), list) and self.last_tool_output["results"]:
                synthesized_answer = self.last_tool_output["results"][0].get("response", synthesized_answer)
            final_content = CanonicalResponse(direct_answer=synthesized_answer)
        elif self.execution_depth > 0 and not self.force_final_summary:
            app_logger.info(f"Sub-planner (depth {self.execution_depth}) completed. Bypassing final summary.")
            self.state = self.AgentState.DONE

            # Emit execution_complete lifecycle event for sub-executor
            try:
                duration_ms = int((time.time() - self.tool_enabled_start_time) * 1000) if hasattr(self, 'tool_enabled_start_time') else 0
                # Calculate turn cost for completion card
                from trusted_data_agent.core.cost_manager import CostManager
                _cost_mgr = CostManager()
                _turn_cost = _cost_mgr.calculate_cost(
                    provider=self.current_provider or "Unknown",
                    model=self.current_model or "Unknown",
                    input_tokens=self.turn_input_tokens,
                    output_tokens=self.turn_output_tokens
                )
                complete_payload = {
                    "profile_type": "tool_enabled",
                    "profile_tag": self._get_current_profile_tag(),
                    "phases_executed": len([a for a in self.turn_action_history if isinstance(a.get("action"), dict) and a["action"].get("tool_name") != "TDA_SystemLog"]),
                    "total_input_tokens": self.turn_input_tokens,
                    "total_output_tokens": self.turn_output_tokens,
                    "duration_ms": duration_ms,
                    "cost_usd": _turn_cost,
                    "success": True
                }

                # Store in tool_enabled_events BEFORE yield (yield suspends execution;
                # storing first guarantees persistence even if generator is not fully consumed)
                if hasattr(self, 'tool_enabled_events'):
                    self.tool_enabled_events.append({
                        "type": "execution_complete",
                        "payload": complete_payload,
                        "metadata": {"execution_depth": self.execution_depth}
                    })

                yield self._emit_lifecycle_event("execution_complete", complete_payload)
                app_logger.info(f"✅ Emitted execution_complete for sub-executor (depth={self.execution_depth})")
            except Exception as e:
                app_logger.warning(f"Failed to emit sub-executor execution_complete: {e}")

            return
        elif final_answer_override:
            final_content = CanonicalResponse(direct_answer=final_answer_override)
        elif self.is_conversational_plan:
            response_text = self.temp_data_holder or "I'm sorry, I don't have a response for that."
            final_content = CanonicalResponse(direct_answer=response_text)
        elif self.last_tool_output and self.last_tool_output.get("status") == "success":
            results = self.last_tool_output.get("results", [{}])
            if not results:
                final_content = CanonicalResponse(direct_answer="The agent has completed its work, but the final step produced no data.")
            else:
                last_result = results[0]
                tool_name = self.last_tool_output.get("metadata", {}).get("tool_name")

                if self.active_prompt_name and tool_name == "TDA_ComplexPromptReport":
                    final_content = PromptReportResponse.model_validate(last_result)
                elif tool_name == "TDA_FinalReport":
                    final_content = CanonicalResponse.model_validate(last_result)
                else:
                    final_content = CanonicalResponse(direct_answer="The agent has completed its work, but a final report was not generated.")
        else:
            final_content = CanonicalResponse(direct_answer="The agent has completed its work, but an issue occurred in the final step.")

        if final_content:
            async for event in self._format_and_yield_final_answer(final_content):
                yield event
            self.state = self.AgentState.DONE

    async def _format_and_yield_final_answer(self, final_content: CanonicalResponse | PromptReportResponse):
        """
        Formats a raw summary string OR a CanonicalResponse object and yields
        the final SSE event to the UI. Also saves the final HTML to session history.
        Includes the turn number in the final event payload.
        """
        formatter_kwargs = {
            "collected_data": self.structured_collected_data,
            "original_user_input": self.original_user_input,
            "active_prompt_name": self.active_prompt_name
        }
        if isinstance(final_content, PromptReportResponse):
            formatter_kwargs["prompt_report_response"] = final_content
        else:
            formatter_kwargs["canonical_response"] = final_content

        formatter = OutputFormatter(**formatter_kwargs)
        final_html, tts_payload = formatter.render()

        # --- MODIFICATION START: Extract component payloads from execution trace ---
        # In tool_enabled profiles, component tool results (canvas, chart, etc.) are
        # stored in turn_action_history with format {"type": "<component_id>", "spec": {...}}.
        # We must extract these and generate the data-component-id divs so the frontend
        # renderer can pick them up — matching what llm_only and rag_focused paths do.
        try:
            component_payloads = []
            for entry in self.turn_action_history:
                result = entry.get("result") if isinstance(entry, dict) else None
                if isinstance(result, dict) and result.get("spec") and result.get("type"):
                    component_payloads.append({
                        "component_id": result["type"],
                        "spec": result["spec"],
                        "render_target": result.get("render_target"),
                    })
            if component_payloads:
                from trusted_data_agent.components.utils import generate_component_html
                final_html += generate_component_html(component_payloads)
        except Exception as comp_extract_err:
            app_logger.warning(f"Failed to extract component payloads from execution trace: {comp_extract_err}")
        # --- MODIFICATION END ---

        # --- MODIFICATION START: Decouple UI and LLM history ---
        # First, determine the clean text summary for the LLM
        clean_summary_for_llm = "The agent has completed its work."
        if hasattr(final_content, 'direct_answer'):
            clean_summary_for_llm = final_content.direct_answer
        elif hasattr(final_content, 'executive_summary'):
            clean_summary_for_llm = final_content.executive_summary
        
        # Store this clean summary in self.final_summary_text *before* saving
        self.final_summary_text = clean_summary_for_llm

        # Now, save both versions to their respective histories
        await session_manager.add_message_to_histories(
            self.user_uuid,
            self.session_id,
            'assistant',
            content=self.final_summary_text, # Clean text for LLM's chat_object
            html_content=final_html,         # Rich HTML for UI's session_history
            is_session_primer=self.is_session_primer
        )
        # --- MODIFICATION END ---

        # NOTE: Removed redundant "LLM has generated the final answer" event (Issue #14)
        # The final_answer event below serves as the visual confirmation in the UI

        # --- MODIFICATION START: Include both HTML and clean text in response ---
        yield self._format_sse_with_depth({
            "final_answer": final_html,
            "final_answer_text": self.final_summary_text,  # Clean text for LLM consumption
            "tts_payload": tts_payload,
            "source": self.source,
            "turn_id": self.current_turn_number, # Use the authoritative instance variable
            "session_id": self.session_id,  # Include session_id for filtering when switching sessions
            # Raw execution data for API consumers
            "execution_trace": self.turn_action_history,
            "collected_data": self.structured_collected_data,
            "turn_input_tokens": self.turn_input_tokens,
            "turn_output_tokens": self.turn_output_tokens,
            "is_session_primer": self.is_session_primer
        }, "final_answer")
        # --- MODIFICATION END ---

        # --- PHASE 2: Emit execution_complete lifecycle event for tool_enabled ---
        try:
            profile_type = self._detect_profile_type()
            if profile_type == "tool_enabled":
                # Calculate duration from tracked start time
                duration_ms = int((time.time() - self.tool_enabled_start_time) * 1000) if hasattr(self, 'tool_enabled_start_time') else 0

                # Calculate turn cost for completion card
                from trusted_data_agent.core.cost_manager import CostManager
                _cost_mgr = CostManager()
                _turn_cost = _cost_mgr.calculate_cost(
                    provider=self.current_provider or "Unknown",
                    model=self.current_model or "Unknown",
                    input_tokens=self.turn_input_tokens,
                    output_tokens=self.turn_output_tokens
                )

                complete_event_payload = {
                    "profile_type": "tool_enabled",
                    "profile_tag": self._get_current_profile_tag(),
                    "phases_executed": len([a for a in self.turn_action_history if isinstance(a.get("action"), dict) and a["action"].get("tool_name") != "TDA_SystemLog"]),
                    "total_input_tokens": self.turn_input_tokens,
                    "total_output_tokens": self.turn_output_tokens,
                    "duration_ms": duration_ms,
                    "cost_usd": _turn_cost,
                    "success": True
                }

                complete_event = self._emit_lifecycle_event("execution_complete", complete_event_payload)
                yield complete_event

                # For depth=0: execution_complete is pre-collected into tool_enabled_events
                # before turn_summary save (in the finally block). SSE emission here is for live UI only.
                # For depth>0 (sub-executors via is_synthesis_from_history path): the finally block's
                # pre-build is guarded by execution_depth==0, so we store here instead.
                if self.execution_depth > 0 and hasattr(self, 'tool_enabled_events'):
                    self.tool_enabled_events.append({
                        "type": "execution_complete",
                        "payload": complete_event_payload,
                        "metadata": {"execution_depth": self.execution_depth}
                    })

                app_logger.info(f"✅ Emitted execution_complete event for tool_enabled profile (depth={self.execution_depth})")
        except Exception as e:
            # Silent failure - don't break execution
            app_logger.warning(f"Failed to emit execution_complete event: {e}")
        # --- PHASE 2 END ---

        # --- Session Name Generation (AFTER final answer) ---
        # Generate session name for first turn AFTER final answer (consolidation requirement)
        # Only for top-level executor (depth==0) to avoid duplicate generation from sub-executors
        # Store collected events in instance variable for workflow history
        self.session_name_events = []
        self.session_name_tokens = (0, 0)

        # Generate session name on first NON-PRIMER turn only
        # Note: Primers are regular turns, so first real query might be turn 2+
        # We check session name not set AND is_session_primer to handle both cases
        if (self.execution_depth == 0 and
            not self.is_delegated_task and
            not self.is_session_primer):  # Skip session primers
            try:
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                current_name = session_data.get("name", "") if session_data else ""

                # Generate name only if not yet set (works for turn 1 or turn 2+ after primer)
                if session_data and (not current_name or current_name == "New Chat"):
                    app_logger.info(f"[SessionName] ✅ GENERATING name for session {self.session_id} (AFTER final answer)")

                    # Generate and emit events using unified generator
                    async for event_dict, event_type, in_tok, out_tok in generate_session_name_with_events(
                        user_query=self.original_user_input,
                        session_id=self.session_id,
                        llm_interface="executor",
                        llm_dependencies=self.dependencies,
                        user_uuid=self.user_uuid,
                        active_profile_id=self.active_profile_id,
                        current_provider=self.current_provider,
                        current_model=self.current_model,
                        profile_llm_instance=self.profile_llm_instance,
                        emit_events=True
                    ):
                        if event_dict is None:
                            # Final yield: update session name
                            new_name = event_type
                            self.session_name_tokens = (in_tok, out_tok)

                            # Add session name tokens to turn totals and session totals
                            if in_tok > 0 or out_tok > 0:
                                self.turn_input_tokens += in_tok
                                self.turn_output_tokens += out_tok
                                await session_manager.update_token_count(
                                    self.user_uuid, self.session_id, in_tok, out_tok
                                )
                                # Emit token_update event so UI reflects updated session totals
                                updated_session = await session_manager.get_session(self.user_uuid, self.session_id)
                                if updated_session:
                                    _name_cost = CostManager().calculate_cost(
                                        provider=self.current_provider or "Unknown",
                                        model=self.current_model or "Unknown",
                                        input_tokens=in_tok,
                                        output_tokens=out_tok
                                    )
                                    yield self._format_sse_with_depth({
                                        "statement_input": in_tok,
                                        "statement_output": out_tok,
                                        "turn_input": self.turn_input_tokens,
                                        "turn_output": self.turn_output_tokens,
                                        "total_input": updated_session.get("input_tokens", 0),
                                        "total_output": updated_session.get("output_tokens", 0),
                                        "call_id": "session_name_generation",
                                        "cost_usd": _name_cost
                                    }, "token_update")
                                # Update turn token counts in workflow_history for reload
                                await session_manager.update_turn_token_counts(
                                    self.user_uuid, self.session_id, self.current_turn_number,
                                    self.turn_input_tokens, self.turn_output_tokens
                                )

                            if new_name and new_name != "New Chat":
                                try:
                                    await session_manager.update_session_name(
                                        self.user_uuid, self.session_id, new_name
                                    )
                                    yield self._format_sse_with_depth({
                                        "session_id": self.session_id,
                                        "newName": new_name
                                    }, "session_name_update")
                                    app_logger.info(f"[SessionName] ✅ Updated session name to '{new_name}'")
                                except Exception as name_e:
                                    app_logger.error(f"[SessionName] ❌ Failed to update: {name_e}", exc_info=True)
                        else:
                            # Emit SSE event and collect for workflow history
                            yield self._format_sse_with_depth(event_dict, event_type)
                            self.session_name_events.append({
                                "type": event_type,
                                "payload": event_dict  # Full event data including step, type, details
                            })
            except Exception as e:
                app_logger.error(f"[SessionName] ❌ Error during generation: {e}", exc_info=True)
        elif self.is_session_primer:
            app_logger.debug(f"[SessionName] ⏭️  Skipping name generation for session primer: {self.original_user_input[:50]}...")