# src/trusted_data_agent/core/config.py
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

class AppConfig:
    """
    Holds static configuration settings for the application.
    These values are typically set at startup and rarely change during runtime.
    """
    # --- Feature Flags & Behavior ---
    GITHUB_API_ENABLED = False # If True, enables GitHub API calls to fetch star count. Default is False to avoid rate limiting during development.
    CHARTING_ENABLED = True # Master switch to enable or disable the agent's ability to generate charts.
    DEFAULT_CHARTING_INTENSITY = "medium" # Controls how proactively the agent suggests charts. Options: "none", "medium", "heavy".
    ALLOW_SYNTHESIS_FROM_HISTORY = True # If True, allows the planner to generate an answer directly from conversation history without using tools.
    VOICE_CONVERSATION_ENABLED = True # Master switch for the Text-to-Speech (TTS) feature.
    SUB_PROMPT_FORCE_SUMMARY = False # If True, forces sub-executors for prompts to generate their own final summary. Default is False.
    ENABLE_SQL_CONSOLIDATION_REWRITE = False # If True, enables an LLM-based plan rewrite rule to consolidate sequential SQL queries.
    GRANTED_PROMPTS_FOR_EFFICIENCY_REPLANNING = ["base_teradataQuery"] # A list of complex prompts that are exempt from the "Re-planning for Efficiency" optimization.
    CONDENSE_SYSTEMPROMPT_HISTORY = True # If True, sends a condensed list of tools/prompts in the system prompt for subsequent turns in a conversation to save tokens.
    
    # GLOBAL APPLICATION STATE (not per-user) - loaded from environment or global settings file
    ENABLE_MCP_CLASSIFICATION = os.environ.get('TDA_ENABLE_MCP_CLASSIFICATION', 'true').lower() == 'true' # If True, uses LLM to classify MCP tools/prompts into categories. If False, uses single categories ('All Tools', 'All Prompts', 'All Resources') for faster configuration. This is a GLOBAL setting affecting all users.


    # --- Connection & Model State ---
    SERVICES_CONFIGURED = False # Master flag indicating if the core services (LLM, MCP) have been successfully configured.
    ACTIVE_PROVIDER = None
    ACTIVE_MODEL = None
    MCP_SERVER_CONNECTED = False # Runtime flag indicating if a connection to the MCP server is active.
    CHART_MCP_CONNECTED = False # Runtime flag indicating if a connection to the Charting server is active.
    CURRENT_PROVIDER = None # Stores the name of the currently configured LLM provider (e.g., "Google").
    CURRENT_MODEL = None # Stores the name of the currently configured LLM model (e.g., "gemini-1.5-flash").
    CURRENT_MCP_SERVER_ID = None # Stores the unique ID of the active MCP server (decoupled from name).
    CURRENT_AWS_REGION = None # Stores the AWS region, used specifically for the "Amazon" provider.
    CURRENT_AZURE_DEPLOYMENT_DETAILS = None # Stores Azure-specific details {endpoint, deployment_name, api_version}.
    
    # --- Profile Classification State ---
    CURRENT_PROFILE_ID = None # ID of the currently active profile
    CURRENT_PROFILE_CLASSIFICATION_MODE = None # Classification mode of current profile: 'light' or 'full'
    CURRENT_FRIENDLI_DETAILS = None # Stores Friendli.ai specific details {token, endpoint_url}.
    CURRENT_MODEL_PROVIDER_IN_PROFILE = None # For Amazon Bedrock, stores the model provider if using an inference profile ARN.

    # --- LLM & Agent Configuration ---
    # MCP_SYSTEM_NAME is now read dynamically from tda_config.json and global_parameters table
    LLM_API_MAX_RETRIES = 5 # The maximum number of times to retry a failed LLM API call.
    LLM_API_BASE_DELAY = 2 # The base delay in seconds for exponential backoff on API retries.
    CONTEXT_DISTILLATION_MAX_ROWS = 500 # The maximum number of rows from a tool's result to include in the LLM context.
    CONTEXT_DISTILLATION_MAX_CHARS = 10000 # The maximum number of characters from a tool's result to include in the LLM context.
    DETAILED_DESCRIPTION_THRESHOLD = 200 # A heuristic character count for the PlanExecutor to distinguish between a generic vs. a detailed task description from the planner.
    SQL_OPTIMIZATION_PROMPTS = []
    SQL_OPTIMIZATION_TOOLS = ["base_readQuery"]

    # RAG Configuration
    RAG_ENABLED = True
    RAG_REFRESH_ON_STARTUP = True # If True, vector store is refreshed on startup. If False, it uses cache until manually refreshed.
    RAG_CASES_DIR = "rag/tda_rag_cases"
    RAG_PERSIST_DIR = ".chromadb_rag_cache"
    RAG_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    RAG_NUM_EXAMPLES = 3 # Total number of few-shot examples to retrieve across all active collections
    RAG_DEFAULT_COLLECTION_NAME = "default_collection" # ChromaDB collection name for default collection (ID 0)
    
    # Knowledge Repository Configuration (Knowledge Repositories = Domain Knowledge RAG)
    KNOWLEDGE_RAG_ENABLED = True # Master switch for knowledge repository retrieval during planning
    KNOWLEDGE_RAG_NUM_DOCS = 3 # Number of knowledge documents to retrieve per planning call
    KNOWLEDGE_MIN_RELEVANCE_SCORE = 0.30  # Lowered for testing - may need better embeddings # Minimum similarity score for knowledge document retrieval (0.0-1.0)
    KNOWLEDGE_MAX_TOKENS = 2000 # Maximum tokens for all knowledge context combined
    KNOWLEDGE_RERANKING_ENABLED = False # Global default for LLM reranking (can be overridden per collection in profiles)
    
    # Session & Analytics Configuration
    SESSIONS_FILTER_BY_USER = os.environ.get('TDA_SESSIONS_FILTER_BY_USER', 'true').lower() == 'true' # If True, execution dashboard shows only current user's sessions. If False, shows all sessions. Note: User tier always filtered, Developer+ can override.


    # --- Initial State Configuration ---
    # Note: INITIALLY_DISABLED_PROMPTS and INITIALLY_DISABLED_TOOLS have been moved to tda_config.json
    # Each MCP server configuration now contains "initially_disabled_tools" and "initially_disabled_prompts" arrays
    # Use config_manager.get_initially_disabled_tools() and config_manager.get_initially_disabled_prompts() to access them

    # --- Tool & Argument Parsing Logic ---
    TOOL_SCOPE_HIERARCHY = [
        ('column', {'database_name', 'object_name', 'column_name'}),
        ('table', {'database_name', 'object_name'}),
        ('database', {'database_name'}),
    ]
    ARGUMENT_SYNONYM_MAP = {
        'database_name': {
            'database_name', 'db_name', 'DatabaseName'
        },
        'object_name':   {
            'table_name', 'tablename', 'TableName',
            'object_name', 'obj_name', 'ObjectName', 'objectname',
            'view_name', 'viewname', 'ViewName'
        },
        'column_name':   {
            'column_name', 'col_name', 'ColumnName'
        },
    }

