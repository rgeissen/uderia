# src/trusted_data_agent/main.py
from dotenv import load_dotenv
load_dotenv()
import asyncio
import os
import sys
import logging
import shutil
import argparse

# --- MODIFICATION START: Import Response from Quart ---
# Required if you add test routes later, good practice to have it
from quart import Quart, Response
# --- MODIFICATION END ---
from quart_cors import cors
import hypercorn.asyncio
from hypercorn.config import Config

os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["TOKENIZERS_PARALLELISM"] = "false"  # Silence tokenizers warnings

# --- Logging Setup (from your original file) ---
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(script_dir))
LOG_DIR = os.path.join(project_root, "logs")

if os.path.exists(LOG_DIR): shutil.rmtree(LOG_DIR)
os.makedirs(LOG_DIR)

class SseConnectionFilter(logging.Filter):
    def filter(self, record):
        is_validation_error = "Failed to validate notification" in record.getMessage()
        is_sse_connection_method = "sse/connection" in record.getMessage()
        return not (is_validation_error and is_sse_connection_method)

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
handler.addFilter(SseConnectionFilter())

root_logger = logging.getLogger()
root_logger.handlers.clear()
root_logger.addHandler(handler)
# --- MODIFICATION START: Set Root Logger Level to INFO ---
root_logger.setLevel(logging.INFO)
# root_logger.setLevel(logging.DEBUG)
# --- MODIFICATION END ---

# Silence verbose third-party loggers
logging.getLogger('chromadb.telemetry.product.posthog').setLevel(logging.WARNING)
logging.getLogger('sentence_transformers').setLevel(logging.WARNING)
logging.getLogger('rag_template_manager').setLevel(logging.WARNING)
# --- TEMPORARILY ENABLE RAG RETRIEVER LOGGING FOR DEBUGGING ---
logging.getLogger('rag_retriever').setLevel(logging.INFO)
logging.getLogger('rag_access_context').setLevel(logging.INFO)

app_logger = logging.getLogger("quart.app")
# --- MODIFICATION START: Set Quart App Logger Level to INFO ---
app_logger.setLevel(logging.INFO) # Ensures quart.app messages (like ours) are shown
# app_logger.setLevel(logging.DEBUG)
# --- MODIFICATION END ---
app_logger.addHandler(handler)
app_logger.propagate = False # Prevent duplicate messages in the root logger


logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp.client.streamable_http").setLevel(logging.WARNING)
logging.getLogger("hypercorn.access").propagate = False
logging.getLogger("hypercorn.error").propagate = False

llm_log_handler = logging.FileHandler(os.path.join(LOG_DIR, "llm_conversation.log"))
llm_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
llm_logger = logging.getLogger("llm_conversation")
llm_logger.setLevel(logging.INFO)
llm_logger.addHandler(llm_log_handler)
llm_logger.propagate = False

llm_history_log_handler = logging.FileHandler(os.path.join(LOG_DIR, "llm_conversation_history.log"))
llm_history_log_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
llm_history_logger = logging.getLogger("llm_conversation_history")
llm_history_logger.setLevel(logging.INFO)
llm_history_logger.addHandler(llm_history_log_handler)
llm_history_logger.propagate = False
# --- End Logging Setup ---

try:
    from trusted_data_agent.agent import prompts
except RuntimeError as e:
    app_logger.critical(f"Application startup failed during initial import: {e}")
    sys.exit(1)

from trusted_data_agent.core.config import APP_CONFIG, APP_STATE


