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
    ALL_MODELS_UNLOCKED = False # If True, bypasses model certification checks, allowing all models from a provider to be used.
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
}

# Whitelists for models that are officially supported.
# The ALL_MODELS_UNLOCKED flag bypasses these checks.
CERTIFIED_GOOGLE_MODELS = ["gemini-2.0-flash"]
CERTIFIED_ANTHROPIC_MODELS = ["*claude-3-5-haiku-2024102*"]
CERTIFIED_AMAZON_MODELS = ["*nova-lite*"]
CERTIFIED_AMAZON_PROFILES = ["*nova-lite*"]
CERTIFIED_OLLAMA_MODELS = ["llama3.1:8b-instruct-q8_0"]
CERTIFIED_OPENAI_MODELS = ["*gpt-4o-mini"]
CERTIFIED_AZURE_MODELS = ["*gpt-4o*"]
CERTIFIED_FRIENDLI_MODELS = ["google/gemma-3-27b-it"]


# ==============================================================================
# USER CONFIGURATION HELPERS
# ==============================================================================
# Per-user runtime context removed - all configuration now stored in database


def get_user_provider(user_uuid: str = None) -> str:
    """
    Get current provider for user.
    
    Args:
        user_uuid: Optional user UUID (for compatibility, always uses global config)
        
    Returns:
        Provider name (e.g., "Google", "Anthropic")
    """
    return APP_CONFIG.CURRENT_PROVIDER
def set_user_provider(provider: str, user_uuid: str = None):
    """
    Set current provider for user.
    
    Args:
        provider: Provider name
        user_uuid: Optional user UUID (for compatibility, always uses global config)
    """
    APP_CONFIG.CURRENT_PROVIDER = provider


def get_user_model(user_uuid: str = None) -> str:
    """
    Get current model for user.
    
    Args:
        user_uuid: Optional user UUID (for compatibility, always uses global config)
        
    Returns:
        Model name (e.g., "gemini-2.0-flash", "claude-3-5-haiku")
    """
    return APP_CONFIG.CURRENT_MODEL


def set_user_model(model: str, user_uuid: str = None):
    """
    Set current model for user.
    
    Args:
        model: Model name
        user_uuid: Optional user UUID (for compatibility, always uses global config)
    """
    APP_CONFIG.CURRENT_MODEL = model


def get_user_mcp_server_id(user_uuid: str = None) -> str:
    """Get current MCP server ID for user."""
    return APP_CONFIG.CURRENT_MCP_SERVER_ID


def set_user_mcp_server_id(server_id: str, user_uuid: str = None):
    """Set current MCP server ID for user."""
    APP_CONFIG.CURRENT_MCP_SERVER_ID = server_id


def get_user_aws_region(user_uuid: str = None) -> str:
    """Get AWS region for user."""
    return APP_CONFIG.CURRENT_AWS_REGION


def set_user_aws_region(region: str, user_uuid: str = None):
    """Set AWS region for user."""
    APP_CONFIG.CURRENT_AWS_REGION = region


def get_user_azure_deployment_details(user_uuid: str = None) -> dict:
    """Get Azure deployment details for user."""
    return APP_CONFIG.CURRENT_AZURE_DEPLOYMENT_DETAILS


def set_user_azure_deployment_details(details: dict, user_uuid: str = None):
    """Set Azure deployment details for user."""
    APP_CONFIG.CURRENT_AZURE_DEPLOYMENT_DETAILS = details


def get_user_friendli_details(user_uuid: str = None) -> dict:
    """Get Friendli.ai details for user."""
    return APP_CONFIG.CURRENT_FRIENDLI_DETAILS


def set_user_friendli_details(details: dict, user_uuid: str = None):
    """Set Friendli.ai details for user."""
    APP_CONFIG.CURRENT_FRIENDLI_DETAILS = details


def get_user_model_provider_in_profile(user_uuid: str = None) -> str:
    """Get model provider in profile (for AWS Bedrock) for user."""
    return APP_CONFIG.CURRENT_MODEL_PROVIDER_IN_PROFILE


def set_user_model_provider_in_profile(provider: str, user_uuid: str = None):
    """Set model provider in profile (for AWS Bedrock) for user."""
    APP_CONFIG.CURRENT_MODEL_PROVIDER_IN_PROFILE = provider


def get_user_llm_instance(user_uuid: str = None):
    """
    Get LLM instance for user.
    
    Args:
        user_uuid: Optional user UUID (for compatibility, always uses global state)
        
    Returns:
        LLM client instance
    """
    return APP_STATE.get("llm")


def set_user_llm_instance(llm_instance, user_uuid: str = None):
    """
    Set LLM instance for user.
    
    Args:
        llm_instance: LLM client instance
        user_uuid: Optional user UUID (for compatibility, always uses global state)
    """
    APP_STATE["llm"] = llm_instance


def get_user_mcp_client(user_uuid: str = None):
    """
    Get MCP client for user.
    
    Args:
        user_uuid: Optional user UUID (for compatibility, always uses global state)
        
    Returns:
        MCP client instance
    """
    return APP_STATE.get("mcp_client")


def set_user_mcp_client(mcp_client, user_uuid: str = None):
    """
    Set MCP client for user.
    
    Args:
        mcp_client: MCP client instance
        user_uuid: Optional user UUID (for compatibility, always uses global state)
    """
    APP_STATE["mcp_client"] = mcp_client


def get_user_server_configs(user_uuid: str = None) -> dict:
    """Get MCP server configs for user."""
    return APP_STATE.get("server_configs", {})


def set_user_server_configs(server_configs: dict, user_uuid: str = None):
    """Set MCP server configs for user."""
    APP_STATE["server_configs"] = server_configs


# cleanup_inactive_user_contexts removed - no longer needed with database persistence