APP_CONFIG = AppConfig()

APP_STATE = {
    # Live client instances and server configurations
    "llm": None, 
    "mcp_client": None, 
    "server_configs": {},

    # Raw tool/prompt definitions loaded from the MCP server
    "mcp_tools": {}, 
    "mcp_prompts": {}, 
    "mcp_charts": {},

    # Processed and categorized structures for UI display
    "structured_tools": {}, 
    "structured_prompts": {}, 
    "structured_resources": {}, 
    "structured_charts": {},

    # Cache for inferred tool operational scopes (e.g., 'table', 'column')
    "tool_scopes": {},

    # Formatted context strings injected into LLM prompts
    "tools_context": "--- No Tools Available ---", 
    "prompts_context": "--- No Prompts Available ---", 
    "charts_context": "--- No Charts Available ---",
    "constraints_context": "",

    # Runtime lists of currently disabled capabilities
    # These are populated from tda_config.json at startup via config_manager
    "disabled_prompts": [],
    "disabled_tools": [],

    # Validated license information
    "license_info": None,

    # Asynchronous task tracking for the REST API
    "background_tasks": {},
    
    # --- MODIFICATION START: Add RAG queue and instance placeholder ---
    # Asynchronous RAG processing queue and singleton instance
    "rag_processing_queue": asyncio.Queue(),
    "rag_retriever_instance": None,
    # RAG collections configuration: list of collection metadata
    # Each collection: {id, name, collection_name, mcp_server_id, enabled, created_at, description}
    "rag_collections": [],
    # --- MODIFICATION END ---

    # Concurrency lock for the configuration process
    "configuration_lock": asyncio.Lock(),

    # === CACHING LAYER (Performance Optimization) ===
    # Cache MCP tool/prompt/resource schemas by server_id (5 minute TTL)
    "mcp_tool_schema_cache": {},  # {server_id: {tools, prompts, resources, timestamp, tool_count}}

    # Connection pooling for MCP clients (keyed by server_id)
    "mcp_client_pool": {},  # {server_id: MultiServerMCPClient instance}

    # LLM instance pooling by (provider, model, credentials_hash, user_uuid)
    "llm_instance_pool": {},  # {pool_key: llm_instance}
}