# --- MODIFICATION START: Add RAG Processing Worker ---
async def rag_processing_worker():
    """
    A single, persistent background worker that processes turns from the
    RAG queue one by one, ensuring no race conditions.
    """
    pass  # RAG worker started
    while True:
        try:
            # 1. Wait for a turn_summary to arrive in the queue
            turn_summary = await APP_STATE['rag_processing_queue'].get()

            # 2. Get the RAG retriever instance
            retriever = APP_STATE.get('rag_retriever_instance')
            
            # 3. Process the turn if RAG is enabled and the instance exists
            if retriever and turn_summary and APP_CONFIG.RAG_ENABLED:
                # Get the collection ID from the turn summary (where the base RAG example came from)
                collection_id = turn_summary.get('rag_source_collection_id')
                user_uuid = turn_summary.get('user_uuid')  # --- MODIFICATION: Extract user_uuid ---
                collection_info = f" to collection {collection_id}" if collection_id is not None else " (no RAG base, using default)"
                app_logger.info(f"RAG worker: Processing turn {turn_summary.get('turn')} from session {turn_summary.get('session_id')}{collection_info}.")
                
                # --- MODIFICATION START: Create context and pass to process_turn_for_rag ---
                from trusted_data_agent.agent.rag_access_context import RAGAccessContext
                rag_context = RAGAccessContext(user_id=user_uuid, retriever=retriever)
                
                # Process the turn and get the case_id, passing the context
                case_id = await retriever.process_turn_for_rag(
                    turn_summary, 
                    collection_id=collection_id,
                    rag_context=rag_context  # --- MODIFICATION: Pass context ---
                )
                # --- MODIFICATION END ---
                
                # If a case was created, store the case_id in the session
                if case_id:
                    from trusted_data_agent.core import session_manager
                    session_id = turn_summary.get('session_id')
                    turn_id = turn_summary.get('turn')
                    
                    if session_id and turn_id and user_uuid:
                        try:
                            await session_manager.add_case_id_to_turn(user_uuid, session_id, turn_id, case_id)
                        except Exception as e:
                            app_logger.error(f"Failed to store case_id {case_id} in session: {e}")
                
            # 4. Mark the queue item as processed
            APP_STATE['rag_processing_queue'].task_done()

        except Exception as e:
            # Log errors but don't crash the worker
            app_logger.error(f"Error in RAG processing worker: {e}", exc_info=True)
            # Ensure task_done() is called even on error to prevent queue blockage
            if 'turn_summary' in locals() and turn_summary:
                APP_STATE['rag_processing_queue'].task_done()
# --- MODIFICATION END ---


# User context cleanup worker removed - no longer needed with database persistence


