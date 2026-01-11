# src/trusted_data_agent/api/routes.py
import json
import os
import logging
import asyncio
import sys
import copy
import hashlib
import httpx
import uuid # Import the uuid module
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions

from quart import Blueprint, request, jsonify, render_template, Response, abort
from langchain_mcp_adapters.prompts import load_mcp_prompt
from langchain_mcp_adapters.client import MultiServerMCPClient

from trusted_data_agent.auth.middleware import require_auth, optional_auth
from trusted_data_agent.core.config import APP_CONFIG, APP_STATE
from trusted_data_agent.core import session_manager
from trusted_data_agent.agent.prompts import PROVIDER_SYSTEM_PROMPTS
from trusted_data_agent.agent.executor import PlanExecutor
from trusted_data_agent.agent.rag_template_generator import RAGTemplateGenerator
from trusted_data_agent.llm import handler as llm_handler
from trusted_data_agent.agent import execution_service
from trusted_data_agent.core import configuration_service
from trusted_data_agent.core.utils import (
    get_tts_client,
    synthesize_speech,
    unwrap_exception,
    _get_prompt_info,
    _regenerate_contexts,
    generate_task_id # Import generate_task_id
)


api_bp = Blueprint('api', __name__)
app_logger = logging.getLogger("quart.app")

def _get_user_uuid_from_request():
    """
    Extracts User UUID from request using JWT token.
    
    Authentication is always required.
    Returns None if not authenticated (caller should handle error).
    """
    try:
        from trusted_data_agent.auth.middleware import get_current_user
        user = get_current_user()
        if user and user.id:
            app_logger.debug(f"User UUID from auth token: {user.id}")
            return user.id
        else:
            app_logger.error(f"Authentication failed - get_current_user returned: {user}")
            return None
    except Exception as e:
        app_logger.error(f"Failed to get user from auth token: {e}", exc_info=True)
        return None


@api_bp.route("/")
async def index():
    """Serves the main HTML page."""
    return await render_template("index.html")


@api_bp.route("/login")
async def login_page():
    """Serves the login page."""
    return await render_template("login.html")


@api_bp.route("/register")
async def register_page():
    """Serves the registration page."""
    return await render_template("register.html")

@api_bp.route("/verify-email")
async def verify_email_page():
    """Serves the email verification page."""
    return await render_template("verify_email.html")

@api_bp.route("/api/status")
@optional_auth
async def get_application_status(current_user):
    """
    Returns the current configuration status of the application.
    This is used by the front end on startup to synchronize its state.
    Authentication is required - returns not configured if user not authenticated.
    """
    # Get user UUID - if not authenticated, return not configured
    user_uuid = current_user.id if current_user else None
    if not user_uuid:
        return jsonify({
            "isConfigured": False,
            "authenticationRequired": True
        })

    # Check if default profile exists (simplified check - activation enforces LLM+MCP configured)
    from trusted_data_agent.core.config_manager import get_config_manager
    config_manager = get_config_manager()
    default_profile_id = config_manager.get_default_profile_id(user_uuid)
    is_configured = default_profile_id is not None

    # Check RAG status
    rag_retriever = APP_STATE.get('rag_retriever_instance')
    
    # Check database for user's collections (more reliable than in-memory state)
    # This ensures RAG shows as active even when collections are created but not yet loaded
    rag_active = False
    if rag_retriever and APP_CONFIG.RAG_ENABLED:
        try:
            from trusted_data_agent.core.collection_db import get_collection_db
            collection_db = get_collection_db()
            user_collections = collection_db.get_all_collections(user_id=user_uuid)
            # RAG is active if user has at least one collection (enabled or not)
            rag_active = len(user_collections) > 0
            app_logger.debug(f"RAG Status Check: retriever_exists=True, user_collections={len(user_collections)}, rag_active={rag_active}")
        except Exception as e:
            app_logger.warning(f"Failed to check RAG collections from database: {e}")
            # Fallback to checking in-memory collections
            rag_active = bool(rag_retriever.collections)
            app_logger.debug(f"RAG Status Check (fallback): collections_loaded={len(rag_retriever.collections)}, rag_active={rag_active}")
    else:
        app_logger.debug(f"RAG Status Check: retriever_exists={bool(rag_retriever)}, rag_enabled={APP_CONFIG.RAG_ENABLED}, rag_active=False")
    
    if is_configured:
        status_payload = {
            "isConfigured": True,
            "provider": APP_CONFIG.ACTIVE_PROVIDER,
            "model": APP_CONFIG.ACTIVE_MODEL,
            "mcp_server": { "id": APP_CONFIG.CURRENT_MCP_SERVER_ID },
            "rag_active": rag_active,
            "rag_enabled": APP_CONFIG.RAG_ENABLED
        }
        return jsonify(status_payload)
    else:
        status_payload = {
            "isConfigured": False,
            "rag_active": rag_active,
            "rag_enabled": APP_CONFIG.RAG_ENABLED
        }
        return jsonify(status_payload)

@api_bp.route("/api/questions")
@optional_auth
async def get_rag_questions(current_user):
    """
    Returns semantically relevant questions from the RAG knowledge base.
    Supports profile-based filtering and semantic ranking.
    
    Query parameters:
    - query: Search text for semantic matching (optional, returns all if empty)
    - profile_id: Profile ID for collection filtering (optional)
    - limit: Maximum number of results (default: 10)
    """
    from trusted_data_agent.core.config_manager import get_config_manager
    from trusted_data_agent.agent.rag_access_context import RAGAccessContext
    
    query_text = request.args.get('query', '').strip()
    profile_id = request.args.get('profile_id', '').strip()
    limit = int(request.args.get('limit', 10))
    
    retriever = APP_STATE.get('rag_retriever_instance')
    if not retriever:
        return jsonify({"questions": []})
    
    # Get user context for access control
    user_uuid = current_user.id if current_user else None
    rag_context = RAGAccessContext(user_uuid, retriever) if user_uuid else None
    
    # Determine which collections to query based on profile and user access
    allowed_collection_ids = None
    if profile_id:
        config_manager = get_config_manager()
        profiles = config_manager.get_profiles(user_uuid)
        profile = next((p for p in profiles if p.get("id") == profile_id), None)
        
        if profile:
            autocomplete_collections = profile.get("autocompleteCollections", ["*"])
            if autocomplete_collections != ["*"]:
                allowed_collection_ids = set(autocomplete_collections)
    
    # Intersect with user-accessible collections if context available
    if rag_context:
        user_accessible = rag_context.accessible_collections
        if allowed_collection_ids is None:
            allowed_collection_ids = user_accessible
        else:
            allowed_collection_ids = allowed_collection_ids & user_accessible
    
    # If no query text, fall back to getting all unique questions (filtered by profile and user)
    if not query_text:
        questions = set()
        for coll_id, collection in retriever.collections.items():
            # Skip if profile filtering is active and this collection isn't allowed
            if allowed_collection_ids is not None and coll_id not in allowed_collection_ids:
                continue
                
            try:
                # Build where clause with user filtering if context available
                # Note: Template-generated cases should be accessible to all users, so we use OR logic
                where_clause = {"$and": [
                    {"strategy_type": {"$eq": "successful"}},
                    {"is_most_efficient": {"$eq": True}},
                    {"user_feedback_score": {"$gte": 0}}  # Exclude downvoted cases
                ]}
                if rag_context and user_uuid:
                    # Include both user's own cases AND template-generated cases
                    where_clause["$and"].append({
                        "$or": [
                            {"user_uuid": {"$eq": user_uuid}},
                            {"user_uuid": {"$eq": RAGTemplateGenerator.TEMPLATE_SESSION_ID}}
                        ]
                    })
                
                # Only get questions from successful and most efficient cases (not downvoted)
                results = collection.get(
                    where=where_clause,
                    include=["metadatas"]
                )
                for metadata in results.get("metadatas", []):
                    user_query = metadata.get("user_query", "")
                    # Filter out very short queries (< 3 chars) as they're not useful suggestions
                    if user_query and len(user_query.strip()) >= 3:
                        questions.add(user_query)
            except Exception as e:
                app_logger.error(f"Error getting documents from collection {collection.name}: {e}")
        
        return jsonify({"questions": sorted(list(questions))[:limit]})
    
    # Semantic search: query each allowed collection and aggregate results
    all_results = []
    for coll_id, collection in retriever.collections.items():
        # Skip if profile filtering is active and this collection isn't allowed
        if allowed_collection_ids is not None and coll_id not in allowed_collection_ids:
            continue
            
        try:
            # Build where clause with user filtering if context available
            # Note: Template-generated cases should be accessible to all users, so we use OR logic
            where_clause = {"$and": [
                {"strategy_type": {"$eq": "successful"}},
                {"is_most_efficient": {"$eq": True}},
                {"user_feedback_score": {"$gte": 0}}  # Exclude downvoted cases
            ]}
            if rag_context and user_uuid:
                # Include both user's own cases AND template-generated cases
                where_clause["$and"].append({
                    "$or": [
                        {"user_uuid": {"$eq": user_uuid}},
                        {"user_uuid": {"$eq": RAGTemplateGenerator.TEMPLATE_SESSION_ID}}
                    ]
                })
            
            # Only query successful and most efficient cases (not downvoted)
            results = collection.query(
                query_texts=[query_text],
                n_results=limit,
                where=where_clause,
                include=["metadatas", "distances"]
            )
            
            # Extract questions with their similarity scores
            if results and results.get("metadatas") and results["metadatas"][0]:
                for idx, metadata in enumerate(results["metadatas"][0]):
                    if "user_query" in metadata:
                        distance = results["distances"][0][idx] if results.get("distances") else 0
                        all_results.append({
                            "question": metadata["user_query"],
                            "distance": distance,
                            "collection_id": coll_id
                        })
        except Exception as e:
            app_logger.error(f"Error querying collection {collection.name}: {e}")
    
    # Sort by distance (lower is better for cosine/L2 distance) and deduplicate
    all_results.sort(key=lambda x: x["distance"])
    seen_questions = set()
    unique_questions = []
    
    for result in all_results:
        question = result["question"]
        if question not in seen_questions:
            seen_questions.add(question)
            unique_questions.append(question)
            if len(unique_questions) >= limit:
                break
    
    return jsonify({"questions": unique_questions})