# Note: Recommended models are now stored in the database (recommended_models table)
# and bootstrapped from tda_config.json. See auth/database.py:_bootstrap_recommended_models()

# ==============================================================================
# USER CONFIGURATION HELPERS
# ==============================================================================
# Per-user runtime context removed - all configuration now stored in database


def get_user_provider(user_uuid: str) -> str:
    """
    Get current provider for user.

    Args:
        user_uuid: User UUID (required)

    Returns:
        Provider name (e.g., "Google", "Anthropic")

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_provider")
    return APP_STATE.get("current_provider_by_user", {}).get(user_uuid)

def set_user_provider(provider: str, user_uuid: str):
    """
    Set current provider for user.

    Args:
        provider: Provider name
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_provider")
    if "current_provider_by_user" not in APP_STATE:
        APP_STATE["current_provider_by_user"] = {}
    APP_STATE["current_provider_by_user"][user_uuid] = provider
    # Also update APP_CONFIG for backwards compatibility with status checks
    APP_CONFIG.CURRENT_PROVIDER = provider


def get_user_model(user_uuid: str) -> str:
    """
    Get current model for user.

    Args:
        user_uuid: User UUID (required)

    Returns:
        Model name (e.g., "gemini-2.5-flash", "claude-3-5-haiku")

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_model")
    return APP_STATE.get("current_model_by_user", {}).get(user_uuid)


def set_user_model(model: str, user_uuid: str):
    """
    Set current model for user.

    Args:
        model: Model name
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_model")
    if "current_model_by_user" not in APP_STATE:
        APP_STATE["current_model_by_user"] = {}
    APP_STATE["current_model_by_user"][user_uuid] = model
    # Also update APP_CONFIG for backwards compatibility with status checks
    APP_CONFIG.CURRENT_MODEL = model


def get_user_mcp_server_id(user_uuid: str) -> str:
    """
    Get current MCP server ID for user.

    Validates that the server ID actually exists in the MCP client.
    If invalid, automatically falls back to the first available server.

    Args:
        user_uuid: User UUID (required)

    Returns:
        MCP server ID

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_mcp_server_id")

    server_id = APP_STATE.get("current_server_id_by_user", {}).get(user_uuid)

    # VALIDATION: Ensure the server ID actually exists in the MCP client
    if server_id:
        mcp_client = APP_STATE.get('mcp_client')
        if mcp_client:
            try:
                # Check if server exists in MCP client's connections
                if server_id not in mcp_client.connections:
                    import logging
                    logger = logging.getLogger("quart.app")
                    available_servers = list(mcp_client.connections.keys())
                    logger.error(
                        f"⚠️ STALE MCP SERVER ID DETECTED: Profile references server '{server_id}' which no longer exists. "
                        f"Available servers: {available_servers}"
                    )

                    # FALLBACK: Use first available server
                    if available_servers:
                        fallback_server = available_servers[0]
                        logger.warning(f"🔄 Auto-correcting to available server: {fallback_server}")
                        # Update the stored value to prevent repeated errors
                        APP_STATE["current_server_id_by_user"][user_uuid] = fallback_server
                        return fallback_server
                    else:
                        logger.error("❌ No MCP servers available!")
                        return None
            except Exception as e:
                import logging
                logger = logging.getLogger("quart.app")
                logger.warning(f"Failed to validate MCP server ID: {e}")

    return server_id


def set_user_mcp_server_id(server_id: str, user_uuid: str):
    """
    Set current MCP server ID for user.

    Args:
        server_id: MCP server ID
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_mcp_server_id")
    if "current_server_id_by_user" not in APP_STATE:
        APP_STATE["current_server_id_by_user"] = {}
    APP_STATE["current_server_id_by_user"][user_uuid] = server_id
    # Also update APP_CONFIG for backwards compatibility with status checks
    APP_CONFIG.CURRENT_MCP_SERVER_ID = server_id