def create_app():
    template_folder = os.path.join(project_root, 'templates')
    static_folder = os.path.join(project_root, 'static')

    app = Quart(__name__, template_folder=template_folder, static_folder=static_folder)
    app = cors(app, allow_origin="*")

    # --- Set Secret Key for Session Management ---
    secret_key = os.getenv('SECRET_KEY')
    if not secret_key:
        app_logger.critical("FATAL: SECRET_KEY environment variable is not set. This is required for session management.")
        raise ValueError("SECRET_KEY is not set. Please set it in your .env file.")
    app.secret_key = secret_key
    # --- End Secret Key ---

    # --- MODIFICATION START: Increase Quart's RESPONSE_TIMEOUT ---
    # This prevents Quart from closing long SSE streams prematurely (default is 60s)
    app.config['RESPONSE_TIMEOUT'] = 1800 # Set to 30 minutes (adjust as needed, or use None for unlimited)
    # You might also want to set REQUEST_TIMEOUT if needed, though less relevant here
    app.config['REQUEST_TIMEOUT'] = None
    # --- MODIFICATION END ---

    from trusted_data_agent.api.routes import api_bp
    from trusted_data_agent.api.rest_routes import rest_api_bp
    from trusted_data_agent.api.auth_routes import auth_bp
    from trusted_data_agent.api.admin_routes import admin_api_bp
    from trusted_data_agent.api.system_prompts_routes import system_prompts_bp
    from trusted_data_agent.api.knowledge_routes import knowledge_api_bp
    from trusted_data_agent.api.contact_routes import contact_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(rest_api_bp, url_prefix="/api")
    app.register_blueprint(auth_bp)  # Auth routes are already prefixed with /api/v1/auth
    app.register_blueprint(admin_api_bp, url_prefix="/api")  # Phase 4 admin & credential management
    app.register_blueprint(system_prompts_bp)  # Phase 3: System prompts (database-backed)
    app.register_blueprint(knowledge_api_bp, url_prefix="/api")  # Knowledge repository endpoints
    app.register_blueprint(contact_bp)  # Contact form endpoint for promotional website

    @app.route('/favicon.ico')
    async def favicon():
        """Serve favicon.ico from root path for browser compatibility"""
        return await app.send_static_file('favicon.ico')

    @app.after_request
    async def add_security_headers(response):
        # Allow connections to unpkg for G2Plot if needed, adjust connect-src
        csp_policy = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com https://cdn.jsdelivr.net", # Allow inline scripts for auth pages + marked.js
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com", # Allow inline styles for G2Plot tooltips etc.
            "font-src 'self' https://fonts.gstatic.com",
            "connect-src 'self' *.googleapis.com https://*.withgoogle.com https://unpkg.com https://api.github.com", # Added unpkg and GitHub API
            "worker-src 'self' blob:",
            "img-src 'self' data:",
            "media-src 'self' blob:" # Allow media from blobs for TTS audio
        ]
        response.headers['Content-Security-Policy'] = "; ".join(csp_policy)
        return response

    # --- MODIFICATION START: Add startup task hook ---
    @app.before_serving
    async def startup():
        """
        Runs once before the server starts serving requests.
        Used to start background tasks like our RAG worker and initialize RAG independently.
        """
        # Initialize authentication database (always required)
        try:
            from trusted_data_agent.auth.database import init_database
            init_database()
        except Exception as e:
            app_logger.error(f"Failed to initialize authentication database: {e}", exc_info=True)
            raise  # Fatal error - cannot run without auth database
        
        # Load configuration from tda_config.json and apply to APP_CONFIG
        from trusted_data_agent.core.config_manager import get_config_manager
        config_manager = get_config_manager()
        loaded_config = config_manager.load_config()
        
        # Load GLOBAL MCP Classification setting from global settings file (overrides environment variable if present)
        # This is a GLOBAL application setting that affects ALL users
        try:
            from pathlib import Path
            import json
            global_settings_file = Path("tda_global_settings.json")
            if global_settings_file.exists():
                with open(global_settings_file, 'r') as f:
                    global_settings = json.load(f)
                if "enable_mcp_classification" in global_settings:
                    APP_CONFIG.ENABLE_MCP_CLASSIFICATION = global_settings["enable_mcp_classification"]
        except Exception as e:
            app_logger.warning(f"Failed to load global settings file: {e}. Using environment default: {APP_CONFIG.ENABLE_MCP_CLASSIFICATION}")
        
        # Initialize RAG early if enabled - independent of LLM/MCP configuration
        if APP_CONFIG.RAG_ENABLED:
            try:
                from pathlib import Path
                from trusted_data_agent.agent.rag_retriever import RAGRetriever
                from trusted_data_agent.agent.rag_template_manager import get_template_manager
                from trusted_data_agent.core.config_manager import get_config_manager
                from trusted_data_agent.core.utils import get_project_root

                app_logger.info("Initializing knowledge retrieval system...")

                # Calculate paths using get_project_root to handle both installed and editable installs
                project_root = get_project_root()
                rag_cases_dir = project_root / APP_CONFIG.RAG_CASES_DIR
                persist_dir = project_root / APP_CONFIG.RAG_PERSIST_DIR

                # Load collections from persistent config
                config_manager = get_config_manager()
                collections_list = config_manager.get_rag_collections()
                APP_STATE["rag_collections"] = collections_list

                # Initialize RAG template manager
                template_manager = get_template_manager()
                templates = template_manager.list_templates()
                APP_STATE['rag_template_manager'] = template_manager

                # Initialize RAG retriever (loads embedding model and ChromaDB)
                app_logger.info("Loading embedding model and vector store...")
                retriever_instance = RAGRetriever(
                    rag_cases_dir=rag_cases_dir,
                    embedding_model_name=APP_CONFIG.RAG_EMBEDDING_MODEL,
                    persist_directory=persist_dir
                )
                APP_STATE['rag_retriever_instance'] = retriever_instance
                app_logger.info("Knowledge retrieval system ready.")

            except Exception as e:
                app_logger.error(f"Failed to initialize RAG at startup: {e}", exc_info=True)
                APP_STATE["rag_collections"] = []
        else:
            APP_STATE["rag_collections"] = []
        
        # Start the single RAG worker as a background task
        asyncio.create_task(rag_processing_worker())

        # Print ready message now that all initialization is complete
        host = APP_STATE.get('server_host', '127.0.0.1')
        port = APP_STATE.get('server_port', 5050)
        print(f"\n{'='*60}")
        print(f"  Web client initialized and ready!")
        print(f"  Navigate to http://{host}:{port}")
        print(f"{'='*60}\n")
    # --- MODIFICATION END ---

    return app