@api_bp.route("/consumption_warnings", methods=["GET"])
async def consumption_warnings():
    """
    Returns consumption usage warnings for the welcome screen.
    Checks hourly, daily, and monthly limits and returns the highest percentage.
    """
    from trusted_data_agent.auth.middleware import get_current_user
    
    current_user = get_current_user()
    if not current_user:
        return jsonify({"warning_level": None, "percentage": 0, "message": "Not authenticated"}), 401
    
    user_uuid = current_user.id

    try:
        from trusted_data_agent.auth.consumption_enforcer import ConsumptionEnforcer
        from trusted_data_agent.auth.models import User
        from trusted_data_agent.auth.database import get_db_session
        
        # Check if user is admin (no limits)
        with get_db_session() as session:
            user = session.query(User).filter_by(id=user_uuid).first()
            is_admin = user.is_admin if user else False
        
        if is_admin:
            return jsonify({"warning_level": None, "percentage": 0, "message": "Admin - No limits"})
        
        # Get consumption enforcer and check usage
        enforcer = ConsumptionEnforcer(user_uuid)
        usage = enforcer.get_current_usage()
        
        # Calculate highest percentage across all limits
        max_percentage = 0
        limit_name = ""
        
        # Check hourly prompts
        if usage.get('prompts_per_hour_limit') and usage['prompts_per_hour_limit'] > 0:
            hourly_pct = (usage['prompts_this_hour'] / usage['prompts_per_hour_limit']) * 100
            if hourly_pct > max_percentage:
                max_percentage = hourly_pct
                limit_name = "hourly prompts"
        
        # Check daily prompts
        if usage.get('prompts_per_day_limit') and usage['prompts_per_day_limit'] > 0:
            daily_pct = (usage['prompts_today'] / usage['prompts_per_day_limit']) * 100
            if daily_pct > max_percentage:
                max_percentage = daily_pct
                limit_name = "daily prompts"
        
        # Check monthly input tokens
        if usage.get('input_tokens_per_month_limit') and usage['input_tokens_per_month_limit'] > 0:
            input_pct = (usage['input_tokens_this_month'] / usage['input_tokens_per_month_limit']) * 100
            if input_pct > max_percentage:
                max_percentage = input_pct
                limit_name = "monthly input tokens"
        
        # Check monthly output tokens
        if usage.get('output_tokens_per_month_limit') and usage['output_tokens_per_month_limit'] > 0:
            output_pct = (usage['output_tokens_this_month'] / usage['output_tokens_per_month_limit']) * 100
            if output_pct > max_percentage:
                max_percentage = output_pct
                limit_name = "monthly output tokens"
        
        # Determine warning level
        warning_level = None
        message = ""
        
        if max_percentage >= 100:
            warning_level = "critical"
            message = f"You've reached your {limit_name} limit ({int(max_percentage)}%). New requests will be blocked."
        elif max_percentage >= 95:
            warning_level = "urgent"
            message = f"You've used {int(max_percentage)}% of your {limit_name} quota. You're very close to the limit."
        elif max_percentage >= 80:
            warning_level = "warning"
            message = f"You've used {int(max_percentage)}% of your {limit_name} quota. Consider managing your usage."
        
        return jsonify({
            "warning_level": warning_level,
            "percentage": round(max_percentage, 1),
            "message": message,
            "usage": usage
        })
        
    except Exception as e:
        app_logger.error(f"Error fetching consumption warnings: {e}", exc_info=True)
        return jsonify({"warning_level": None, "percentage": 0, "message": "Error checking consumption"}), 500

@api_bp.route("/simple_chat", methods=["POST"])
async def simple_chat():
    """
    Handles direct, tool-less chat with the configured LLM.
    This is used by the 'Chat' modal in the UI.
    """
    if not APP_STATE.get('llm'):
        return jsonify({"error": "LLM not configured."}), 400

    # Check consumption limits
    user_uuid = _get_user_uuid_from_request()
    if user_uuid:
        try:
            from trusted_data_agent.auth.consumption_enforcer import ConsumptionEnforcer
            from trusted_data_agent.auth.models import User
            from trusted_data_agent.auth.database import get_db_session
            
            # Check if user is admin
            with get_db_session() as session:
                user = session.query(User).filter_by(id=user_uuid).first()
                is_admin = user.is_admin if user else False
            
            if not is_admin:
                enforcer = ConsumptionEnforcer(user_uuid)
                can_proceed, error_message = enforcer.can_execute_prompt()
                
                if not can_proceed:
                    app_logger.warning(f"Consumption limit exceeded (simple_chat) for user {user_uuid}: {error_message}")
                    return jsonify({"error": error_message, "type": "rate_limit_exceeded"}), 429
        except Exception as e:
            app_logger.error(f"Error checking consumption limits: {e}", exc_info=True)
            # Fail open

    data = await request.get_json()
    message = data.get("message")
    history = data.get("history", [])

    if not message:
        return jsonify({"error": "No message provided."}), 400

    try:
        response_text, _, _, _, _ = await llm_handler.call_llm_api(
            llm_instance=APP_STATE.get('llm'),
            prompt=message,
            chat_history=history,
            system_prompt_override="You are a helpful assistant.",
            dependencies={'STATE': APP_STATE},
            reason="Simple, tool-less chat."
        )

        final_response = response_text.replace("FINAL_ANSWER:", "").strip()

        return jsonify({"response": final_response})

    except Exception as e:
        app_logger.error(f"Error in simple_chat: {e}", exc_info=True)
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500

@api_bp.route("/app-config")
async def get_app_config():
    """Returns the startup configuration flags and license info."""
    from trusted_data_agent.core.config_manager import get_config_manager
    
    # Load window defaults from config
    config_manager = get_config_manager()
    config = config_manager.load_config()
    window_defaults = config.get('window_defaults', {
        # Session History Panel
        'session_history_visible': True,
        'session_history_default_mode': 'collapsed',
        'session_history_user_can_toggle': True,
        # Resources Panel
        'resources_visible': True,
        'resources_default_mode': 'collapsed',
        'resources_user_can_toggle': True,
        # Status Window
        'status_visible': True,
        'status_default_mode': 'collapsed',
        'status_user_can_toggle': True,
        # Other settings
        'always_show_welcome_screen': False,
        'default_theme': 'legacy'
    })
    
    return jsonify({
        "all_models_unlocked": APP_CONFIG.ALL_MODELS_UNLOCKED,
        "charting_enabled": APP_CONFIG.CHARTING_ENABLED,
        "allow_synthesis_from_history": APP_CONFIG.ALLOW_SYNTHESIS_FROM_HISTORY,
        "default_charting_intensity": APP_CONFIG.DEFAULT_CHARTING_INTENSITY,
        "voice_conversation_enabled": APP_CONFIG.VOICE_CONVERSATION_ENABLED,
        "rag_enabled": APP_CONFIG.RAG_ENABLED,
        "license_info": APP_STATE.get("license_info"),
        "window_defaults": window_defaults
    })

@api_bp.route("/api/prompts-version")
async def get_prompts_version():
    """
    Returns a SHA-256 hash of the master system prompts.
    """
    try:
        # Convert LazyPrompt objects to strings for JSON serialization
        prompts_dict = {k: str(v) for k, v in PROVIDER_SYSTEM_PROMPTS.items()}
        prompts_str = json.dumps(prompts_dict, sort_keys=True)
        prompt_hash = hashlib.sha256(prompts_str.encode('utf-8')).hexdigest()
        return jsonify({"version": prompt_hash})
    except Exception as e:
        app_logger.error(f"Failed to generate prompts version hash: {e}", exc_info=True)
        return jsonify({"error": "Could not generate prompts version"}), 500