def get_user_aws_region(user_uuid: str) -> str:
    """
    Get AWS region for user.

    Args:
        user_uuid: User UUID (required)

    Returns:
        AWS region

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_aws_region")
    return APP_STATE.get("current_aws_region_by_user", {}).get(user_uuid)


def set_user_aws_region(region: str, user_uuid: str):
    """
    Set AWS region for user.

    Args:
        region: AWS region
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_aws_region")
    if "current_aws_region_by_user" not in APP_STATE:
        APP_STATE["current_aws_region_by_user"] = {}
    APP_STATE["current_aws_region_by_user"][user_uuid] = region
    # Also update APP_CONFIG for backwards compatibility
    APP_CONFIG.CURRENT_AWS_REGION = region


def get_user_azure_deployment_details(user_uuid: str) -> dict:
    """
    Get Azure deployment details for user.

    Args:
        user_uuid: User UUID (required)

    Returns:
        Azure deployment details dict

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_azure_deployment_details")
    return APP_STATE.get("current_azure_details_by_user", {}).get(user_uuid)


def set_user_azure_deployment_details(details: dict, user_uuid: str):
    """
    Set Azure deployment details for user.

    Args:
        details: Azure deployment details dict
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_azure_deployment_details")
    if "current_azure_details_by_user" not in APP_STATE:
        APP_STATE["current_azure_details_by_user"] = {}
    APP_STATE["current_azure_details_by_user"][user_uuid] = details
    # Also update APP_CONFIG for backwards compatibility
    APP_CONFIG.CURRENT_AZURE_DEPLOYMENT_DETAILS = details


def get_user_friendli_details(user_uuid: str) -> dict:
    """
    Get Friendli.ai details for user.

    Args:
        user_uuid: User UUID (required)

    Returns:
        Friendli.ai details dict

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_friendli_details")
    return APP_STATE.get("current_friendli_details_by_user", {}).get(user_uuid)


def set_user_friendli_details(details: dict, user_uuid: str):
    """
    Set Friendli.ai details for user.

    Args:
        details: Friendli.ai details dict
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_friendli_details")
    if "current_friendli_details_by_user" not in APP_STATE:
        APP_STATE["current_friendli_details_by_user"] = {}
    APP_STATE["current_friendli_details_by_user"][user_uuid] = details
    # Also update APP_CONFIG for backwards compatibility
    APP_CONFIG.CURRENT_FRIENDLI_DETAILS = details


def get_user_model_provider_in_profile(user_uuid: str) -> str:
    """
    Get model provider in profile (for AWS Bedrock) for user.

    Args:
        user_uuid: User UUID (required)

    Returns:
        Model provider string

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_model_provider_in_profile")
    return APP_STATE.get("current_model_provider_by_user", {}).get(user_uuid)


def set_user_model_provider_in_profile(provider: str, user_uuid: str):
    """
    Set model provider in profile (for AWS Bedrock) for user.

    Args:
        provider: Model provider string
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_model_provider_in_profile")
    if "current_model_provider_by_user" not in APP_STATE:
        APP_STATE["current_model_provider_by_user"] = {}
    APP_STATE["current_model_provider_by_user"][user_uuid] = provider
    # Also update APP_CONFIG for backwards compatibility
    APP_CONFIG.CURRENT_MODEL_PROVIDER_IN_PROFILE = provider