app = create_app()

async def main(args): # MODIFIED: Accept args
    print("\n--- Starting Hypercorn Server for Quart App ---")
    host = args.host
    port = args.port
    # Store host/port in APP_STATE so startup() can print the ready message after RAG initialization
    APP_STATE['server_host'] = host
    APP_STATE['server_port'] = port
    print(f"Server starting on http://{host}:{port} - please wait for initialization...")
    config = Config()
    config.bind = [f"{host}:{port}"] # MODIFIED: Use dynamic host and port
    config.accesslog = None
    config.errorlog = None
    # --- MODIFICATION START: Add longer Hypercorn timeouts (Good Practice) ---
    # While Quart's RESPONSE_TIMEOUT was the main fix, setting these high
    # ensures Hypercorn doesn't impose its own shorter limits.
    config.worker_timeout = 600 # e.g., 10 minutes
    config.read_timeout = 600  # e.g., 10 minutes
    app_logger.info(f"Hypercorn worker timeout set to {config.worker_timeout} seconds.")
    app_logger.info(f"Hypercorn read timeout set to {config.read_timeout} seconds.")
    # --- MODIFICATION END ---
    await hypercorn.asyncio.serve(app, config)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Uderia Platform web client.")
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind the server to. Use '0.0.0.0' for Docker."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5050,
        help="Port to bind the server to."
    )
    parser.add_argument("--nogitcall", action="store_true", help="Disable GitHub API calls to fetch star count.")
    parser.add_argument("--offline", action="store_true", help="Use cached HuggingFace models only (skip remote version checks).")
    args = parser.parse_args()

    if args.nogitcall:
        APP_CONFIG.GITHUB_API_ENABLED = False
        print("\n--- GITHUB API DISABLED: Star count fetching is disabled. ---\n")
    else:
        APP_CONFIG.GITHUB_API_ENABLED = True
        print("\n--- GITHUB API ENABLED: Star count will be fetched from GitHub. ---\n")

    if args.offline:
        os.environ['HF_HUB_OFFLINE'] = '1'
        print("\n--- OFFLINE MODE: Using cached HuggingFace models only (no remote checks). ---\n")

    print("\n--- CHARTING ENABLED: Charting configuration is active. ---\n")

    if APP_CONFIG.VOICE_CONVERSATION_ENABLED:
        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            print("\n--- ⚠️ VOICE FEATURE WARNING ---\n")
            print("The 'GOOGLE_APPLICATION_CREDENTIALS' environment variable is not set.")
            print("The voice conversation feature will require credentials to be provided in the config UI.")
        else:
            print("\n--- VOICE FEATURE ENABLED: Credentials found in environment. ---\n")

    try:
        asyncio.run(main(args)) # MODIFIED: Pass args to main
    except KeyboardInterrupt:
        print("\nServer shut down.")