@api_bp.route("/api_key/<provider>")
async def get_api_key(provider):
    """Retrieves API keys from environment variables for pre-population."""
    key = None
    provider_lower = provider.lower()

    if provider_lower == 'google':
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return jsonify({"apiKey": key or ""})
    elif provider_lower == 'anthropic':
        key = os.environ.get("ANTHROPIC_API_KEY")
        return jsonify({"apiKey": key or ""})
    elif provider_lower == 'openai':
        key = os.environ.get("OPENAI_API_KEY")
        return jsonify({"apiKey": key or ""})
    elif provider_lower == 'azure':
        keys = {
            "azure_api_key": os.environ.get("AZURE_OPENAI_API_KEY"),
            "azure_endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT"),
            "azure_deployment_name": os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME"),
            "azure_api_version": os.environ.get("AZURE_OPENAI_API_VERSION")
        }
        return jsonify(keys)
    elif provider_lower == 'friendli':
        keys = {
            "friendli_token": os.environ.get("FRIENDLI_TOKEN"),
            "friendli_endpoint_url": os.environ.get("FRIENDLI_ENDPOINT_URL")
        }
        return jsonify(keys)
    elif provider_lower == 'amazon':
        keys = {
            "aws_access_key_id": os.environ.get("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.environ.get("AWS_SECRET_ACCESS_KEY"),
            "aws_region": os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        }
        return jsonify(keys)
    elif provider_lower == 'ollama':
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        return jsonify({"host": host})

    return jsonify({"error": "Unknown provider"}), 404

@api_bp.route("/api/synthesize-speech", methods=["POST"])
async def text_to_speech():
    """
    Converts text to speech using Google Cloud TTS.
    """
    if not APP_CONFIG.VOICE_CONVERSATION_ENABLED:
        app_logger.warning("Voice conversation feature is disabled by config. Aborting text-to-speech request.")
        return jsonify({"error": "Voice conversation feature is disabled."}), 403

    data = await request.get_json()
    text = data.get("text")
    if not text:
        app_logger.warning("No text provided in request body for speech synthesis.")
        return jsonify({"error": "No text provided for synthesis."}), 400

    if "tts_client" not in APP_STATE or APP_STATE["tts_client"] is None:
        app_logger.info("TTS client not in STATE, attempting to initialize.")
        APP_STATE["tts_client"] = get_tts_client()

    tts_client = APP_STATE.get("tts_client")
    if not tts_client:
        app_logger.error("TTS client is still not available after initialization attempt.")
        return jsonify({"error": "TTS client could not be initialized. Check server logs."}), 500

    audio_content = synthesize_speech(tts_client, text)

    if audio_content:
        app_logger.debug(f"Returning synthesized audio content ({len(audio_content)} bytes).")
        return Response(audio_content, mimetype="audio/mpeg")
    else:
        app_logger.error("synthesize_speech returned None. Sending error response.")
        return jsonify({"error": "Failed to synthesize speech."}), 500

@api_bp.route("/tools")
async def get_tools():
    """Returns the categorized list of MCP tools."""
    # Auto-load profile if not already loaded
    if not APP_STATE.get("mcp_client"):
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.core import configuration_service
        config_manager = get_config_manager()
        user_uuid = _get_user_uuid_from_request()

        # CRITICAL: Use active_for_consumption profile, not default
        # The resource panel should show tools/prompts for the active profile
        active_profile_ids = config_manager.get_active_for_consumption_profile_ids(user_uuid)
        profile_id_to_load = None

        if active_profile_ids:
            profile_id_to_load = active_profile_ids[0]  # Primary active profile
            app_logger.info(f"Auto-loading active profile {profile_id_to_load} for /tools endpoint")
        else:
            # Fallback to default if no active profiles
            default_profile_id = config_manager.get_default_profile_id(user_uuid)
            if default_profile_id:
                profile_id_to_load = default_profile_id
                app_logger.info(f"No active profiles, auto-loading default profile {profile_id_to_load} for /tools endpoint")

        if not profile_id_to_load:
            return jsonify({"error": "No profiles configured"}), 400

        # Load profile into APP_STATE (without LLM validation for resource viewing)
        result = await configuration_service.switch_profile_context(profile_id_to_load, user_uuid, validate_llm=False)
        if result["status"] != "success":
            return jsonify({"error": f"Failed to load profile: {result['message']}"}), 400

    # Return structured tools (disabled flags already set by _regenerate_contexts)
    return jsonify(APP_STATE.get("structured_tools", {}))

@api_bp.route("/prompts")
async def get_prompts():
    """
    Returns the categorized list of MCP prompts with metadata only.
    """
    # Auto-load profile if not already loaded
    if not APP_STATE.get("mcp_client"):
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.core import configuration_service
        config_manager = get_config_manager()
        user_uuid = _get_user_uuid_from_request()

        # CRITICAL: Use active_for_consumption profile, not default
        # The resource panel should show prompts for the active profile
        active_profile_ids = config_manager.get_active_for_consumption_profile_ids(user_uuid)
        profile_id_to_load = None

        if active_profile_ids:
            profile_id_to_load = active_profile_ids[0]  # Primary active profile
            app_logger.info(f"Auto-loading active profile {profile_id_to_load} for /prompts endpoint")
        else:
            # Fallback to default if no active profiles
            default_profile_id = config_manager.get_default_profile_id(user_uuid)
            if default_profile_id:
                profile_id_to_load = default_profile_id
                app_logger.info(f"No active profiles, auto-loading default profile {profile_id_to_load} for /prompts endpoint")

        if not profile_id_to_load:
            return jsonify({"error": "No profiles configured"}), 400

        # Load profile into APP_STATE (without LLM validation for resource viewing)
        result = await configuration_service.switch_profile_context(profile_id_to_load, user_uuid, validate_llm=False)
        if result["status"] != "success":
            return jsonify({"error": f"Failed to load profile: {result['message']}"}), 400

    # Return structured prompts (disabled flags already set by _regenerate_contexts)
    return jsonify(APP_STATE.get("structured_prompts", {}))

@api_bp.route("/resources")
async def get_resources():
    """
    Returns a categorized list of MCP resources.
    This is a placeholder for future functionality.
    """
    # Auto-load profile if not already loaded
    if not APP_STATE.get("mcp_client"):
        from trusted_data_agent.core.config_manager import get_config_manager
        from trusted_data_agent.core import configuration_service
        config_manager = get_config_manager()
        user_uuid = _get_user_uuid_from_request()

        # CRITICAL: Use active_for_consumption profile, not default
        # The resource panel should show resources for the active profile
        active_profile_ids = config_manager.get_active_for_consumption_profile_ids(user_uuid)
        profile_id_to_load = None

        if active_profile_ids:
            profile_id_to_load = active_profile_ids[0]  # Primary active profile
            app_logger.info(f"Auto-loading active profile {profile_id_to_load} for /resources endpoint")
        else:
            # Fallback to default if no active profiles
            default_profile_id = config_manager.get_default_profile_id(user_uuid)
            if default_profile_id:
                profile_id_to_load = default_profile_id
                app_logger.info(f"No active profiles, auto-loading default profile {profile_id_to_load} for /resources endpoint")

        if not profile_id_to_load:
            return jsonify({"error": "No profiles configured"}), 400

        # Load profile into APP_STATE (without LLM validation for resource viewing)
        result = await configuration_service.switch_profile_context(profile_id_to_load, user_uuid, validate_llm=False)
        if result["status"] != "success":
            return jsonify({"error": f"Failed to load profile: {result['message']}"}), 400

    # Placeholder: Return empty dict until implemented
    return jsonify({})

@api_bp.route("/tool/toggle_status", methods=["POST"])
async def toggle_tool_status():
    """
    Enables or disables a tool.
    """
    data = await request.get_json()
    tool_name = data.get("name")
    is_disabled = data.get("disabled")

    if not tool_name or is_disabled is None:
        return jsonify({"status": "error", "message": "Missing 'name' or 'disabled' field."}), 400

    disabled_tools_set = set(APP_STATE.get("disabled_tools", []))

    if is_disabled:
        disabled_tools_set.add(tool_name)
        app_logger.info(f"Disabling tool '{tool_name}' for agent use.")
    else:
        disabled_tools_set.discard(tool_name)
        app_logger.info(f"Enabling tool '{tool_name}' for agent use.")

    APP_STATE["disabled_tools"] = list(disabled_tools_set)

    _regenerate_contexts()

    return jsonify({"status": "success", "message": f"Tool '{tool_name}' status updated."})

@api_bp.route("/prompt/toggle_status", methods=["POST"])
async def toggle_prompt_status():
    """
    Enables or disables a prompt.
    """
    data = await request.get_json()
    prompt_name = data.get("name")
    is_disabled = data.get("disabled")

    if not prompt_name or is_disabled is None:
        return jsonify({"status": "error", "message": "Missing 'name' or 'disabled' field."}), 400

    disabled_prompts_set = set(APP_STATE.get("disabled_prompts", []))

    if is_disabled:
        disabled_prompts_set.add(prompt_name)
        app_logger.info(f"Disabling prompt '{prompt_name}' for agent use.")
    else:
        disabled_prompts_set.discard(prompt_name)
        app_logger.info(f"Enabling prompt '{prompt_name}' for agent use.")

    APP_STATE["disabled_prompts"] = list(disabled_prompts_set)

    _regenerate_contexts()

    return jsonify({"status": "success", "message": f"Prompt '{prompt_name}' status updated."})

@api_bp.route("/app-settings", methods=["GET"])
async def get_app_settings():
    """
    Returns application-level settings that are relevant to the frontend.
    No authentication required for public settings.
    """
    return jsonify({
        "github_api_enabled": APP_CONFIG.GITHUB_API_ENABLED
    })

@api_bp.route("/prompt/<prompt_name>", methods=["GET"])
async def get_prompt_content(prompt_name):
    """
    Retrieves the content of a specific MCP prompt. For dynamic prompts
    with arguments, it renders them with placeholder values for preview.
    """
    mcp_client = APP_STATE.get("mcp_client")
    if not mcp_client:
        return jsonify({"error": "MCP client not configured."}), 400

    # Use server ID instead of name for session management
    server_id = APP_CONFIG.CURRENT_MCP_SERVER_ID
    if not server_id:
         return jsonify({"error": "MCP server ID not configured."}), 400

    try:
        prompt_info = _get_prompt_info(prompt_name)
        placeholder_args = {}

        if prompt_info and prompt_info.get("arguments"):
            app_logger.info(f"'{prompt_name}' is a dynamic prompt. Building placeholder arguments for preview.")
            for arg in prompt_info["arguments"]:
                arg_name = arg.get("name")
                if arg_name:
                    placeholder_args[arg_name] = f"<{arg_name}>"

        async with mcp_client.session(server_id) as temp_session:
            if placeholder_args:
                prompt_obj = await load_mcp_prompt(
                    temp_session, name=prompt_name, arguments=placeholder_args
                )
            else:
                prompt_obj = await temp_session.get_prompt(name=prompt_name)

        if not prompt_obj:
            return jsonify({"error": f"Prompt '{prompt_name}' not found."}), 404

        prompt_text = "Prompt content is not available."
        if isinstance(prompt_obj, str):
            prompt_text = prompt_obj
        elif (isinstance(prompt_obj, list) and len(prompt_obj) > 0 and hasattr(prompt_obj[0], 'content')):
             if isinstance(prompt_obj[0].content, str):
                 prompt_text = prompt_obj[0].content
             elif hasattr(prompt_obj[0].content, 'text'):
                 prompt_text = prompt_obj[0].content.text
        elif (hasattr(prompt_obj, 'messages') and
            isinstance(prompt_obj.messages, list) and
            len(prompt_obj.messages) > 0 and
            hasattr(prompt_obj.messages[0], 'content') and
            hasattr(prompt_obj.messages[0].content, 'text')):
            prompt_text = prompt_obj.messages[0].content.text
        elif hasattr(prompt_obj, 'text') and isinstance(prompt_obj.text, str):
            prompt_text = prompt_obj.text

        return jsonify({"name": prompt_name, "content": prompt_text})

    except Exception as e:
        root_exception = unwrap_exception(e)
        app_logger.error(f"Error fetching prompt content for '{prompt_name}': {root_exception}", exc_info=True)
        return jsonify({"error": "An unexpected error occurred while fetching the prompt."}), 500

@api_bp.route("/api/notifications/subscribe", methods=["GET"])
async def subscribe_notifications():
    """
    SSE endpoint for clients to receive real-time notifications.
    Includes a heartbeat to keep the connection alive.
    """
    user_uuid = request.args.get("user_uuid")
    if not user_uuid:
        app_logger.error("Missing user_uuid query parameter in notification subscription request.")
        abort(400, description="user_uuid query parameter is required.")

    pass  # User subscribed

    async def notification_generator():
        queue = asyncio.Queue()
        # Use a set for faster lookups
        queues_for_user = APP_STATE.setdefault("notification_queues", {}).setdefault(user_uuid, set())
        queues_for_user.add(queue)
        try:
            while True:
                try:
                    # Wait for a notification with a 20-second timeout
                    notification = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield PlanExecutor._format_sse(notification, "notification")
                except asyncio.TimeoutError:
                    # If timeout, send a heartbeat comment to keep the connection alive
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            app_logger.info(f"Notification subscription cancelled for user {user_uuid}.")
        finally:
            queues_for_user.remove(queue)
            # Clean up user entry if no more queues are associated with them
            if not queues_for_user:
                notification_queues = APP_STATE.get("notification_queues", {})
                if user_uuid in notification_queues:
                    del notification_queues[user_uuid]

    return Response(notification_generator(), mimetype="text/event-stream")

@api_bp.route("/rag/collections", methods=["GET"])
async def list_rag_collections():
    """Lists available ChromaDB collections with basic metadata and document counts."""
    try:
        retriever = APP_STATE.get('rag_retriever_instance')
        client = None
        if retriever and hasattr(retriever, 'client'):
            client = retriever.client
        else:
            # Fallback: attempt to open persistent client if RAG is enabled
            if APP_CONFIG.RAG_ENABLED:
                project_root = Path(__file__).resolve().parent.parent.parent
                persist_dir = project_root / '.chromadb_rag_cache'
                persist_dir.mkdir(exist_ok=True)
                client = chromadb.PersistentClient(path=str(persist_dir))
        if not client:
            return jsonify({"collections": []})
        raw_collections = client.list_collections()
        collections = []
        for col in raw_collections:
            name = getattr(col, 'name', None) or getattr(col, 'id', 'unknown')
            count = None
            metadata = {}
            try:
                c_obj = client.get_collection(name=name)
                count = c_obj.count()
                metadata = c_obj.metadata or {}
            except Exception as inner_e:
                app_logger.warning(f"Failed to inspect collection '{name}': {inner_e}")
            collections.append({"name": name, "count": count, "metadata": metadata})
        return jsonify({"collections": collections})
    except Exception as e:
        app_logger.error(f"Error listing RAG collections: {e}", exc_info=True)
        return jsonify({"error": "Failed to list collections"}), 500

@api_bp.route("/rag/collections/<int:collection_id>/rows", methods=["GET"])
async def get_collection_rows(collection_id):
    """Returns a sample or search results of rows from a ChromaDB collection.

    Query Parameters:
      limit (int): number of rows to return (default 25, max 100)
      q (str): optional search query; if provided runs a similarity query
      light (bool): if true, omits full_case_data from response for lighter payload
    """
    try:
        # Look up collection metadata by ID from database (not stale APP_STATE)
        from trusted_data_agent.core.collection_db import get_collection_db
        collection_db = get_collection_db()
        collection_meta = collection_db.get_collection_by_id(collection_id)
        
        if not collection_meta:
            return jsonify({"error": f"Collection with ID {collection_id} not found."}), 404
        
        collection_name = collection_meta["collection_name"]
        app_logger.info(f"RAG Inspection - Collection ID: {collection_id}, Name: {collection_meta.get('name')}, ChromaDB Name: {collection_name}")
        
        # Always try to get ChromaDB client, even if app is not configured
        # RAG collections can be inspected independently of MCP/LLM configuration
        client = None
        retriever = APP_STATE.get('rag_retriever_instance')
        
        if retriever and hasattr(retriever, 'client'):
            # Use existing retriever's client if available
            client = retriever.client
            app_logger.info(f"Using existing RAG retriever client")
        else:
            # Create direct client connection to ChromaDB
            # This allows RAG inspection even before app configuration
            try:
                # routes.py is at src/trusted_data_agent/api/routes.py
                # We need to go up 4 levels to get to project root
                project_root = Path(__file__).resolve().parent.parent.parent.parent
                persist_dir = project_root / '.chromadb_rag_cache'
                persist_dir.mkdir(exist_ok=True)
                
                # Create client
                client = chromadb.PersistentClient(path=str(persist_dir))
                
                # WORKAROUND: Force client initialization by listing collections immediately
                # This seems to help with ChromaDB 0.6+ telemetry initialization timing
                try:
                    _ = client.list_collections()
                except:
                    pass
                
                app_logger.info(f"Created direct ChromaDB client for RAG inspection (app not configured)")
                app_logger.info(f"ChromaDB persist directory: {persist_dir}")
                app_logger.info(f"Directory exists: {persist_dir.exists()}")
                if persist_dir.exists():
                    files = list(persist_dir.glob('*'))
                    app_logger.info(f"Files in persist_dir: {[f.name for f in files]}")
                
                # Note: We don't set the embedding function on the client itself.
                # Collections in ChromaDB 0.6+ store their own embedding function,
                # so we need to get the collection and it will use its stored embedding function.
            except Exception as e:
                app_logger.error(f"Failed to create ChromaDB client: {e}")
                return jsonify({
                    "error": "Failed to connect to RAG database",
                    "rows": [],
                    "total": 0,
                    "collection_name": collection_name
                }), 500
        
        if not client:
            return jsonify({
                "error": "RAG database not available",
                "rows": [],
                "total": 0,
                "collection_name": collection_name
            }), 500

        limit = request.args.get('limit', default=25, type=int)
        limit = max(1, min(limit, 200))  # Allow up to 200 rows per request
        offset = request.args.get('offset', default=0, type=int)
        offset = max(0, offset)
        query_text = request.args.get('q', default=None, type=str)
        light = request.args.get('light', default='true').lower() == 'true'

        try:
            # Try to get or create the collection
            # Use get_or_create to handle case where collection doesn't exist yet
            collection = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            count = collection.count()
            app_logger.info(f"Successfully retrieved collection '{collection_name}' with {count} documents")
        except Exception as e:
            app_logger.error(f"Failed to get ChromaDB collection '{collection_name}': {e}")
            
            # List available collections for debugging
            try:
                available_collections = client.list_collections()
                available_names = [str(col) for col in available_collections]
                app_logger.info(f"Available collections in ChromaDB: {available_names}")
                
                # If there's only one collection and it's not the one we're looking for,
                # this might be a naming mismatch - use the first available collection
                if len(available_collections) == 1 and collection_name == "default_collection":
                    actual_name = str(available_collections[0])
                    app_logger.info(f"Attempting to use actual collection '{actual_name}' instead of '{collection_name}'")
                    collection = client.get_collection(name=actual_name)
                    count = collection.count()
                    app_logger.info(f"Successfully retrieved fallback collection '{actual_name}' with {count} documents")
                    collection_name = actual_name  # Update for response
                else:
                    return jsonify({"error": f"ChromaDB collection '{collection_name}' not found. Available: {available_names}"}), 404
            except Exception as list_error:
                app_logger.error(f"Failed to list ChromaDB collections: {list_error}")
                return jsonify({"error": f"ChromaDB collection '{collection_name}' not found."}), 404

        rows = []
        total = 0
        
        # --- MODIFICATION START: Get user context for access filtering ---
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required. Please login."}), 401
        
        # Determine if we need to filter by user_uuid
        retriever = APP_STATE.get('rag_retriever_instance')
        from trusted_data_agent.agent.rag_access_context import RAGAccessContext
        
        where_filter = None
        if retriever:
            rag_context = RAGAccessContext(user_id=user_uuid, retriever=retriever)
            access_type = rag_context.get_access_type(collection_id)
            
            # For owned collections, filter to show only current user's cases
            if access_type == "owned":
                where_filter = {"user_uuid": {"$eq": user_uuid}}
        # --- MODIFICATION END ---
        
        if query_text and len(query_text) >= 3:
            # Similarity search path
            try:
                query_results = collection.query(
                    query_texts=[query_text], n_results=limit, include=["metadatas", "distances"], where=where_filter
                )
                if query_results and query_results.get("ids"):
                    total = len(query_results["ids"][0])
                    for i in range(total):
                        row_id = query_results["ids"][0][i]
                        meta = query_results["metadatas"][0][i]
                        distance = query_results["distances"][0][i]
                        similarity = 1 - distance
                        full_case_data = None
                        if not light:
                            try:
                                full_case_data = json.loads(meta.get("full_case_data", "{}"))
                            except json.JSONDecodeError:
                                full_case_data = None
                        rows.append({
                            "id": row_id,
                            "user_query": meta.get("user_query"),
                            "strategy_type": meta.get("strategy_type"),
                            "is_most_efficient": meta.get("is_most_efficient"),
                            "user_feedback_score": meta.get("user_feedback_score", 0),
                            "output_tokens": meta.get("output_tokens"),
                            "timestamp": meta.get("timestamp"),
                            "similarity_score": similarity,
                            "full_case_data": full_case_data,
                        })
            except Exception as qe:
                app_logger.warning(f"Query failed for collection '{collection_name}': {qe}")
        else:
            # Sampling path: attempt limited get; fallback to slice
            try:
                # ChromaDB doesn't always expose a limit param; retrieve all then slice
                all_results = collection.get(include=["metadatas"], where=where_filter)
                ids = all_results.get("ids", [])
                metas = all_results.get("metadatas", [])
                total = len(ids)
                sample_count = min(limit, total)
                for i in range(sample_count):
                    meta = metas[i]
                    full_case_data = None
                    if not light:
                        try:
                            full_case_data = json.loads(meta.get("full_case_data", "{}"))
                        except json.JSONDecodeError:
                            full_case_data = None
                    rows.append({
                        "id": ids[i],
                        "user_query": meta.get("user_query"),
                        "strategy_type": meta.get("strategy_type"),
                        "is_most_efficient": meta.get("is_most_efficient"),
                        "user_feedback_score": meta.get("user_feedback_score", 0),
                        "output_tokens": meta.get("output_tokens"),
                        "timestamp": meta.get("timestamp"),
                        "full_case_data": full_case_data,
                    })
            except Exception as ge:
                app_logger.error(f"Sampling failed for collection '{collection_name}': {ge}", exc_info=True)
        
        # Override feedback scores from cache for consistency (cache is source of truth after updates)
        retriever = APP_STATE.get('rag_retriever_instance')
        if retriever and hasattr(retriever, 'get_feedback_score'):
            for row in rows:
                case_id = row.get('id')
                if case_id:
                    cached_feedback = retriever.get_feedback_score(case_id)
                    if cached_feedback != row.get('user_feedback_score', 0):
                        app_logger.debug(f"Using cached feedback for {case_id}: {cached_feedback} (was {row.get('user_feedback_score', 0)})")
                        row['user_feedback_score'] = cached_feedback
        
        # Apply server-side sorting if requested
        sort_by = request.args.get('sort_by', default=None, type=str)
        sort_order = request.args.get('sort_order', default='asc', type=str)
        if sort_by and sort_by in ['id', 'user_query', 'strategy_type', 'user_feedback_score', 'output_tokens', 'timestamp', 'similarity_score']:
            reverse = sort_order.lower() == 'desc'
            try:
                rows.sort(key=lambda x: (x.get(sort_by) is None, x.get(sort_by)), reverse=reverse)
                app_logger.debug(f"Applied server-side sorting: {sort_by} {sort_order}")
            except Exception as e:
                app_logger.debug(f"Sorting failed: {e}")
        
        # Apply pagination: offset and limit
        paginated_rows = rows[offset:offset + limit]
        
        return jsonify({
            "rows": paginated_rows, 
            "total": total, 
            "query": query_text, 
            "collection_id": collection_id,
            "collection_name": collection_meta["name"]
        })
    except Exception as e:
        app_logger.error(f"Error getting collection rows for collection ID {collection_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to get collection rows"}), 500

