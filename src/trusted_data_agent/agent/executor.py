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


def load_document_context(user_uuid: str, session_id: str, attachments: list, max_total_chars: int | None = None) -> tuple[str | None, list[dict]]:
    """
    Load extracted text from uploaded documents and format as context block.

    This is a module-level function so it can be used by both PlanExecutor and
    the genie execution path.

    Args:
        user_uuid: The user's UUID
        session_id: The session ID
        attachments: List of attachment dicts with file_id, filename keys
        max_total_chars: Optional budget-aware total character limit from context window module.
                        Falls back to APP_CONFIG.DOCUMENT_CONTEXT_MAX_CHARS if not provided.

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

        effective_limit = max_total_chars if max_total_chars else APP_CONFIG.DOCUMENT_CONTEXT_MAX_CHARS
        if total_chars > effective_limit:
            context_parts.append("[Additional documents omitted - context limit reached]")
            truncation_events.append({
                "subtype": "document_truncation",
                "summary": f"Document context limit reached: {len(context_parts)} of {len(attachments)} documents loaded ({total_chars:,} chars)",
                "documents_loaded": len(context_parts),
                "documents_total": len(attachments),
                "total_chars": total_chars,
                "limit_chars": effective_limit,
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


async def _ingest_documents_to_session_store(
    session_store: Any,
    session_id: str,
    user_uuid: str,
    session_data: dict,
) -> None:
    """Ingest uploaded documents into the session vector store for RAG condensation.

    Chunks extracted text from each attachment into ~200-token paragraph blocks.
    Idempotent: session_store.ingest() skips already-indexed chunk IDs.
    Called before handler.assemble() so the store is warm during Pass 4 condensation.
    """
    try:
        from pathlib import Path as _Path
        from trusted_data_agent.vectorstore.types import VectorDocument

        attachments = session_data.get("attachments", [])
        if not attachments:
            return

        manifest_path = _Path(f"tda_sessions/{user_uuid}/uploads/{session_id}/manifest.json")
        if not manifest_path.exists():
            return

        with open(manifest_path) as _f:
            manifest = json.load(_f)

        CHUNK_CHARS = 800  # ~200 tokens per chunk

        for attachment in attachments:
            file_id = attachment.get("file_id", "")
            filename = attachment.get("filename", "unknown")
            file_info = manifest.get(file_id, {})
            extracted_text = file_info.get("extracted_text", "")
            if not extracted_text:
                continue

            # Split into paragraphs, group into ~200-token chunks
            paragraphs = [p.strip() for p in extracted_text.split("\n\n") if p.strip()]
            chunks: list = []
            current: list = []
            current_len = 0
            chunk_idx = 0

            for para in paragraphs:
                if current_len + len(para) > CHUNK_CHARS and current:
                    chunks.append((chunk_idx, "\n\n".join(current)))
                    chunk_idx += 1
                    current = []
                    current_len = 0
                current.append(para)
                current_len += len(para)

            if current:
                chunks.append((chunk_idx, "\n\n".join(current)))

            docs = [
                VectorDocument(
                    id=f"{session_id}__doc__{file_id}__chunk{idx}",
                    content=text,
                    metadata={"file_id": file_id, "filename": filename, "chunk_num": idx},
                )
                for idx, text in chunks
            ]

            if docs:
                await session_store.ingest("document_context", docs)
                app_logger.debug(
                    f"Ingested {len(docs)} document chunks for '{filename}' "
                    f"into session store {session_id}"
                )

    except Exception as _e:
        app_logger.debug(f"Document ingestion to session store skipped (non-critical): {_e}")


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
    def __init__(self, session_id: str, user_uuid: str, original_user_input: str, dependencies: dict, active_prompt_name: str = None, prompt_arguments: dict = None, execution_depth: int = 0, disabled_history: bool = False, previous_turn_data: dict = None, force_history_disable: bool = False, source: str = "text", is_delegated_task: bool = False, force_final_summary: bool = False, plan_to_execute: list = None, is_replay: bool = False, task_id: str = None, profile_override_id: str = None, event_handler=None, is_session_primer: bool = False, attachments: list = None, skill_result=None, canvas_context: dict = None, force_profile_type: str = None, _visited_prompts: frozenset = None):
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
        self.force_profile_type = force_profile_type  # Override _detect_profile_type() (e.g. "tool_enabled" for KG constructor)

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
        # Tracks the prompt call chain for this execution tree to detect cycles (e.g. A→B→A).
        # Inherited by sub-executors and extended with each new prompt name.
        self._visited_prompts: frozenset = _visited_prompts if _visited_prompts is not None else frozenset()

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
        self.context_window_snapshot_event = None  # Store context window snapshot for historical replay
        self.strategic_context_snapshot_event = None  # Per-call strategic snapshot from planner for reload
        self._context_distiller = None  # Lazily initialised from context window type config
        self._distillation_events = []  # Accumulates distillation events across all phases for snapshot
        self.context_builder = None  # ContextBuilder — lazily initialised from context window assembly

        # Knowledge Graph enrichment event for Live Status replay
        self.kg_enrichment_event = None

    async def _get_kg_enrichment(self):
        """
        Fetch KG context enrichment from active components.

        Calls get_component_context_enrichment() and stores the event data
        in self.kg_enrichment_event for SSE emission + persistence.

        Returns:
            Enrichment text to inject into LLM context, or empty string.
        """
        try:
            app_logger.debug(
                f"KG enrichment: starting for profile_id={self.active_profile_id}, "
                f"user_uuid={self.user_uuid}, query='{self.original_user_input[:80]}'"
            )
            from trusted_data_agent.components.manager import get_component_context_enrichment
            kg_text, kg_details = await get_component_context_enrichment(
                query=self.original_user_input,
                profile_id=self.active_profile_id,
                user_uuid=self.user_uuid,
            )
            if kg_text and kg_details:
                self.kg_enrichment_event = {
                    "enrichments": kg_details,
                    "total_entities": sum(d.get("entity_count", 0) for d in kg_details),
                    "total_relationships": sum(d.get("relationship_count", 0) for d in kg_details),
                    "session_id": self.session_id,
                }
                app_logger.info(
                    f"KG enrichment: {self.kg_enrichment_event['total_entities']} entities, "
                    f"{self.kg_enrichment_event['total_relationships']} relationships"
                )
                return kg_text
            else:
                app_logger.debug(
                    f"KG enrichment: returned empty (kg_text={bool(kg_text)}, kg_details={bool(kg_details)})"
                )
        except Exception as e:
            app_logger.warning(f"KG enrichment failed: {e}", exc_info=True)
        return ""

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
        _llm_coro = llm_handler.call_llm_api(
            llm_instance, prompt,
            user_uuid=self.user_uuid, session_id=self.session_id,
            dependencies=self.dependencies, reason=reason,
            system_prompt_override=system_prompt_override, raise_on_error=raise_on_error,
            disabled_history=final_disabled_history,
            active_prompt_name_for_filter=active_prompt_name_for_filter,
            source=source,
            active_profile_id=self.active_profile_id,
            current_provider=effective_provider,
            current_model=effective_model,
            multimodal_content=multimodal_content,
            thinking_budget=self.thinking_budget
        )
        _timeout = APP_CONFIG.LLM_CALL_TIMEOUT_SECONDS
        try:
            if _timeout > 0:
                response_text, statement_input_tokens, statement_output_tokens, actual_provider, actual_model = \
                    await asyncio.wait_for(_llm_coro, timeout=_timeout)
            else:
                response_text, statement_input_tokens, statement_output_tokens, actual_provider, actual_model = \
                    await _llm_coro
        except asyncio.TimeoutError:
            app_logger.error(
                f"LLM call timed out after {_timeout}s [reason='{reason}', "
                f"provider={effective_provider}, model={effective_model}]"
            )
            raise RuntimeError(
                f"The AI provider did not respond within {_timeout} seconds. "
                "It may be overloaded — please try again in a moment."
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
        Recursively distills large data structures into metadata summaries
        to protect the LLM context window.

        Delegates to the unified ExecutionContextDistiller from the
        context_window component when available (configurable thresholds
        from the active context-window-type).  Falls back to APP_CONFIG
        thresholds when the distiller has not been initialised.

        Args:
            data: The data structure to distill
            _events: Optional list to accumulate distillation event dicts
                     (caller reads after call)
        """
        if self._context_distiller is not None:
            return self._context_distiller.distill(data, events=_events)

        # Fallback: inline distillation with global APP_CONFIG thresholds
        # (only reached if _run_context_window_assembly hasn't run yet)
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

    def _snapshot_with_distillation_events(self):
        """Return context window snapshot enriched with intra-turn distillation events."""
        snapshot = getattr(self, 'context_window_snapshot_event', None)
        distill_evts = getattr(self, '_distillation_events', [])
        if snapshot and distill_evts:
            snapshot = dict(snapshot)  # shallow copy to avoid mutating original
            snapshot["distillation_events"] = distill_evts
        return snapshot

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


    async def _run_context_window_assembly(self, profile_type: str, profile_config: dict):
        """
        Run the Context Window Manager orchestrator to assemble context
        and emit a snapshot event for observability.

        Only called when APP_CONFIG.USE_CONTEXT_WINDOW_MANAGER is True.
        In Phase 4 (feature-flagged), this runs alongside existing code paths
        for observability only — it does NOT replace the actual context assembly.
        """
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            from components.builtin.context_window.handler import ContextWindowHandler
            from components.builtin.context_window.base import AssemblyContext

            config_manager = get_config_manager()

            # Resolve context window type for the active profile
            cwt_id = profile_config.get("contextWindowTypeId")
            if cwt_id:
                cwt = config_manager.get_context_window_type(cwt_id, self.user_uuid)
            else:
                cwt = config_manager.get_default_context_window_type(self.user_uuid)

            if not cwt:
                app_logger.debug("No context window type configured — skipping assembly")
                return None

            # Initialise the execution-context distiller from context window
            # type config so that intra-turn distillation uses the same
            # thresholds configured alongside the module budget allocations.
            try:
                from components.builtin.context_window.distiller import ExecutionContextDistiller
                self._context_distiller = ExecutionContextDistiller.from_context_window_type(cwt)
            except Exception as e:
                app_logger.debug(f"Could not create context distiller from cwt: {e}")

            # Resolve model context limit from litellm model metadata
            model_context_limit = 128_000  # Safe default
            try:
                import litellm
                model_key = f"{self.current_provider}/{self.current_model}" if self.current_provider else self.current_model
                model_info = litellm.model_cost.get(model_key) or litellm.model_cost.get(self.current_model or "")
                if model_info:
                    model_context_limit = model_info.get("max_input_tokens") or model_info.get("max_tokens") or 128_000
                    app_logger.debug(f"Resolved model context limit: {model_context_limit:,} tokens for {model_key}")
            except Exception as e:
                app_logger.debug(f"Could not resolve model context limit from litellm: {e}")

            # Apply profile-level context limit override
            context_limit_override = profile_config.get("contextLimitOverride")
            if context_limit_override and isinstance(context_limit_override, int):
                if context_limit_override < model_context_limit:
                    app_logger.info(
                        f"Profile context limit override: {context_limit_override:,} tokens "
                        f"(model default: {model_context_limit:,})"
                    )
                    model_context_limit = context_limit_override

            # Build assembly context
            session_data = await session_manager.get_session(self.user_uuid, self.session_id)

            # Enrich dependencies: modules expect top-level keys like
            # 'current_provider' and 'structured_tools' that live on self
            # or nested under dependencies['STATE'].
            enriched_deps = dict(self.dependencies)
            enriched_deps['current_provider'] = getattr(self, 'current_provider', '') or ''
            enriched_deps['current_model'] = getattr(self, 'current_model', '') or ''
            app_state = enriched_deps.get('STATE')
            if app_state and isinstance(app_state, dict):
                enriched_deps['structured_tools'] = app_state.get('structured_tools', {})
                enriched_deps['mcp_tools'] = app_state.get('mcp_tools', {})

            # Enrich session_data: modules like RAGContextModule and
            # KnowledgeContextModule expect 'current_query' which is on
            # self.original_user_input, not in session_manager data.
            enriched_session = dict(session_data) if session_data else {}
            enriched_session['current_query'] = self.original_user_input or ''

            # Apply session-level context limit override (takes precedence over profile)
            session_context_limit = enriched_session.get('session_context_limit_override')
            if session_context_limit and isinstance(session_context_limit, int):
                if session_context_limit < model_context_limit:
                    app_logger.info(
                        f"Session context limit override: {session_context_limit:,} tokens "
                        f"(effective default: {model_context_limit:,})"
                    )
                    model_context_limit = session_context_limit

            ctx = AssemblyContext(
                profile_type=profile_type,
                profile_id=self.active_profile_id or "",
                session_id=self.session_id,
                user_uuid=self.user_uuid,
                session_data=enriched_session,
                turn_number=getattr(self, "current_turn_number", 1),
                is_first_turn=getattr(self, "current_turn_number", 1) == 1,
                model_context_limit=model_context_limit,
                dependencies=enriched_deps,
                profile_config=profile_config,
            )

            # Create per-session vector store for RAG condensation (if configured)
            session_store = None
            try:
                from components.builtin.context_window.session_vector_store import get_session_store
                rag_backend_id = cwt.get("rag_offload_backend_id")
                backend_config = None
                if rag_backend_id:
                    vs_configs = config_manager.get_vector_store_configurations(self.user_uuid)
                    vs_cfg = next(
                        (c for c in vs_configs if c.get("id") == rag_backend_id), None
                    )
                    if vs_cfg:
                        backend_config = {
                            "backend_type": vs_cfg.get("backend_type", "chromadb"),
                            "backend_config": vs_cfg.get("backend_config", {}),
                        }
                session_store = get_session_store(self.session_id, self.user_uuid, backend_config)
            except Exception as _svs_err:
                app_logger.debug(f"Session store init skipped (non-critical): {_svs_err}")

            # Ingest documents if document_context has rag_offload configured
            if session_store:
                cwt_modules = cwt.get("modules", {})
                doc_module_cfg = cwt_modules.get("document_context", {})
                if doc_module_cfg.get("condensation_strategy") == "rag_offload":
                    asyncio.create_task(
                        _ingest_documents_to_session_store(
                            session_store=session_store,
                            session_id=self.session_id,
                            user_uuid=self.user_uuid,
                            session_data=enriched_session,
                        )
                    )

            # Run orchestrator
            handler = ContextWindowHandler()
            assembled = await handler.assemble(cwt, ctx, session_store=session_store)

            # Log snapshot
            if assembled.snapshot:
                app_logger.info(
                    f"Context Window Snapshot: "
                    f"{assembled.snapshot.total_used:,}/{assembled.snapshot.available_budget:,} tokens "
                    f"({assembled.snapshot.utilization_pct:.1f}% utilization)"
                )

            # Initialise the ContextBuilder with the assembled output so that
            # planner.py and phase_executor.py can consume module content
            # through a single, budget-aware entry point.
            try:
                from components.builtin.context_window.context_builder import ContextBuilder
                if self.context_builder is None:
                    self.context_builder = ContextBuilder(self)
                self.context_builder.set_assembled_context(assembled, ctx, cwt)
                app_logger.debug("ContextBuilder initialised with assembled context")
            except Exception as cb_err:
                app_logger.debug(f"Could not initialise ContextBuilder: {cb_err}")

            return assembled

        except Exception as e:
            app_logger.warning(f"Context window assembly failed (non-critical): {e}")
            return None

    def _detect_profile_type(self) -> str:
        """Detect whether current profile is llm_only, rag_focused, or tool_enabled."""
        if self.force_profile_type:
            return self.force_profile_type
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
        """Delegated to ConversationEngine. Kept for any internal callers."""
        from trusted_data_agent.agent.engines.conversation_engine import ConversationEngine
        async for event in ConversationEngine().run(self):
            yield event

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
        # Use budget-aware module output if available (Phase 5a: context window integration)
        cw_history = getattr(self, '_cw_conversation_history', None)
        if cw_history:
            history_text = cw_history
            app_logger.debug("Using budget-aware conversation history from context window module")
        else:
            try:
                session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                session_history = session_data.get('chat_object', []) if session_data else []

                # Fallback: Format last 10 messages for context, filtering out invalid messages
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
        # Use budget-aware module output if available (Phase 5a: context window integration)
        if not self.disabled_history:
            cw_history = getattr(self, '_cw_conversation_history', None)
            if cw_history:
                parts.append(f"\n--- CONVERSATION HISTORY ---\n{cw_history}\n")
                app_logger.debug("Using budget-aware conversation history from context window module")
            else:
                try:
                    session_data = await session_manager.get_session(self.user_uuid, self.session_id)
                    session_history = session_data.get('chat_object', []) if session_data else []

                    if session_history:
                        # Fallback: Format last 10 messages for context, filtering out invalid messages
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
            # Consumption enforcement failed unexpectedly (e.g. DB unavailable).
            # Execution is allowed to proceed (fail-open) to prevent locking all users out
            # during transient infrastructure issues, but we emit a visible warning event
            # and increment a process-level counter so operators can detect the bypass.
            APP_STATE.setdefault("consumption_enforcement_bypasses", 0)
            APP_STATE["consumption_enforcement_bypasses"] += 1
            bypass_count = APP_STATE["consumption_enforcement_bypasses"]
            app_logger.warning(
                f"[SECURITY] Consumption enforcement bypassed for user {self.user_uuid} "
                f"due to unexpected error (bypass #{bypass_count}): {e}"
            )
            bypass_event = {
                "step": "Security Warning",
                "type": "workaround",
                "details": (
                    f"Consumption limit check could not be completed ({type(e).__name__}). "
                    "Execution is proceeding, but quota limits may not be enforced. "
                    "Contact your administrator if this persists."
                ),
            }
            self._log_system_event(bypass_event)
            yield self._format_sse_with_depth(bypass_event)
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

        # --- EXECUTION PROVENANCE CHAIN (EPC) INIT ---
        from trusted_data_agent.core.provenance import ProvenanceChain, get_previous_turn_tip_hash
        prev_tip = await get_previous_turn_tip_hash(self.user_uuid, self.session_id)
        self.provenance = ProvenanceChain(
            session_id=self.session_id,
            turn_number=self.current_turn_number,
            user_uuid=self.user_uuid,
            profile_type=profile_type,
            previous_turn_tip_hash=prev_tip,
            event_queue=asyncio.Queue(maxsize=100),
        )
        # --- EPC INIT END ---

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
                self.document_context, doc_trunc_events = load_document_context(self.user_uuid, self.session_id, self.attachments, max_total_chars=getattr(self, '_cw_document_max_chars', None))
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

        # --- CONTEXT WINDOW MANAGER (Feature-Flagged) ---
        if APP_CONFIG.USE_CONTEXT_WINDOW_MANAGER:
            assembled_context = await self._run_context_window_assembly(profile_type, profile_config)
            if assembled_context and assembled_context.snapshot:
                # Emit snapshot as SSE event for observability
                snapshot_event = {
                    "step": "Context Window Assembly",
                    "type": "context_window_snapshot",
                    "details": assembled_context.snapshot.to_summary_text(),
                    "payload": assembled_context.snapshot.to_sse_event(),
                }
                self._log_system_event(snapshot_event)
                self.context_window_snapshot_event = assembled_context.snapshot.to_sse_event()
                yield self._format_sse_with_depth(snapshot_event)
            # Extract budget-aware contributions for downstream use
            if assembled_context:
                # Conversation history: text content + window size
                cw_hist = assembled_context.contributions.get("conversation_history")
                if cw_hist:
                    if cw_hist.content:
                        self._cw_conversation_history = cw_hist.content
                    if cw_hist.metadata.get("turn_count", 0) > 0:
                        self._cw_history_window = cw_hist.metadata["turn_count"]
                        app_logger.info(
                            f"Context window: conversation_history budget-aware window={self._cw_history_window} "
                            f"({cw_hist.tokens_used:,} tokens, "
                            f"mode={cw_hist.metadata.get('mode', 'unknown')})"
                        )

                # Knowledge + Document context: budget-aware limits from allocation
                if assembled_context.snapshot:
                    for cm in assembled_context.snapshot.contributions:
                        if cm.module_id == "knowledge_context" and cm.tokens_allocated > 0:
                            self._cw_knowledge_max_tokens = cm.tokens_allocated
                            app_logger.info(
                                f"Context window: knowledge_context budget={cm.tokens_allocated:,} tokens "
                                f"(used={cm.tokens_used:,})"
                            )
                        elif cm.module_id == "document_context" and cm.tokens_allocated > 0:
                            # Convert token budget to chars (1 token ≈ 4 chars)
                            self._cw_document_max_chars = cm.tokens_allocated * 4
                            app_logger.info(
                                f"Context window: document_context budget={cm.tokens_allocated:,} tokens "
                                f"(~{self._cw_document_max_chars:,} chars, used={cm.tokens_used:,})"
                            )

                # Component instructions: pre-computed content (Phase 5e consolidation)
                cw_comp = assembled_context.contributions.get("component_instructions")
                if cw_comp and cw_comp.content:
                    self._cw_component_instructions = cw_comp.content
                    app_logger.info(
                        f"Context window: component_instructions pre-computed "
                        f"({cw_comp.tokens_used:,} tokens, {len(cw_comp.content):,} chars)"
                    )
        # --- CONTEXT WINDOW MANAGER END ---

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
                from trusted_data_agent.llm.client_factory import get_or_create_llm_client
                from trusted_data_agent.core.configuration_service import retrieve_credentials_for_provider

                credentials_result = await retrieve_credentials_for_provider(self.user_uuid, self.current_provider)
                credentials = credentials_result.get("credentials", {}) or {}

                # Always merge LLM config credentials — providers like OpenRouter store their
                # API key only in the LLM config, not in the global credential store.
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

                if credentials:
                    self.profile_llm_instance = await get_or_create_llm_client(self.current_provider, self.current_model, credentials)
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
                from trusted_data_agent.llm.client_factory import get_or_create_llm_client
                from trusted_data_agent.auth.encryption import decrypt_credentials

                # Create strategic LLM instance
                # Credentials are stored per-provider in user_credentials table, not in LLM configs
                strategic_creds = decrypt_credentials(self.user_uuid, self.strategic_provider)
                if not strategic_creds:
                    raise ValueError(f"No credentials found for strategic model provider: {self.strategic_provider}")

                self.strategic_llm_instance = await get_or_create_llm_client(
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

                self.tactical_llm_instance = await get_or_create_llm_client(
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
            # DIRECT EXECUTION PATH - Delegated to IdeateEngine
            from trusted_data_agent.agent.engines.ideate_engine import IdeateEngine
            async for event in IdeateEngine().run(self):
                yield event
            return
        # --- LLM-ONLY PROFILE: DIRECT EXECUTION PATH END (delegated to IdeateEngine) ---

        # --- CONVERSATION WITH TOOLS: LANGCHAIN AGENT PATH ---
        # Routes here when llm_only profile has MCP tools OR active component tools.
        # has_component_tools requires a runtime check (component manager), so applies_to()
        # on ConversationEngine only covers useMcpTools=True; the component-tools case is
        # detected here and also delegated to ConversationEngine.
        is_conversation_with_tools = (profile_type == "llm_only" and (use_mcp_tools or has_component_tools))
        if is_conversation_with_tools:
            from trusted_data_agent.agent.engines.conversation_engine import ConversationEngine
            async for event in ConversationEngine().run(self):
                yield event
            return
        # --- CONVERSATION WITH TOOLS END ---

        # --- RAG FOCUSED EXECUTION PATH ---
        is_rag_focused = self._is_rag_focused_profile()
        if is_rag_focused:
            # DIRECT EXECUTION PATH - Delegated to FocusEngine
            from trusted_data_agent.agent.engines.focus_engine import FocusEngine
            async for event in FocusEngine().run(self):
                yield event
            return


        # DIRECT EXECUTION PATH - Delegated to OptimizeEngine
        from trusted_data_agent.agent.engines.optimize_engine import OptimizeEngine
        async for event in OptimizeEngine().run(self):
            yield event
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
                "context_window_snapshot_event": self._snapshot_with_distillation_events(),
                "strategic_context_snapshot_event": getattr(self, 'strategic_context_snapshot_event', None),
                "tool_enabled_events": getattr(self, 'tool_enabled_events', []),  # Partial lifecycle events for tool_enabled profiles
                # Status fields for partial data
                "status": status,  # "cancelled" or "error"
                "error_message": error_message,
                "error_details": error_details,
                "is_partial": True,  # Flag to indicate incomplete execution
                "skills_applied": self.skill_result.to_applied_list() if self.skill_result and self.skill_result.has_content else []
            }

            # --- EPC: Seal provenance chain on error/cancellation ---
            try:
                if hasattr(self, 'provenance') and not self.provenance._sealed:
                    self.provenance.add_error_step(
                        status, error_message or "Unknown error")
                    turn_summary.update(self.provenance.finalize())
            except Exception as _epc_err:
                app_logger.debug(f"[EPC] error finalize: {_epc_err}")
            # --- EPC END ---

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

    # --- Phase parallelization helpers ---

    @staticmethod
    def _phase_referenced_deps(phase: dict) -> set:
        """Return the set of phase numbers that this phase directly references."""
        _PAT = re.compile(r'result_of_phase_(\d+)|phase_(\d+)')

        def _scan(obj):
            nums = set()
            if isinstance(obj, str):
                for m in _PAT.finditer(obj):
                    nums.add(int(m.group(1) or m.group(2)))
            elif isinstance(obj, dict):
                for v in obj.values():
                    nums |= _scan(v)
            elif isinstance(obj, list):
                for item in obj:
                    nums |= _scan(item)
            return nums

        refs = set()
        refs |= _scan(phase.get('loop_over', ''))
        refs |= _scan(phase.get('arguments', {}))
        refs |= _scan(phase.get('goal', ''))
        return refs

    _TERMINAL_TOOLS = frozenset({
        "TDA_FinalReport", "TDA_ComplexPromptReport",
        "TDA_ContextReport", "TDA_LLMTask",
    })

    @classmethod
    def _is_terminal_phase(cls, phase: dict) -> bool:
        """A terminal phase cannot share a parallel group with any other phase."""
        if phase.get('type') == 'loop':
            return True
        if 'executable_prompt' in phase:
            return True
        tools = set(phase.get('relevant_tools') or [])
        return bool(tools & cls._TERMINAL_TOOLS)

    @classmethod
    def _build_phase_groups(cls, meta_plan: list) -> list:
        """
        Return a list of groups where each group is a list of phases.
        Groups with >1 phase can be run in parallel — their phases have
        no cross-dependencies and none is terminal.
        """
        groups = []
        current_group: list = []
        current_nums: set = set()

        for phase in meta_plan:
            phase_num = phase.get('phase', 0)

            if cls._is_terminal_phase(phase):
                if current_group:
                    groups.append(current_group)
                    current_group = []
                    current_nums = set()
                groups.append([phase])
                continue

            deps = cls._phase_referenced_deps(phase)
            if deps & current_nums:
                # This phase depends on something already in the current group —
                # flush and start a fresh group.
                groups.append(current_group)
                current_group = [phase]
                current_nums = {phase_num}
            else:
                current_group.append(phase)
                current_nums.add(phase_num)

        if current_group:
            groups.append(current_group)

        return groups

    async def _stream_parallel_phases(self, phase_executor, phases: list):
        """
        Execute a list of independent phases concurrently, collect all events per
        phase, then yield them phase-by-phase.

        The collect-then-yield approach ensures the ui.js phase container stack
        sees a clean sequential lifecycle (phase_start … phase_end) for each phase,
        even though the underlying execution was parallel. Interleaving events from
        multiple phases would otherwise confuse the stack and lose "Phase N Completed"
        footers.

        turn_action_history entries produced during the parallel group are also
        post-sorted by phase_num so that historical replay renders in the correct order.
        """
        phase_nums = [p.get('phase', '?') for p in phases]
        n = len(phases)

        # Emit a system note so the Live Status panel shows parallel execution
        parallel_note = {
            "step": f"Parallel Execution: phases {phase_nums}",
            "type": "system_message",
            "details": {
                "summary": f"Executing {n} independent phases concurrently: {phase_nums}",
                "parallel_phases": phase_nums,
            },
        }
        self._log_system_event(parallel_note)
        yield self._format_sse_with_depth(parallel_note)

        # Mark where parallel phase entries begin in turn_action_history
        history_start = len(self.turn_action_history)

        async def _collect(phase):
            """Run one phase generator and collect all SSE events into a list."""
            events = []
            try:
                is_delegated = ('executable_prompt' in phase
                                and self.execution_depth < self.MAX_EXECUTION_DEPTH)
                if is_delegated:
                    gen = self._run_sub_prompt(
                        phase.get('executable_prompt'), phase.get('arguments', {}))
                else:
                    gen = phase_executor.execute_phase(phase)
                async for event in gen:
                    events.append(event)
            except Exception as exc:
                app_logger.error(f"Parallel phase error (phase {phase.get('phase', '?')}): {exc}",
                                 exc_info=True)
            return events

        # Run all phases concurrently; each returns its complete event list
        per_phase_events = await asyncio.gather(
            *[_collect(p) for p in phases], return_exceptions=True)

        # Yield events phase-by-phase so the UI sees clean sequential lifecycles
        for phase_events in per_phase_events:
            if isinstance(phase_events, Exception):
                app_logger.error(f"Parallel phase raised: {phase_events}")
                continue
            for event in phase_events:
                yield event

        # Post-sort turn_action_history entries by phase_num for correct historical replay
        def _entry_phase_num(entry):
            action = entry.get('action', {})
            if not isinstance(action, dict):
                return float('inf')
            # Tool call entries carry metadata.phase_number
            pn = action.get('metadata', {}).get('phase_number')
            if pn is not None:
                return int(pn)
            # TDA_SystemLog entries carry details.phase_num
            if action.get('tool_name') == 'TDA_SystemLog':
                details = action.get('arguments', {}).get('details', {})
                if isinstance(details, dict):
                    pn = details.get('phase_num')
                    if pn is not None:
                        return int(pn)
            return float('inf')

        parallel_slice = self.turn_action_history[history_start:]
        parallel_slice.sort(key=_entry_phase_num)  # stable sort preserves intra-phase order
        self.turn_action_history[history_start:] = parallel_slice

    # --- End phase parallelization helpers ---

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


        # Build phase groups — consecutive independent phases share a group and
        # are run concurrently; terminal/loop/synthesis phases run alone.
        phase_groups = self._build_phase_groups(self.meta_plan)
        has_parallel = any(len(g) > 1 for g in phase_groups)
        if has_parallel:
            n_parallel = sum(len(g) for g in phase_groups if len(g) > 1)
            app_logger.info(
                f"Phase parallelization: {len(self.meta_plan)} phases → {len(phase_groups)} groups "
                f"({n_parallel} phases eligible for parallel execution)"
            )

        for group in phase_groups:
            # Check for cancellation before each group
            self._check_cancellation()

            if len(group) > 1:
                # Parallel group — stream events from all phases concurrently
                async for event in self._stream_parallel_phases(phase_executor, group):
                    yield event
                self.current_phase_index += len(group)
                continue

            # Single-phase group — existing sequential path (unchanged behaviour)
            current_phase = group[0]
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

        # Cycle detection: abort if this prompt is already in the current call chain
        if prompt_name in self._visited_prompts:
            cycle_path = " → ".join(sorted(self._visited_prompts)) + f" → {prompt_name}"
            app_logger.error(f"Prompt cycle detected and blocked: {cycle_path}")
            cycle_event = {
                "step": "System Correction",
                "details": f"Circular prompt execution blocked: '{prompt_name}' is already in the current call chain ({cycle_path}). Skipping to prevent infinite recursion.",
                "type": "workaround"
            }
            self._log_system_event(cycle_event)
            yield self._format_sse_with_depth(cycle_event)
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
            profile_override_id=self.profile_override_id,
            _visited_prompts=self._visited_prompts | {prompt_name},
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

    def _build_tool_context_summary(self) -> str | None:
        """
        Build a compact summary of MCP tool calls from this turn for cross-turn LLM context.

        Stored in chat_object so conversation_history carries tool awareness across turns
        without re-running queries. Only data-returning tools are included — TDA_ internal
        tools are skipped as they carry no cross-turn value.
        """
        _TDA_PREFIX = "TDA_"
        lines = []

        for entry in self.turn_action_history:
            action = entry.get("action", {})
            result = entry.get("result", {})
            if not isinstance(action, dict):
                continue
            tool_name = action.get("tool_name", "")

            # Skip internal orchestration tools
            if tool_name.startswith(_TDA_PREFIX):
                # Date range orchestrator: summarise using its consolidated result
                args = action.get("arguments", {})
                if args.get("orchestration_type") == "date_range_complete":
                    target = args.get("target_tool", tool_name)
                    n_iter = args.get("num_iterations", "?")
                    lines.append(self._format_tool_summary_line(
                        f"{target} (×{n_iter} dates)", action, result
                    ))
                continue

            if result.get("status") == "error":
                continue

            lines.append(self._format_tool_summary_line(tool_name, action, result))

        if not lines:
            return None
        return "[Tool Execution Summary]\n" + "\n".join(lines)

    def _format_tool_summary_line(self, tool_name: str, action: dict, result: dict) -> str:
        """Format a single tool call as a compact summary line."""
        args = action.get("arguments", {})
        meta = result.get("metadata", {})
        results_list = result.get("results", [])

        # Primary argument: prefer sql/query fields, then first string value
        primary_arg = ""
        for key in ("sql", "query", "statement"):
            if key in args and isinstance(args[key], str):
                val = args[key].replace("\n", " ").strip()
                primary_arg = val[:120] + "..." if len(val) > 120 else val
                break
        if not primary_arg:
            for val in args.values():
                if isinstance(val, str) and val.strip():
                    primary_arg = val[:80] + "..." if len(val) > 80 else val
                    break

        # Row count and columns — prefer distiller metadata, fall back to inline
        row_count = meta.get("row_count")
        columns = meta.get("columns")
        if row_count is None and results_list:
            row_count = len(results_list)
        if columns is None and results_list and isinstance(results_list[0], dict):
            columns = list(results_list[0].keys())
        # Normalize: distiller may store columns as [{name, type}, ...] — extract names only
        if columns and isinstance(columns[0], dict):
            columns = [c.get("name", str(c)) for c in columns]

        # One sample row (first row, trimmed)
        sample = ""
        if results_list and isinstance(results_list[0], dict):
            row = results_list[0]
            trimmed = {k: (str(v)[:60] if len(str(v)) > 60 else v)
                       for k, v in list(row.items())[:5]}
            sample = f", sample: {trimmed}"

        row_info = f"→ {row_count} row{'s' if row_count != 1 else ''}" if row_count is not None else ""
        col_info = f", cols: {columns}" if columns else ""
        arg_info = f": {primary_arg}" if primary_arg else ""

        return f"• {tool_name}{arg_info} {row_info}{col_info}{sample}".strip()

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
                    if result.get("type") == "chart":
                        continue  # Formatter handles charts via structured_collected_data with paired table details
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
        tool_context = self._build_tool_context_summary() if self._detect_profile_type() == "tool_enabled" else None
        await session_manager.add_message_to_histories(
            self.user_uuid,
            self.session_id,
            'assistant',
            content=self.final_summary_text, # Clean text for LLM's chat_object
            html_content=final_html,         # Rich HTML for UI's session_history
            tool_context=tool_context,
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