def get_user_llm_instance(user_uuid: str):
    """
    Get LLM instance for user.

    Args:
        user_uuid: User UUID (required)

    Returns:
        LLM client instance

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_llm_instance")
    return APP_STATE.get("llm_by_user", {}).get(user_uuid)


def set_user_llm_instance(llm_instance, user_uuid: str):
    """
    Set LLM instance for user.

    Args:
        llm_instance: LLM client instance
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_llm_instance")
    if "llm_by_user" not in APP_STATE:
        APP_STATE["llm_by_user"] = {}
    APP_STATE["llm_by_user"][user_uuid] = llm_instance
    # Also update global APP_STATE for backwards compatibility
    APP_STATE["llm"] = llm_instance


def get_user_mcp_client(user_uuid: str):
    """
    Get MCP client for user.

    Args:
        user_uuid: User UUID (required)

    Returns:
        MCP client instance

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_mcp_client")
    return APP_STATE.get("mcp_clients", {}).get(user_uuid)


def set_user_mcp_client(mcp_client, user_uuid: str):
    """
    Set MCP client for user.

    Args:
        mcp_client: MCP client instance
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_mcp_client")
    if "mcp_clients" not in APP_STATE:
        APP_STATE["mcp_clients"] = {}
    APP_STATE["mcp_clients"][user_uuid] = mcp_client
    # Also update global APP_STATE for backwards compatibility
    APP_STATE["mcp_client"] = mcp_client


def get_user_server_configs(user_uuid: str) -> dict:
    """
    Get MCP server configs for user.

    Args:
        user_uuid: User UUID (required)

    Returns:
        Server configs dict

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for get_user_server_configs")
    return APP_STATE.get("server_configs_by_user", {}).get(user_uuid, {})


def set_user_server_configs(server_configs: dict, user_uuid: str):
    """
    Set MCP server configs for user.

    Args:
        server_configs: Server configs dict
        user_uuid: User UUID (required)

    Raises:
        ValueError: If user_uuid is not provided
    """
    if not user_uuid:
        raise ValueError("user_uuid is required for set_user_server_configs")
    if "server_configs_by_user" not in APP_STATE:
        APP_STATE["server_configs_by_user"] = {}
    APP_STATE["server_configs_by_user"][user_uuid] = server_configs
    # Also update global APP_STATE for backwards compatibility
    APP_STATE["server_configs"] = server_configs


# cleanup_inactive_user_contexts removed - no longer needed with database persistence


def get_llm_pool_key(provider: str, model: str, credentials: dict, user_uuid: str) -> str:
    """
    Generate cache key for LLM instance pooling.

    Args:
        provider: LLM provider name (e.g., 'google', 'anthropic')
        model: Model identifier (e.g., 'gemini-2.5-flash')
        credentials: Credentials dictionary
        user_uuid: User UUID for isolation

    Returns:
        Cache key string in format: provider:model:cred_hash:user_uuid
    """
    import hashlib
    import json

    # Hash credentials to avoid storing sensitive data in keys
    cred_str = json.dumps({k: v for k, v in credentials.items() if v}, sort_keys=True)
    cred_hash = hashlib.sha256(cred_str.encode()).hexdigest()[:16]

    # Include user_uuid for per-user isolation
    return f"{provider}:{model}:{cred_hash}:{user_uuid}"


def clear_mcp_server_cache(server_id: str):
    """
    Clear all cached data for a specific MCP server.
    Call this when MCP server configuration changes.

    This clears:
    - Tool schema cache (tools, prompts, resources)
    - Connection pool (MCP client instances)

    Args:
        server_id: MCP server ID to clear caches for
    """
    import logging
    logger = logging.getLogger("quart.app")

    # Clear tool schema cache
    schema_cache = APP_STATE.get('mcp_tool_schema_cache', {})
    if server_id in schema_cache:
        del schema_cache[server_id]
        logger.info(f"Cleared tool schema cache for MCP server {server_id}")

    # Clear connection pool
    client_pool = APP_STATE.get('mcp_client_pool', {})
    if server_id in client_pool:
        del client_pool[server_id]
        logger.info(f"Cleared pooled MCP client for server {server_id}")