# --- NEW ENDPOINT: Retrieve full case + associated turn summary ---
@api_bp.route("/rag/cases/<case_id>", methods=["GET"])
async def get_rag_case_details(case_id: str):
    """Returns full RAG case JSON and associated session turn summary.

    Matching logic:
      1. Load case file from rag/tda_rag_cases (case_<uuid>.json)
      2. Extract session_id, turn_id, task_id from case metadata
      3. Search session logs (tda_sessions/<user_uuid>/<session_id>.json)
         - First try match by turn_id
         - If not found, fallback to match by task_id
      4. Validate user has read access to the case's collection
    """
    try:
        # --- MODIFICATION START: Extract user context ---
        user_uuid = _get_user_uuid_from_request()
        if not user_uuid:
            return jsonify({"status": "error", "message": "Authentication required. Please login."}), 401
        # --- MODIFICATION END ---
        
        # Determine project root (4 levels up from this file)
        project_root = Path(__file__).resolve().parents[3]
        cases_dir = project_root / 'rag' / 'tda_rag_cases'
        if not cases_dir.exists():
            return jsonify({"error": "Cases directory not found."}), 500

        file_stem = case_id if case_id.startswith('case_') else f'case_{case_id}'
        
        # Search in flat structure first (legacy), then in collection subdirectories
        case_path = cases_dir / f"{file_stem}.json"
        if not case_path.exists():
            # Search all collection_* subdirectories
            found = False
            for collection_dir in cases_dir.glob("collection_*"):
                if collection_dir.is_dir():
                    potential_path = collection_dir / f"{file_stem}.json"
                    if potential_path.exists():
                        case_path = potential_path
                        found = True
                        break
            
            if not found:
                return jsonify({"error": f"Case '{file_stem}' not found."}), 404

        with open(case_path, 'r', encoding='utf-8') as f:
            case_data = json.load(f)

        metadata = case_data.get('metadata', {})
        session_id = metadata.get('session_id')
        turn_id = metadata.get('turn_id')
        task_id = metadata.get('task_id')
        
        # --- MODIFICATION START: Validate user access to case's collection ---
        from trusted_data_agent.agent.rag_access_context import RAGAccessContext
        collection_id = metadata.get('collection_id', 0)
        retriever = APP_STATE.get('rag_retriever_instance')
        
        if retriever:
            rag_context = RAGAccessContext(user_id=user_uuid, retriever=retriever)
            if not rag_context.validate_collection_access(collection_id, write=False):
                app_logger.warning(f"User {user_uuid} attempted to access case {case_id} from collection {collection_id} without read access")
                return jsonify({"error": "You do not have access to this case."}), 403
        # --- MODIFICATION END ---

        session_turn_summary = None
        join_method = None

        if session_id:
            sessions_root = project_root / 'tda_sessions'
            if sessions_root.exists():
                # Iterate all user_uuid directories to locate the session file
                for user_dir in sessions_root.iterdir():
                    if not user_dir.is_dir():
                        continue
                    session_file = user_dir / f"{session_id}.json"
                    if not session_file.exists():
                        continue
                    try:
                        with open(session_file, 'r', encoding='utf-8') as sf:
                            session_json = json.load(sf)
                        workflow_history = session_json.get('last_turn_data', {}).get('workflow_history', [])
                        # 1. Try by turn_id
                        if turn_id is not None:
                            for entry in workflow_history:
                                if entry.get('turn') == turn_id:
                                    session_turn_summary = entry
                                    join_method = 'turn_id'
                                    break
                        # 2. Fallback by task_id
                        if not session_turn_summary and task_id:
                            for entry in workflow_history:
                                if entry.get('task_id') == task_id:
                                    session_turn_summary = entry
                                    join_method = 'task_id'
                                    break
                    except Exception as se:
                        app_logger.warning(f"Failed reading session file '{session_file.name}': {se}")
                    break  # Stop after first matching session file directory

        return jsonify({
            "case": case_data,
            "session_turn_summary": session_turn_summary,
            "join_method": join_method
        })
    except Exception as e:
        app_logger.error(f"Error retrieving RAG case details for '{case_id}': {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve case details"}), 500

@api_bp.route("/sessions", methods=["GET"])
@require_auth
async def get_sessions(current_user):
    """Returns a list of all active chat sessions for the requesting user.
    
    Query Parameters:
        all_users (bool): If true and user has VIEW_ALL_SESSIONS feature, returns sessions from all users
    """
    user_uuid = current_user.id
    
    # Check if requesting all users' sessions
    all_users = request.args.get('all_users', 'false').lower() == 'true'
    
    if all_users:
        # Check if user has VIEW_ALL_SESSIONS feature
        from trusted_data_agent.auth.service import get_user_features
        from trusted_data_agent.auth.features import Feature
        
        user_features = get_user_features(user_uuid)
        if Feature.VIEW_ALL_SESSIONS not in user_features:
            return jsonify({"status": "error", "message": "Insufficient permissions to view all sessions"}), 403
        
        # Temporarily override filter setting to get all sessions
        from trusted_data_agent.core.config import APP_CONFIG
        original_filter = APP_CONFIG.SESSIONS_FILTER_BY_USER
        try:
            APP_CONFIG.SESSIONS_FILTER_BY_USER = False
            sessions = await session_manager.get_all_sessions(user_uuid=user_uuid)
        finally:
            APP_CONFIG.SESSIONS_FILTER_BY_USER = original_filter
    else:
        sessions = await session_manager.get_all_sessions(user_uuid=user_uuid)
    
    # Ensure profile_tags_used is included for each session
    for session in sessions:
        if 'profile_tags_used' not in session:
            session['profile_tags_used'] = []
    return jsonify(sessions)

@api_bp.route("/session/<session_id>", methods=["GET"])
@require_auth
async def get_session_history(current_user, session_id):
    """Retrieves the chat history and token counts for a specific session."""
    user_uuid = current_user.id

    session_data = await session_manager.get_session(user_uuid=user_uuid, session_id=session_id)
    if session_data:
        # --- MODIFICATION START: Extract feedback from workflow_history ---
        feedback_by_turn = {}
        workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])
        for turn in workflow_history:
            turn_num = turn.get("turn")
            feedback = turn.get("feedback")
            if turn_num is not None and feedback is not None:
                feedback_by_turn[turn_num] = feedback
        # --- MODIFICATION END ---
        
        response_data = {
            "history": session_data.get("session_history", []),
            "input_tokens": session_data.get("input_tokens", 0),
            "output_tokens": session_data.get("output_tokens", 0),
            "models_used": session_data.get("models_used", []),
            "profile_tags_used": session_data.get("profile_tags_used", []),
            "provider": session_data.get("provider"),
            "model": session_data.get("model"),
            "feedback_by_turn": feedback_by_turn  # Add feedback data
        }
        return jsonify(response_data)
    app_logger.warning(f"Session {session_id} not found for user {user_uuid}.")
    return jsonify({"error": "Session not found"}), 404

@api_bp.route("/api/session/<session_id>/rename", methods=["POST"])
@require_auth
async def rename_session(current_user, session_id: str):
    """Renames a specific session for the requesting user."""
    user_uuid = current_user.id
    data = await request.get_json()
    new_name = data.get("newName")

    if not new_name or not isinstance(new_name, str) or len(new_name.strip()) == 0:
        return jsonify({"status": "error", "message": "Invalid or empty 'newName' provided."}), 400

    session_data = await session_manager.get_session(user_uuid=user_uuid, session_id=session_id)
    if not session_data:
        app_logger.warning(f"Rename failed: Session {session_id} not found for user {user_uuid}.")
        return jsonify({"status": "error", "message": "Session not found or access denied."}), 404

    try:
        await session_manager.update_session_name(user_uuid, session_id, new_name.strip())
        app_logger.info(f"User {user_uuid} renamed session {session_id} to '{new_name.strip()}'.")
        return jsonify({"status": "success", "message": "Session renamed successfully."}), 200
    except Exception as e:
        app_logger.error(f"Error renaming session {session_id} for user {user_uuid}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "Failed to update session name on the server."}), 500

@api_bp.route("/api/session/<session_id>", methods=["DELETE"])
@require_auth
async def delete_session_endpoint(current_user, session_id: str):
    """Deletes a specific session for the requesting user."""
    user_uuid = current_user.id
    app_logger.info(f"DELETE request received for session {session_id} from user {user_uuid}.")

    try:
        success = await session_manager.delete_session(user_uuid, session_id)
        if success:
            app_logger.info(f"Successfully processed archive request for session {session_id} (user {user_uuid}).")
            return jsonify({"status": "success", "message": "Session archived successfully."}), 200
        else:
            app_logger.error(f"session_manager.delete_session reported failure for session {session_id} (user {user_uuid}).")
            return jsonify({"status": "error", "message": "Failed to archive session file on the server."}), 500
    except Exception as e:
        app_logger.error(f"Unexpected error during DELETE /api/session/{session_id} for user {user_uuid}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": "An unexpected server error occurred during archiving."}), 500

# --- MODIFICATION START: Add new endpoint for purging session memory ---
@api_bp.route("/api/session/<session_id>/purge_memory", methods=["POST"])
@require_auth
async def purge_memory(current_user, session_id: str):
    """Purges the agent's LLM context memory (`chat_object`) for a session."""
    user_uuid = current_user.id
    app_logger.info(f"Purge memory request for session {session_id}, user {user_uuid}")

    success = await session_manager.purge_session_memory(user_uuid, session_id)

    if success:
        app_logger.info(f"Agent memory purged successfully for session {session_id}, user {user_uuid}.")
        return jsonify({"status": "success", "message": "Agent memory purged."}), 200
    else:
        # This could be 404 (session not found) or 500 (save error), 404 is safer
        app_logger.warning(f"Failed to purge memory for session {session_id}, user {user_uuid}. Session may not exist or save failed.")
        return jsonify({"status": "error", "message": "Failed to purge session memory. Session not found or save error."}), 404
# --- MODIFICATION END ---

# --- MODIFICATION START: Add endpoints for /plan and /details ---
@api_bp.route("/api/session/<session_id>/turn/<int:turn_id>/plan", methods=["GET"])
@require_auth
async def get_turn_plan(current_user, session_id: str, turn_id: int):
    """Retrieves the original plan for a specific turn in a session."""
    user_uuid = current_user.id
    session_data = await session_manager.get_session(user_uuid=user_uuid, session_id=session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])
    if not isinstance(workflow_history, list) or turn_id <= 0 or turn_id > len(workflow_history):
        return jsonify({"error": f"Turn {turn_id} not found in session history."}), 404

    # Turns are 1-based for the user, but list index is 0-based
    turn_data = workflow_history[turn_id - 1]
    original_plan = turn_data.get("original_plan")

    if original_plan:
        return jsonify({"plan": original_plan})
    else:
        return jsonify({"error": f"Original plan not found for turn {turn_id}."}), 404

@api_bp.route("/api/session/<session_id>/turn/<int:turn_id>/details", methods=["GET"])
@require_auth
async def get_turn_details(current_user, session_id: str, turn_id: int):
    """Retrieves the full details (plan and trace) for a specific turn."""
    user_uuid = current_user.id
    session_data = await session_manager.get_session(user_uuid=user_uuid, session_id=session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])

    # Validate turn_id (workflow_history now exists for all profile types)
    if not isinstance(workflow_history, list) or turn_id <= 0 or turn_id > len(workflow_history):
        return jsonify({"error": f"Turn {turn_id} not found in session history."}), 404

    # --- MODIFICATION START: Prioritize turn-level data over session-level ---
    turn_data = workflow_history[turn_id - 1]
    # Create a copy to send, ensuring we don't modify the session data in memory
    turn_data_copy = copy.deepcopy(turn_data)

    # Fallback for provider: use turn-specific, otherwise session-specific
    if "provider" not in turn_data_copy:
        turn_data_copy["provider"] = session_data.get("provider")

    # Fallback for model: use turn-specific, otherwise session-specific
    if "model" not in turn_data_copy:
        turn_data_copy["model"] = session_data.get("model")

    # Return the copy with ensured model/provider info
    return jsonify(turn_data_copy)
    # --- MODIFICATION END ---


@api_bp.route("/api/session/<session_id>/turn/<int:turn_id>/query", methods=["GET"])
async def get_turn_query(session_id: str, turn_id: int):
    """Retrieves the original user query for a specific turn in a session."""
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        return jsonify({"status": "error", "message": "Authentication required. Please login."}), 401
    session_data = await session_manager.get_session(user_uuid=user_uuid, session_id=session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    workflow_history = session_data.get("last_turn_data", {}).get("workflow_history", [])
    if not isinstance(workflow_history, list) or turn_id <= 0 or turn_id > len(workflow_history):
        return jsonify({"error": f"Turn {turn_id} not found in session history."}), 404

    # Turns are 1-based for the user, but list index is 0-based
    turn_data = workflow_history[turn_id - 1]
    original_query = turn_data.get("user_query")

    if original_query:
        return jsonify({"query": original_query})
    else:
        # Should ideally always be present, but handle gracefully
        return jsonify({"error": f"Original query not found for turn {turn_id}."}), 404

@api_bp.route("/session", methods=["POST"])
async def new_session():
    """Creates a new chat session for the requesting user."""
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        return jsonify({"status": "error", "message": "Authentication required. Please login."}), 401

    # Get default profile to determine validation requirements
    from trusted_data_agent.core.config_manager import get_config_manager
    from trusted_data_agent.core import configuration_service
    config_manager = get_config_manager()
    default_profile_id = config_manager.get_default_profile_id(user_uuid)

    # Determine profile type to know what validation is needed
    default_profile = None
    profile_type = "tool_enabled"  # Default for backward compatibility

    if default_profile_id:
        profiles = config_manager.get_profiles(user_uuid)
        default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
        if default_profile:
            profile_type = default_profile.get("profile_type", "tool_enabled")

    # Validate based on profile type
    # LLM is always required, MCP only required for tool-enabled profiles
    needs_mcp = (profile_type == "tool_enabled")

    if not APP_STATE.get('llm') or (needs_mcp and not APP_CONFIG.MCP_SERVER_CONNECTED):
        # Try to initialize and validate with default profile
        if default_profile_id:
            app_logger.info(f"Validating {'LLM+MCP' if needs_mcp else 'LLM'} for session creation using profile {default_profile_id} (type: {profile_type})")
            result = await configuration_service.switch_profile_context(default_profile_id, user_uuid, validate_llm=True)
            app_logger.info(f"Validation result: {result}")
            if result["status"] != "success":
                error_msg = f"Failed to validate LLM configuration: {result['message']}"
                app_logger.warning(f"Returning 400 error to client: {error_msg}")
                return jsonify({"error": error_msg}), 400
        else:
            return jsonify({"error": "Application not configured. Please set LLM details in Config."}), 400

    # Double-check after validation attempt
    # LLM always required, MCP only for tool-enabled profiles
    if not APP_STATE.get('llm'):
        return jsonify({"error": "Application not configured. Please set LLM details in Config."}), 400

    if needs_mcp and not APP_CONFIG.MCP_SERVER_CONNECTED:
        return jsonify({"error": "Tool-enabled profile requires MCP server. Please configure MCP details in Config."}), 400

    try:
        loggers_to_purge = ["llm_conversation", "llm_conversation_history"]
        for logger_name in loggers_to_purge:
            logger = logging.getLogger(logger_name)
            for handler in logger.handlers[:]:
                if isinstance(handler, logging.FileHandler):
                    log_file_path = handler.baseFilename
                    handler.close()
                    logger.removeHandler(handler)
                    try:
                        with open(log_file_path, 'w'):
                            pass
                        app_logger.info(f"Successfully purged log file: {log_file_path}")
                        logger.addHandler(handler)
                    except Exception as clear_e:
                        app_logger.error(f"Failed to clear log file {log_file_path}: {clear_e}. Attempting to re-add handler anyway.")
                        logger.addHandler(handler)
    except Exception as e:
        app_logger.error(f"Failed to purge log files for new session: {e}", exc_info=True)


    data = await request.get_json()
    charting_intensity = data.get("charting_intensity", APP_CONFIG.DEFAULT_CHARTING_INTENSITY) if APP_CONFIG.CHARTING_ENABLED else "none"
    system_prompt_template = data.get("system_prompt")

    # Get profile tag and LLM config from DEFAULT profile (not first active)
    from trusted_data_agent.core.config_manager import get_config_manager
    from trusted_data_agent.core.config import set_user_mcp_server_id, set_user_mcp_client
    config_manager = get_config_manager()
    default_profile_id = config_manager.get_default_profile_id(user_uuid)
    profile_tag = None
    profile_provider = APP_CONFIG.CURRENT_PROVIDER  # Fallback to global config

    if default_profile_id:
        profiles = config_manager.get_profiles(user_uuid)
        default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
        if default_profile:
            profile_tag = default_profile.get("tag")

            # CRITICAL: Initialize MCP server ID AND CLIENT from profile for deterministic behavior
            # This ensures new sessions always use the profile's configured MCP server,
            # not leftover state from profile overrides in previous sessions
            profile_mcp_server_id = default_profile.get('mcpServerId')
            if profile_mcp_server_id:
                # Update server ID
                set_user_mcp_server_id(profile_mcp_server_id, user_uuid)

                # CRITICAL: Also update the MCP client to point to the pooled client for this server
                # Without this, APP_STATE['mcp_client'] still points to the previous server's client
                client_pool = APP_STATE.get('mcp_client_pool', {})
                pooled_client = client_pool.get(profile_mcp_server_id)

                if pooled_client:
                    set_user_mcp_client(pooled_client, user_uuid)
                    app_logger.info(f"✅ Initialized MCP from default profile: server_id={profile_mcp_server_id}, client=POOLED")
                else:
                    app_logger.warning(f"⚠️ MCP server {profile_mcp_server_id} not in connection pool (will initialize on first use)")
            else:
                app_logger.warning(f"⚠️ Default profile has no mcpServerId configured")

            # Get provider from the profile's LLM configuration
            llm_config_id = default_profile.get('llmConfigurationId')
            if llm_config_id:
                llm_configs = config_manager.get_llm_configurations(user_uuid)
                llm_config = next((cfg for cfg in llm_configs if cfg['id'] == llm_config_id), None)
                if llm_config:
                    profile_provider = llm_config.get('provider', APP_CONFIG.CURRENT_PROVIDER)
                    app_logger.info(f"Creating session with default profile: {default_profile.get('name')} (@{profile_tag}), provider: {profile_provider}")
                else:
                    app_logger.warning(f"LLM config {llm_config_id} not found, using global provider")
            else:
                app_logger.info(f"Creating session with default profile: {default_profile.get('name')} (@{profile_tag}), no LLM config (using global)")
        else:
            app_logger.warning(f"Default profile ID {default_profile_id} not found in profiles list")

    try:
        session_id = await session_manager.create_session(
            user_uuid=user_uuid,
            provider=profile_provider,
            llm_instance=APP_STATE.get('llm'),
            charting_intensity=charting_intensity,
            system_prompt_template=system_prompt_template,
            profile_tag=profile_tag
        )
        app_logger.info(f"Created new session: {session_id} for user {user_uuid} with profile_tag {profile_tag}.")
        return jsonify({
            "id": session_id, 
            "name": "New Chat", 
            "profile_tags_used": [],
            "models_used": []
        })
    except Exception as e:
        app_logger.error(f"Failed to create new session for user {user_uuid}: {e}", exc_info=True)
        return jsonify({"error": f"Failed to initialize a new chat session: {e}"}), 500

@api_bp.route("/models", methods=["POST"])
async def get_models():
    """Fetches the list of available models from the selected provider."""
    try:
        data = await request.get_json()
        provider = data.get("provider")
        credentials = { "listing_method": data.get("listing_method", "foundation_models") }
        if provider == 'Azure':
            credentials["azure_deployment_name"] = data.get("azure_deployment_name")
        elif provider == 'Amazon':
            credentials.update({
                "aws_access_key_id": data.get("aws_access_key_id"),
                "aws_secret_access_key": data.get("aws_secret_access_key"),
                "aws_region": data.get("aws_region")
            })
        elif provider == 'Friendli':
            credentials.update({
                "friendli_token": data.get("friendli_token"),
                "friendli_endpoint_url": data.get("friendli_endpoint_url")
            })
        elif provider == 'Ollama':
            # Support multiple host key formats for compatibility
            host_keys = ["ollama_host", "ollamaHost", "host"]
            ollama_host = next((data.get(key) for key in host_keys if data.get(key) is not None), None)
            credentials["host"] = ollama_host
        else:
            credentials["apiKey"] = data.get("apiKey")

        models = await llm_handler.list_models(provider, credentials)
        return jsonify({"status": "success", "models": models})
    except Exception as e:
        app_logger.error(f"Failed to list models for provider {provider}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 400

@api_bp.route("/system_prompt/<provider>/<path:model_name>", methods=["GET"])
async def get_default_system_prompt(provider, model_name):
    """Gets the system prompt for a given model using profile-based mapping."""
    try:
        from trusted_data_agent.agent.prompt_loader import get_prompt_loader
        from trusted_data_agent.agent.prompt_mapping import get_prompt_for_category
        from trusted_data_agent.config.configuration_manager import config_manager
        from trusted_data_agent.auth.middleware import get_current_user
        
        # Get user's UUID from session/auth
        current_user = await get_current_user()
        user_uuid = current_user.id if current_user else None
        
        # Get user's default profile to use their custom mappings
        profile_id = "__system_default__"  # Fallback
        if user_uuid:
            default_profile_id = config_manager.get_default_profile_id(user_uuid)
            if default_profile_id:
                profile_id = default_profile_id
                app_logger.info(f"Using profile {profile_id} for system prompt resolution")
        
        # Use prompt mapping system to resolve provider → prompt name
        prompt_name = get_prompt_for_category(
            profile_id=profile_id,
            category="master_system_prompts",
            subcategory=provider
        )
        
        if not prompt_name:
            # Fallback to default if mapping not found
            prompt_name = "MASTER_SYSTEM_PROMPT"
            app_logger.warning(f"No mapping found for provider {provider}, using default")
        
        app_logger.info(f"Resolved prompt for {provider}: {prompt_name} (profile: {profile_id})")
        
        # Load from database (gets active version of the mapped prompt)
        loader = get_prompt_loader()
        prompt_content = loader.get_prompt(prompt_name)
        
        return jsonify({"status": "success", "system_prompt": prompt_content})
    except Exception as e:
        app_logger.error(f"Failed to load system prompt for {provider}: {e}")
        # Fallback to old system if database fails
        base_prompt_template = str(PROVIDER_SYSTEM_PROMPTS.get(provider, PROVIDER_SYSTEM_PROMPTS["Google"]))
        return jsonify({"status": "success", "system_prompt": base_prompt_template})

@api_bp.route("/configure", methods=["POST"])
async def configure_services():
    """
    Configures and validates the core LLM and MCP services from the UI.
    This is now a thin, protected wrapper around the centralized configuration service.
    """
    data_from_ui = await request.get_json()
    if not data_from_ui:
        return jsonify({"status": "error", "message": "Request body must be a valid JSON."}), 400
    
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        return jsonify({"status": "error", "message": "Authentication required. Please login."}), 401

    # Check if credentials are nested (new format) or flat (old format)
    creds = data_from_ui.get("credentials", {})
    
    host_keys = ["ollama_host", "ollamaHost", "host"]
    ollama_host_value = next((creds.get(key) or data_from_ui.get(key) for key in host_keys if creds.get(key) or data_from_ui.get(key)), None)

    # Get MCP server config - support both nested and flat formats
    mcp_server_data = data_from_ui.get("mcp_server", {})
    
    service_config_data = {
        "provider": data_from_ui.get("provider"),
        "model": data_from_ui.get("model"),
        "tts_credentials_json": data_from_ui.get("tts_credentials_json"),
        "user_uuid": user_uuid,
        "credentials": {
            "apiKey": creds.get("apiKey") or data_from_ui.get("apiKey"),
            "aws_access_key_id": creds.get("aws_access_key_id") or data_from_ui.get("aws_access_key_id"),
            "aws_secret_access_key": creds.get("aws_secret_access_key") or data_from_ui.get("aws_secret_access_key"),
            "aws_region": creds.get("aws_region") or data_from_ui.get("aws_region"),
            "ollama_host": ollama_host_value,
            "azure_api_key": creds.get("azure_api_key") or data_from_ui.get("azure_api_key"),
            "azure_endpoint": creds.get("azure_endpoint") or data_from_ui.get("azure_endpoint"),
            "azure_deployment_name": creds.get("azure_deployment_name") or data_from_ui.get("azure_deployment_name"),
            "azure_api_version": creds.get("azure_api_version") or data_from_ui.get("azure_api_version"),
            "listing_method": creds.get("listing_method") or data_from_ui.get("listing_method", "foundation_models"),
            "friendli_token": creds.get("friendli_token") or data_from_ui.get("friendli_token"),
            "friendli_endpoint_url": creds.get("friendli_endpoint_url") or data_from_ui.get("friendli_endpoint_url")
        },
        "mcp_server": {
            "name": mcp_server_data.get("name") or data_from_ui.get("server_name"),
            "id": mcp_server_data.get("id") or data_from_ui.get("server_id"),
            "host": mcp_server_data.get("host") or data_from_ui.get("host"),
            "port": mcp_server_data.get("port") or data_from_ui.get("port"),
            "path": mcp_server_data.get("path") or data_from_ui.get("path")
        }
    }
    service_config_data["credentials"] = {k: v for k, v in service_config_data["credentials"].items() if v is not None}

    result = await configuration_service.setup_and_categorize_services(service_config_data)

    if result.get("status") == "success":
        return jsonify(result), 200
    else:
        return jsonify(result), 500

@api_bp.route("/test-mcp-connection", methods=["POST"])
async def test_mcp_connection():
    """
    Tests MCP server connectivity without performing full configuration.
    This allows users to validate individual MCP server settings before activation.
    Supports both SSE/HTTP and stdio transports.
    """
    data = await request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "Request body must be valid JSON."}), 400

    # Use server ID if provided, otherwise generate a temporary one for testing
    import uuid
    server_id = data.get("id") or f"temp-{uuid.uuid4()}"
    server_name = data.get("name", "Test Server")  # For logging only

    try:
        from trusted_data_agent.core.configuration_service import build_mcp_server_config

        # Build server config based on transport type
        app_logger.info(f"Testing MCP connection for '{server_name}' (ID: {server_id})")
        temp_server_configs = build_mcp_server_config(server_id, data)

        # Create temporary MCP client
        temp_mcp_client = MultiServerMCPClient(temp_server_configs)

        # Test connection by listing tools
        async with temp_mcp_client.session(server_id) as temp_session:
            tools_result = await temp_session.list_tools()
            tool_count = len(tools_result.tools) if hasattr(tools_result, 'tools') else 0

        app_logger.info(f"MCP connection test successful for '{server_name}' (ID: {server_id}). Found {tool_count} tools.")
        return jsonify({
            "status": "success",
            "message": f"Connection successful! Found {tool_count} tools.",
            "tool_count": tool_count
        }), 200

    except Exception as e:
        root_exception = unwrap_exception(e)
        error_message = ""

        transport_info = data.get('transport', {})
        transport_type = transport_info.get('type', 'sse')

        if isinstance(root_exception, (httpx.ConnectTimeout, httpx.ConnectError)):
            host = data.get("host")
            port = data.get("port")
            error_message = f"Connection failed: Cannot reach server at {host}:{port}. Please verify host and port."
        elif transport_type == 'stdio':
            error_message = f"Connection test failed: {str(root_exception)}. Check if command is installed and executable."
        else:
            error_message = f"Connection test failed: {str(root_exception)}"

        app_logger.error(f"MCP connection test failed for '{server_name}': {error_message}", exc_info=True)
        return jsonify({"status": "error", "message": error_message}), 500

@api_bp.route("/ask_stream", methods=["POST"])
async def ask_stream():
    """Handles the main chat conversation stream for ad-hoc user queries."""
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        async def error_gen():
            yield PlanExecutor._format_sse({"error": "Authentication required. Please login."}, "error")
        return Response(error_gen(), mimetype="text/event-stream")

    # Check consumption limits before allowing execution
    try:
        from trusted_data_agent.auth.consumption_enforcer import ConsumptionEnforcer
        from trusted_data_agent.auth.models import User
        from trusted_data_agent.auth.database import get_db_session
        
        # Check if user is admin - admins bypass consumption checks
        with get_db_session() as session:
            user = session.query(User).filter_by(id=user_uuid).first()
            is_admin = user.is_admin if user else False
        
        if not is_admin:
            enforcer = ConsumptionEnforcer(user_uuid)
            can_proceed, error_message = enforcer.can_execute_prompt()
            
            if not can_proceed:
                app_logger.warning(f"Consumption limit exceeded for user {user_uuid}: {error_message}")
                async def limit_error_gen():
                    yield PlanExecutor._format_sse({
                        "error": error_message,
                        "type": "rate_limit_exceeded"
                    }, "error")
                return Response(limit_error_gen(), mimetype="text/event-stream")
    except Exception as e:
        app_logger.error(f"Error checking consumption limits for user {user_uuid}: {e}", exc_info=True)
        # Fail open - allow execution if consumption check fails
        pass

    data = await request.get_json()
    user_input = data.get("message")
    session_id = data.get("session_id")
    disabled_history = data.get("disabled_history", False)
    source = data.get("source", "text")
    # --- MODIFICATION START: Receive optional plan and replay flag ---
    plan_to_execute = data.get("plan_to_execute") # Plan object or null
    is_replay = data.get("is_replay", False) # Boolean flag
    display_message = data.get("display_message") # Optional message for history
    # --- MODIFICATION END ---
    # --- MODIFICATION START: Receive optional profile override ---
    profile_override_id = data.get("profile_override_id") # Profile ID for temporary override
    # --- MODIFICATION END ---


    session_data = await session_manager.get_session(user_uuid=user_uuid, session_id=session_id)
    if not session_data:
        app_logger.error(f"ask_stream denied: Session {session_id} not found for user {user_uuid}.")
        async def error_gen():
            yield PlanExecutor._format_sse({"error": "Session not found or invalid."}, "error")
        return Response(error_gen(), mimetype="text/event-stream")

    # Get profile tag from active profile (NOT from override)
    # Note: If profile_override_id is set, the executor will handle updating the session
    # with the override profile only if it succeeds. We should not pre-emptively add
    # the override tag here, as it may fail during executor initialization.
    from trusted_data_agent.core.config_manager import get_config_manager
    config_manager = get_config_manager()

    # Determine active profile type to conditionally validate MCP requirement
    # Check profile override first, then fall back to default profile
    active_profile = None
    if profile_override_id:
        profiles = config_manager.get_profiles(user_uuid)
        active_profile = next((p for p in profiles if p.get("id") == profile_override_id), None)

    if not active_profile:
        # Get default profile
        default_profile_id = config_manager.get_default_profile_id(user_uuid)
        if default_profile_id:
            profiles = config_manager.get_profiles(user_uuid)
            active_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)

    # Get profile type (default to tool_enabled for backward compatibility)
    active_profile_type = active_profile.get("profile_type", "tool_enabled") if active_profile else "tool_enabled"

    # Only validate MCP tools for tool-enabled profiles
    # LLM-only profiles bypass planner/tools and execute directly
    if active_profile_type == "tool_enabled" and not APP_STATE.get('mcp_tools'):
        async def error_gen():
            yield PlanExecutor._format_sse({
                "error": "The agent is not fully configured. Please ensure the LLM and MCP server details are set correctly in the 'Config' tab before starting a chat."
            }, "error")
        return Response(error_gen(), mimetype="text/event-stream")

    # Validate knowledge collections for RAG focused profiles
    if active_profile_type == "rag_focused":
        knowledge_config = active_profile.get("knowledgeConfig", {}) if active_profile else {}
        knowledge_collections = knowledge_config.get("collections", [])

        if not knowledge_collections or len(knowledge_collections) == 0:
            app_logger.warning(f"RAG focused profile has no knowledge collections configured for user {user_uuid}")
            async def error_gen():
                yield PlanExecutor._format_sse({
                    "error": "RAG focused profiles require at least 1 knowledge collection. Please configure knowledge collections in the profile settings.",
                    "error_type": "missing_knowledge_collections"
                }, "error")
            return Response(error_gen(), mimetype="text/event-stream")

    # Always use default profile here - executor will update if override succeeds
    default_profile_id = config_manager.get_default_profile_id(user_uuid)
    if default_profile_id:
        profiles = config_manager.get_profiles(user_uuid)
        default_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)
        profile_tag = default_profile.get("tag") if default_profile else None
    else:
        profile_tag = None

    # Only update session if no profile override is active
    # If profile override is active, let executor handle the update after validation
    if not profile_override_id:
        await session_manager.update_models_used(user_uuid=user_uuid, session_id=session_id, provider=APP_CONFIG.CURRENT_PROVIDER, model=APP_CONFIG.CURRENT_MODEL, profile_tag=profile_tag)

    # --- MODIFICATION START: Generate task_id for interactive sessions ---
    task_id = generate_task_id()
    # --- MODIFICATION END ---

    active_tasks_key = f"{user_uuid}_{session_id}"
    active_tasks = APP_STATE.get("active_tasks", {})
    if active_tasks_key in active_tasks:
        existing_task = active_tasks.pop(active_tasks_key)
        if not existing_task.done():
            app_logger.warning(f"Cancelling previous active task for user {user_uuid}, session {session_id}.")
            existing_task.cancel()
            try:
                await asyncio.wait_for(existing_task, timeout=0.1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception as e:
                app_logger.error(f"Error during cancellation cleanup: {e}")

    async def stream_generator():
        queue = asyncio.Queue()

        # Store queue in APP_STATE for cancellation endpoint access
        active_tasks_key = f"{user_uuid}_{session_id}"
        active_queues = APP_STATE.setdefault("active_queues", {})
        active_queues[active_tasks_key] = queue

        async def event_handler(event_data, event_type):
            sse_event = PlanExecutor._format_sse(event_data, event_type)
            await queue.put(sse_event)

        # --- MODIFICATION START: Send initial task_start event ---
        # Send an initial event to the client with the task_id
        await queue.put(PlanExecutor._format_sse({"task_id": task_id}, "task_start"))
        # --- MODIFICATION END ---

        async def run_and_signal_completion():
            task = None
            try:
                # --- MODIFICATION START: Pass plan and replay flag to execution service ---
                task = asyncio.create_task(
                    execution_service.run_agent_execution(
                        user_uuid=user_uuid,
                        session_id=session_id,
                        user_input=user_input,
                        event_handler=event_handler,
                        disabled_history=disabled_history,
                        source=source,
                        plan_to_execute=plan_to_execute, # Pass the plan
                        is_replay=is_replay, # Pass the flag
                        display_message=display_message, # Pass the display message
                        task_id=task_id, # Pass the generated task_id
                        profile_override_id=profile_override_id # Pass the profile override
                    )
                )
                # --- MODIFICATION END ---
                APP_STATE.setdefault("active_tasks", {})[active_tasks_key] = task
                await task
            except asyncio.CancelledError:
                app_logger.info(f"Task for user {user_uuid}, session {session_id} was cancelled.")
                await event_handler({"message": "Execution stopped by user."}, "cancelled")
            except Exception as e:
                 app_logger.error(f"Error during task execution for user {user_uuid}, session {session_id}: {e}", exc_info=True)
                 await event_handler({"error": str(e)}, "error")
            finally:
                if active_tasks_key in APP_STATE.get("active_tasks", {}):
                    del APP_STATE["active_tasks"][active_tasks_key]
                # Clean up queue from APP_STATE
                active_queues = APP_STATE.get("active_queues", {})
                if active_tasks_key in active_queues:
                    del active_queues[active_tasks_key]
                await queue.put(None)

        asyncio.create_task(run_and_signal_completion())

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return Response(stream_generator(), mimetype="text/event-stream")

@api_bp.route("/invoke_prompt_stream", methods=["POST"])
async def invoke_prompt_stream():
    """
    Handles the direct invocation of a prompt from the UI.
    """
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        async def error_gen():
            yield PlanExecutor._format_sse({"error": "Authentication required. Please login."}, "error")
        return Response(error_gen(), mimetype="text/event-stream")

    # Check consumption limits before proceeding
    try:
        from trusted_data_agent.auth.consumption_enforcer import ConsumptionEnforcer
        from trusted_data_agent.auth.models import User
        from trusted_data_agent.auth.database import get_db_session
        
        # Check if user is admin (admins bypass consumption limits)
        with get_db_session() as session:
            user = session.query(User).filter_by(id=user_uuid).first()
            is_admin = user.is_admin if user else False
        
        if not is_admin:
            enforcer = ConsumptionEnforcer(user_uuid)
            can_proceed, error_message = enforcer.can_execute_prompt()
            
            if not can_proceed:
                app_logger.warning(f"Consumption limit exceeded (invoke_prompt) for user {user_uuid}: {error_message}")
                async def limit_error_gen():
                    yield PlanExecutor._format_sse({
                        "error": error_message,
                        "type": "rate_limit_exceeded"
                    }, "error")
                return Response(limit_error_gen(), mimetype="text/event-stream")
    except Exception as e:
        app_logger.error(f"Error checking consumption limits: {e}", exc_info=True)
        # Fail open: allow execution if enforcement check fails

    if not APP_STATE.get('mcp_tools'):
        async def error_gen():
            yield PlanExecutor._format_sse({
                "error": "The agent is not fully configured. Please ensure the LLM and MCP server details are set correctly in the 'Config' tab before invoking a prompt."
            }, "error")
        return Response(error_gen(), mimetype="text/event-stream")

    data = await request.get_json()
    session_id = data.get("session_id")
    prompt_name = data.get("prompt_name")
    arguments = data.get("arguments", {})
    disabled_history = data.get("disabled_history", False)
    source = data.get("source", "prompt_library")

    session_data = await session_manager.get_session(user_uuid=user_uuid, session_id=session_id)
    if not session_data:
        app_logger.error(f"invoke_prompt_stream denied: Session {session_id} not found for user {user_uuid}.")
        async def error_gen():
            yield PlanExecutor._format_sse({"error": "Session not found or invalid."}, "error")
        return Response(error_gen(), mimetype="text/event-stream")

    # Get active profile to check profile type
    from trusted_data_agent.core.config_manager import get_config_manager
    config_manager = get_config_manager()
    default_profile_id = config_manager.get_default_profile_id(user_uuid)
    active_profile = None
    if default_profile_id:
        profiles = config_manager.get_profiles(user_uuid)
        active_profile = next((p for p in profiles if p.get("id") == default_profile_id), None)

    # Get profile type (default to tool_enabled for backward compatibility)
    active_profile_type = active_profile.get("profile_type", "tool_enabled") if active_profile else "tool_enabled"

    # MCP prompt invocation is only for tool-enabled profiles
    if active_profile_type != "tool_enabled":
        app_logger.warning(f"MCP prompt invocation attempted with {active_profile_type} profile for user {user_uuid}")
        async def error_gen():
            yield PlanExecutor._format_sse({
                "error": "MCP prompts are only available for tool-enabled profiles. Please switch to a tool-enabled profile or use the chat interface.",
                "error_type": "invalid_profile_type"
            }, "error")
        return Response(error_gen(), mimetype="text/event-stream")

    # --- MODIFICATION START: Generate task_id for prompt invocations ---
    task_id = generate_task_id()
    # --- MODIFICATION END ---

    active_tasks_key = f"{user_uuid}_{session_id}"
    active_tasks = APP_STATE.get("active_tasks", {})
    if active_tasks_key in active_tasks:
        existing_task = active_tasks.pop(active_tasks_key)
        if not existing_task.done():
            app_logger.warning(f"Cancelling previous active task for user {user_uuid}, session {session_id} during prompt invocation.")
            existing_task.cancel()
            try:
                await asyncio.wait_for(existing_task, timeout=0.1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception as e:
                app_logger.error(f"Error during cancellation cleanup: {e}")

    async def stream_generator():
        queue = asyncio.Queue()

        # Store queue in APP_STATE for cancellation endpoint access
        active_tasks_key = f"{user_uuid}_{session_id}"
        active_queues = APP_STATE.setdefault("active_queues", {})
        active_queues[active_tasks_key] = queue

        async def event_handler(event_data, event_type):
            sse_event = PlanExecutor._format_sse(event_data, event_type)
            await queue.put(sse_event)

        async def run_and_signal_completion():
            task = None
            try:
                # Prompt invocation doesn't support replay currently
                # --- MODIFICATION START: Use f-string for user_input ---
                task = asyncio.create_task(
                    execution_service.run_agent_execution(
                        user_uuid=user_uuid,
                        session_id=session_id,
                        user_input=f"Executing prompt: {prompt_name}",
                        event_handler=event_handler,
                        active_prompt_name=prompt_name,
                # --- MODIFICATION END ---
                        prompt_arguments=arguments,
                        disabled_history=disabled_history,
                        source=source,
                        task_id=task_id # Pass the generated task_id
                        # plan_to_execute=None, is_replay=False
                    )
                )
                APP_STATE.setdefault("active_tasks", {})[active_tasks_key] = task
                await task
            except asyncio.CancelledError:
                app_logger.info(f"Prompt task for user {user_uuid}, session {session_id} was cancelled.")
                await event_handler({"message": "Execution stopped by user."}, "cancelled")
            except Exception as e:
                 app_logger.error(f"Error during prompt task execution for user {user_uuid}, session {session_id}: {e}", exc_info=True)
                 await event_handler({"error": str(e)}, "error")
            finally:
                if active_tasks_key in APP_STATE.get("active_tasks", {}):
                    del APP_STATE["active_tasks"][active_tasks_key]
                # Clean up queue from APP_STATE
                active_queues = APP_STATE.get("active_queues", {})
                if active_tasks_key in active_queues:
                    del active_queues[active_tasks_key]
                await queue.put(None)

        asyncio.create_task(run_and_signal_completion())

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return Response(stream_generator(), mimetype="text/event-stream")

@api_bp.route("/api/session/<session_id>/cancel_stream", methods=["POST"])
async def cancel_stream(session_id: str):
    """Cancels the active execution task for a given session."""
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        return jsonify({"status": "error", "message": "Authentication required. Please login."}), 401
    active_tasks_key = f"{user_uuid}_{session_id}"
    active_tasks = APP_STATE.get("active_tasks", {})
    task = active_tasks.get(active_tasks_key)

    if task and not task.done():
        app_logger.info(f"Received request to cancel task for user {user_uuid}, session {session_id}.")

        # Set cancellation flag for executor to check
        cancellation_flags = APP_STATE.setdefault("cancellation_flags", {})
        cancellation_flags[active_tasks_key] = True

        # Cancel the asyncio task
        task.cancel()

        # Send immediate SSE event to frontend to ensure UI updates
        # This happens even if task is stuck and doesn't acknowledge cancellation
        active_queues = APP_STATE.get("active_queues", {})
        queue = active_queues.get(active_tasks_key)
        if queue:
            try:
                from .executor import PlanExecutor
                sse_event = PlanExecutor._format_sse(
                    {"message": "Cancellation requested by user", "session_id": session_id},
                    "cancelled"
                )
                await queue.put(sse_event)
                app_logger.info(f"Sent immediate cancellation SSE event for session {session_id}")
            except Exception as e:
                app_logger.error(f"Failed to send SSE cancellation event: {e}")

        # Delayed cleanup to allow event propagation and task cancellation
        async def delayed_cleanup():
            await asyncio.sleep(2)
            if active_tasks_key in active_tasks:
                del active_tasks[active_tasks_key]
            cancellation_flags.pop(active_tasks_key, None)
            app_logger.info(f"Cleaned up cancelled task for session {session_id}")

        asyncio.create_task(delayed_cleanup())

        return jsonify({"status": "success", "message": "Cancellation request sent."}), 200
    elif task and task.done():
        app_logger.info(f"Cancellation request for user {user_uuid}, session {session_id} ignored: task already completed.")
        if active_tasks_key in active_tasks:
             del active_tasks[active_tasks_key]
        return jsonify({"status": "info", "message": "Task already completed."}), 200
    else:
        app_logger.warning(f"Cancellation request for user {user_uuid}, session {session_id} failed: No active task found.")
        return jsonify({"status": "error", "message": "No active task found for this session."}), 404

# --- MODIFICATION START: Add endpoint to toggle turn validity ---
@api_bp.route("/api/session/<session_id>/turn/<int:turn_id>/toggle_validity", methods=["POST"])
async def toggle_turn_validity_route(session_id: str, turn_id: int):
    """Toggles the validity of a specific turn."""
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        return jsonify({"status": "error", "message": "Authentication required. Please login."}), 401
    app_logger.info(f"Toggle validity request for session {session_id}, turn {turn_id}, user {user_uuid}")

    success = await session_manager.toggle_turn_validity(user_uuid, session_id, turn_id)

    if success:
        return jsonify({"status": "success", "message": f"Turn {turn_id} validity toggled."}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to toggle turn validity."}), 500
# --- MODIFICATION END ---

# --- MODIFICATION START: Add endpoint to update turn feedback ---
@api_bp.route("/api/session/<session_id>/turn/<int:turn_id>/feedback", methods=["POST"])
async def update_turn_feedback_route(session_id: str, turn_id: int):
    """Updates the feedback (upvote/downvote) for a specific turn."""
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        return jsonify({"status": "error", "message": "Authentication required. Please login."}), 401
    data = await request.get_json()
    vote = data.get("vote")  # Expected: 'up', 'down', or None
    
    app_logger.info(f"Feedback update request for session {session_id}, turn {turn_id}, user {user_uuid}: {vote}")

    success = await session_manager.update_turn_feedback(user_uuid, session_id, turn_id, vote)

    if success:
        return jsonify({"status": "success", "message": f"Turn {turn_id} feedback updated."}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to update turn feedback."}), 500
# --- MODIFICATION END ---

# --- MODIFICATION START: Add endpoint for direct RAG case feedback (works without session) ---
@api_bp.route("/api/rag/cases/<case_id>/feedback", methods=["POST"])
async def update_rag_case_feedback_route(case_id: str):
    """
    Updates the feedback (upvote/downvote) directly for a RAG case.
    This endpoint works independently of sessions and is used when updating feedback
    from the RAG collection view (e.g., when the session may no longer exist).
    
    Args:
        case_id: The case ID (with or without 'case_' prefix)
        vote: 'up', 'down', or None to clear
    """
    user_uuid = _get_user_uuid_from_request()
    if not user_uuid:
        return jsonify({"status": "error", "message": "Authentication required. Please login."}), 401
    
    data = await request.get_json()
    vote = data.get("vote")  # Expected: 'up', 'down', or None
    
    if vote not in ['up', 'down', None]:
        return jsonify({"status": "error", "message": "Invalid vote. Must be 'up', 'down', or None."}), 400
    
    app_logger.info(f"Direct RAG case feedback update request for case {case_id}, user {user_uuid}: {vote}")
    
    try:
        # Get the RAG retriever instance
        retriever = APP_STATE.get('rag_retriever_instance')
        if not retriever:
            return jsonify({"status": "error", "message": "RAG system not initialized."}), 500
        
        # --- MODIFICATION START: Validate user has access to case's collection ---
        from trusted_data_agent.agent.rag_access_context import RAGAccessContext
        
        # Load case metadata to get collection_id
        project_root = Path(__file__).resolve().parents[3]
        cases_dir = project_root / 'rag' / 'tda_rag_cases'
        file_stem = case_id if case_id.startswith('case_') else f'case_{case_id}'
        
        case_path = cases_dir / f"{file_stem}.json"
        if not case_path.exists():
            # Search in collection subdirectories
            for collection_dir in cases_dir.glob("collection_*"):
                if collection_dir.is_dir():
                    potential_path = collection_dir / f"{file_stem}.json"
                    if potential_path.exists():
                        case_path = potential_path
                        break
        
        if not case_path.exists():
            return jsonify({"status": "error", "message": f"Case '{file_stem}' not found."}), 404
        
        with open(case_path, 'r', encoding='utf-8') as f:
            case_data = json.load(f)
        
        collection_id = case_data.get('metadata', {}).get('collection_id', 0)
        
        # Validate access (user must own or be subscribed to the collection)
        rag_context = RAGAccessContext(user_id=user_uuid, retriever=retriever)
        if not rag_context.validate_collection_access(collection_id, write=False):
            app_logger.warning(f"User {user_uuid} attempted to update feedback for case {case_id} from collection {collection_id} without access")
            return jsonify({"status": "error", "message": "You do not have access to this case."}), 403
        # --- MODIFICATION END ---
        
        # Convert vote to feedback score
        feedback_score = 1 if vote == 'up' else -1 if vote == 'down' else 0
        
        # Update the case feedback directly (handles both JSON and ChromaDB updates)
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context
            success = await retriever.update_case_feedback(case_id, feedback_score)
        except RuntimeError:
            # No running loop, create new one
            success = await asyncio.new_event_loop().run_until_complete(
                retriever.update_case_feedback(case_id, feedback_score)
            )
        
        if success:
            action = "upvoted" if vote == 'up' else "downvoted" if vote == 'down' else "cleared"
            app_logger.info(f"Successfully {action} RAG case {case_id} by user {user_uuid}")
            
            # Check if the original session still exists (for warning purposes)
            session_warning = None
            case_metadata = None
            try:
                project_root = Path(__file__).resolve().parents[3]
                cases_dir = project_root / 'rag' / 'tda_rag_cases'
                file_stem = case_id if case_id.startswith('case_') else f'case_{case_id}'
                case_path = cases_dir / f"{file_stem}.json"
                
                # Search in collection directories if not found at root
                if not case_path.exists():
                    for collection_dir in cases_dir.glob("collection_*"):
                        if collection_dir.is_dir():
                            potential_path = collection_dir / f"{file_stem}.json"
                            if potential_path.exists():
                                case_path = potential_path
                                break
                
                if case_path.exists():
                    with open(case_path, 'r', encoding='utf-8') as f:
                        case_data = json.load(f)
                    case_metadata = case_data.get('metadata', {})
                    session_id = case_metadata.get('session_id')
                    
                    # Check if session file exists
                    if session_id:
                        sessions_root = project_root / 'tda_sessions'
                        session_found = False
                        if sessions_root.exists():
                            for user_dir in sessions_root.iterdir():
                                if user_dir.is_dir():
                                    session_file = user_dir / f"{session_id}.json"
                                    if session_file.exists():
                                        session_found = True
                                        break
                        
                        if not session_found:
                            session_warning = f"Note: Original session (ID: {session_id[:8]}...) no longer exists, but RAG case has been updated successfully."
                            app_logger.info(f"Session {session_id} not found for case {case_id}, but feedback updated anyway")
            except Exception as e:
                app_logger.debug(f"Could not check session existence: {e}")
            
            response_data = {
                "status": "success", 
                "message": f"Case {case_id} feedback {action}.",
                "case_id": case_id,
                "feedback_score": feedback_score
            }
            if session_warning:
                response_data["warning"] = session_warning
            
            return jsonify(response_data), 200
        else:
            app_logger.warning(f"Failed to update feedback for case {case_id}: update_case_feedback returned False")
            return jsonify({"status": "error", "message": f"Case {case_id} not found or failed to update."}), 404
    
    except Exception as e:
        app_logger.error(f"Error updating RAG case feedback for case {case_id}: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to update case feedback: {str(e)}"}), 500
# --- MODIFICATION END ---