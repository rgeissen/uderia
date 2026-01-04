# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Uderia Platform** - Enterprise-grade AI orchestration platform with cloud-level reasoning and zero-trust privacy. The platform provides a multi-provider LLM agent system with MCP (Model Context Protocol) integration, RAG-powered continuous improvement, and comprehensive multi-user authentication.

## Development Commands

### Running the Application

```bash
# Standard mode (certified models only)
python -m trusted_data_agent.main

# Developer mode (all models including uncertified)
python -m trusted_data_agent.main --all-models

# Access at: http://localhost:5050
# Default credentials: admin / admin (CHANGE IMMEDIATELY!)
```

### Installation & Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install in editable mode (REQUIRED - must be run from project root)
pip install -e .

# Regenerate JWT secret (CRITICAL SECURITY STEP)
python maintenance/regenerate_jwt_secret.py
```

### Testing

```bash
# Run specific test files
python test/test_access_tokens.py
python test/test_bedrock_connectivity.py
python schema/dev/test_prompt_encryption.py

# Test with PYTHONPATH
PYTHONPATH=/Users/livin2rave/my_private_code/uderia/src python test/<test_file>.py
```

### Database Management

```bash
# Database files
tda_auth.db              # User authentication, credentials, configuration
tda_sessions/            # Session data per user
schema/*.sql             # Schema definitions (read-only)

# Bootstrap encrypted prompts
schema/default_prompts.dat  # Encrypted system prompts (84KB)
```

## Architecture Overview

### High-Level System Design

```
┌──────────┐      ┌─────────────┐      ┌──────────┐      ┌─────┐      ┌─────────┐
│  Browser │ SSE  │   Backend   │ HTTP │   LLM    │ HTTP │ MCP │ SQL  │ Data    │
│   (UI)   │◄────►│   (Quart)   │─────►│ Provider │      │ Svr │─────►│ Source  │
└──────────┘      └─────────────┘      └──────────┘      └─────┘      └─────────┘
```

### Core Module Structure

- **`src/trusted_data_agent/agent/`** - Agent execution engine
  - `executor.py` - Main orchestrator with Fusion Optimizer
  - `planner.py` - Strategic & tactical planning logic
  - `phase_executor.py` - Individual phase execution
  - `orchestrators.py` - Specialized execution patterns
  - `formatter.py` - Response formatting & rendering
  - `prompt_loader.py` - Database-backed prompt system with tier-based access
  - `prompt_encryption.py` - License-based encryption (runtime vs UI access)
  - `profile_prompt_resolver.py` - Profile-specific prompt resolution
  - `rag_retriever.py` - RAG case retrieval
  - `repository_constructor.py` - RAG template plugins

- **`src/trusted_data_agent/llm/`** - Multi-provider LLM integration
  - `handler.py` - Unified LLM interface with profile support
  - `client_factory.py` - Provider-specific client creation

- **`src/trusted_data_agent/mcp_adapter/`** - MCP protocol client
  - `adapter.py` - Tool/prompt/resource discovery & execution

- **`src/trusted_data_agent/api/`** - REST & SSE endpoints
  - `routes.py` - Interactive UI endpoints (SSE streaming)
  - `rest_routes.py` - Async REST API (task-based)
  - `auth_routes.py` - Authentication (JWT + OAuth)
  - `admin_routes.py` - User management
  - `system_prompts_routes.py` - Prompt editing (PE/Enterprise only)
  - `knowledge_routes.py` - Knowledge repository management

- **`src/trusted_data_agent/auth/`** - Authentication & authorization
  - `database.py` - User database initialization
  - `middleware.py` - JWT validation & decorators
  - `encryption.py` - Fernet credential encryption
  - `oauth_handlers.py` - Google/GitHub OAuth
  - `email_verification.py` - Email verification flow
  - `consumption_enforcer.py` - Rate limiting & quotas
  - `rate_limiter.py` - Token-bucket rate limiting

- **`src/trusted_data_agent/core/`** - Configuration & state
  - `config.py` - Global configuration (APP_CONFIG, APP_STATE)
  - `config_manager.py` - Database-backed config management
  - `session_manager.py` - Session persistence & context
  - `cost_manager.py` - LLM cost tracking & analytics
  - `collection_db.py` - ChromaDB RAG collections

- **`static/js/`** - Frontend JavaScript
  - `adminManager.js` - User tier management UI
  - `handlers/` - Feature-specific handlers (RAG, marketplace, etc.)

### Key Architectural Patterns

#### 1. License-Based Prompt Encryption

**Critical Understanding**: The system has tier-based access for system prompts:

- **Runtime access** (all tiers): All users can decrypt prompts for LLM conversations
- **UI access** (PE/Enterprise only): Only privileged tiers can view/edit prompts in UI

Functions:
- `can_access_prompts(tier)` - Always returns True (runtime decryption)
- `can_access_prompts_ui(tier)` - Returns True only for PE/Enterprise (UI editing)

Files: `src/trusted_data_agent/agent/prompt_encryption.py`, `prompt_loader.py`

#### 2. Profile System Architecture

**Profiles combine MCP Server + LLM Provider** into reusable configurations:

- **Default profile**: Used for all queries unless overridden
- **Temporary override**: `@TAG` syntax for single-query profile switching
- **Profile classification**: Light (filter-based) vs Full (LLM-assisted)

Session data tracks:
- `profile_id` - Current active profile
- `profile_tag` - Current profile tag
- `profile_tags_used[]` - History of all profiles used
- `models_used[]` - History of all LLM providers/models used

Files: `src/trusted_data_agent/agent/executor.py`, `profile_prompt_resolver.py`

#### 3. Multi-User Authentication Flow

```
1. User login → JWT issued (24h) or OAuth flow
2. Credentials encrypted (Fernet) → Stored per-user in tda_auth.db
3. Profiles associated with user account
4. Session isolation by user UUID
5. Bootstrap configuration copied on first login
```

- **JWT tokens**: Web UI sessions (24-hour expiry)
- **Access tokens**: Long-lived REST API tokens (90 days or never)
- **User tiers**: `user`, `developer`, `admin` (controls feature access)

Files: `src/trusted_data_agent/auth/middleware.py`, `database.py`, `auth_routes.py`

#### 4. RAG System (Retrieval-Augmented Generation)

**Two repository types**:
- **Planner Repositories**: Execution strategies and proven patterns
- **Knowledge Repositories**: Reference documents and domain knowledge

**Template plugins** (`rag_templates/`):
- Self-contained modules with manifests
- SQL query templates, document Q&A
- Auto-generation via LLM assistance

Files: `src/trusted_data_agent/agent/rag_retriever.py`, `repository_constructor.py`, `rag_template_manager.py`

#### 5. Fusion Optimizer Execution Flow

```
User Query → Strategic Plan → Tactical Execution → Tool Calls → Response Synthesis
                  ↓                    ↓
              RAG Retrieval     Plan Hydration
              (champion cases)  (context injection)
```

- **Strategic planning**: High-level meta-plan (phases)
- **Tactical execution**: Single-step tool selection (per phase)
- **Self-correction**: Error recovery with targeted prompts
- **Plan hydration**: Inject previous turn results to skip redundant calls

Files: `src/trusted_data_agent/agent/executor.py`, `planner.py`, `phase_executor.py`

## Critical Implementation Details

### Database Schema Migration

**The system migrated from file-based config to database schema (Dec 2024)**:

- Old: `tda_config.json` (read-write user config)
- New: Database tables in `tda_auth.db`
- Bootstrap: `tda_config.json` is now a read-only template copied on first user login

Schema files in `schema/`:
- `00_master.sql` - Database initialization
- `01_core_tables.sql` - Prompts, users, profiles
- `02_parameters.sql` - Prompt parameters & overrides
- `03_profile_integration.sql` - Profile-prompt mappings
- `06_prompt_mappings.sql` - Provider-specific prompt routing

### Prompt Management System

**System prompts** are stored encrypted in database:

1. **Bootstrap encryption**: `schema/default_prompts.dat` encrypted with key from `tda_keys/public_key.pem`
2. **Database encryption**: Re-encrypted with tier-specific key (from license signature + tier)
3. **Runtime decryption**: All tiers can decrypt for LLM usage
4. **UI restrictions**: Only PE/Enterprise can view/edit via System Prompts editor

**Prompt override hierarchy** (highest to lowest priority):
1. User-level override (PE/Enterprise only)
2. Profile-level override
3. Base prompt from database

### Session Management

**Session persistence** in `tda_sessions/{session_id}/`:
- `conversation.json` - Chat history for UI rendering
- `workflow.json` - Turn summaries for planner context
- `llm_conversation.json` - Raw LLM conversation history

**Context modes**:
- **Full Context**: Sends entire conversation history
- **Turn Summaries**: Sends only workflow summaries (stateless)

Activation: Hold `Alt` for single query, `Shift+Alt` to lock mode

### Cost Management

**Real-time cost tracking**:
- Token counting per turn (input + output)
- Provider-specific pricing from `llm_model_costs` table
- LiteLLM integration for automatic pricing sync
- Manual overrides preserved during sync

Files: `src/trusted_data_agent/core/cost_manager.py`

### Security Considerations

1. **Credential encryption**: All API keys encrypted with Fernet (stored in `tda_auth.db`)
2. **JWT secrets**: Regenerate `tda_keys/jwt_secret.key` on installation
3. **License validation**: `tda_keys/license.key` verified on startup
4. **Rate limiting**: Configurable per-user quotas (disabled by default)
5. **OAuth**: Google/GitHub integration with email verification

## Common Development Tasks

### Adding a New LLM Provider

1. Update `src/trusted_data_agent/llm/client_factory.py` with provider-specific client
2. Add provider to `src/trusted_data_agent/core/provider_colors.py`
3. Update UI dropdown in `templates/index.html`
4. Add pricing data to `llm_model_costs` table

### Modifying System Prompts

**For PE/Enterprise tiers only**:
1. UI: Setup → System Prompts → Edit prompt
2. Database: Prompts stored encrypted in `prompts` table
3. Versioning: Changes saved to `prompt_versions` table

**For development**:
1. Edit `schema/default_prompts.dat` (requires encryption tools)
2. Or modify database directly after decryption

### Creating RAG Template Plugins

1. Create directory in `rag_templates/templates/<your-template>/`
2. Add `manifest.json` with schema definition
3. Implement `template.py` with required methods
4. Register in `rag_templates/registry.json`

See: `rag_templates/README.md`, `rag_templates/PLUGIN_MANIFEST_SCHEMA.md`

### Working with Multi-User Features

**User creation**:
- UI: Administration → User Management
- API: `POST /api/v1/admin/users`

**User tiers** (controls feature access):
- `user` - Basic conversation access
- `developer` - Additional tools/debugging
- `admin` - Full system access

**Profile tiers** (separate from user tiers):
- Controls prompt override capabilities
- Defined in profile tier system (User → Developer → Admin)

## Important Files & Locations

### Configuration Files

```
tda_config.json          # Read-only bootstrap template
tda_auth.db              # User database (credentials, config, prompts)
tda_keys/
  ├── license.key        # License validation (JSON)
  ├── public_key.pem     # Signature verification + bootstrap encryption
  └── jwt_secret.key     # JWT token signing (regenerate on install!)
```

### Entry Points

```
src/trusted_data_agent/main.py              # Application startup
templates/index.html                         # Single-page UI
static/js/main.js                           # Frontend initialization
```

### Documentation

```
docs/
  ├── RestAPI/restAPI.md                    # REST API reference
  ├── PROMPT_ENCRYPTION.md                  # Encryption architecture
  ├── RAG/RAG.md                            # RAG system guide
  ├── Marketplace/MARKETPLACE_COMPLETE_GUIDE.md
  └── OAuth/OAUTH.md                        # OAuth setup
```

## Troubleshooting

### ModuleNotFoundError

**Problem**: Python can't find `trusted_data_agent` module

**Solution**:
1. Ensure you're in project root directory
2. Run `pip install -e .` in your active virtual environment
3. Verify `pyproject.toml` exists with correct `[tool.setuptools.packages.find]`

### License Validation Errors

**Problem**: App won't start, license errors in logs

**Check**:
1. `tda_keys/license.key` exists and is valid JSON
2. `tda_keys/public_key.pem` exists
3. License not expired (`expires_at` field)

### Database Schema Issues

**Problem**: Missing tables, column errors

**Solution**:
1. Delete `tda_auth.db`
2. Restart application (auto-creates from `schema/*.sql`)
3. Default admin account recreated: `admin` / `admin`

### Prompt Decryption Failures

**Problem**: Standard tier users get `[ENCRYPTED CONTENT]` in conversations

**This is now FIXED**: All tiers can decrypt for runtime LLM usage. If this occurs:
1. Check `can_access_prompts()` in `prompt_encryption.py` returns True
2. Verify license signature in database matches file
3. Check logs for decryption errors

### Frontend Build Issues

**Note**: The application uses CDN-loaded Tailwind CSS (no build step required)

For production: Consider building Tailwind locally:
```bash
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss build
```

## Project-Specific Conventions

### Code Organization

- **Async/await**: All API routes and LLM calls are async (Quart framework)
- **Type hints**: Used throughout Python codebase
- **Logging**: Use `logger = logging.getLogger("quart.app")`
- **Error handling**: Graceful degradation with user-facing error messages

### Naming Conventions

- **Database tables**: `snake_case` (e.g., `llm_model_costs`)
- **Python classes**: `PascalCase` (e.g., `PromptLoader`)
- **Python functions**: `snake_case` (e.g., `can_access_prompts_ui`)
- **JavaScript**: `camelCase` (e.g., `renderUsersTable`)
- **API routes**: `/api/v1/<resource>/<action>`

### Git Workflow

- **Recent commits** focus on:
  - License problem fixes
  - Admin UI improvements
  - Docker deployment enhancements
- **Branch**: `main` (default)

## External Integrations

### MCP (Model Context Protocol)

- Connect to external MCP servers for tools/prompts/resources
- Dynamic capability discovery at runtime
- Credential passthrough (no server-side storage)

### LLM Providers Supported

- Google (Gemini 2.0)
- Anthropic (Claude)
- OpenAI (GPT-4o)
- Azure OpenAI
- AWS Bedrock
- Friendli.AI
- Ollama (local, offline)

### Apache Airflow Integration

- DAG examples in `docs/Airflow/`
- Async polling pattern for long-running tasks
- Session reuse via `tda_session_id` variable

### Flowise Integration

- Visual workflow builder
- Pre-built TDA agent flows
- Import-ready JSON templates in `docs/Flowise/`

## Performance & Scalability

### Token Optimization

- **Plan hydration**: Reuses previous turn results
- **Tactical fast path**: Skips LLM for simple tool calls
- **Context distillation**: Summarizes large tool outputs
- **RAG efficiency**: Learns from past successes

### Deployment Options

- **Single-user**: Local Python process
- **Multi-user**: Docker container with volume mounts
- **Load balanced**: Multiple containers (ports 5050, 5051, 5052...)

### Rate Limiting

- **Disabled by default** for single-user installs
- **Configurable** via UI: Administration → App Config → Security
- **Per-user quotas**: Prompts/hour, tokens/month, config changes
- **Consumption profiles**: Free, Pro, Enterprise, Unlimited

## Recent Major Changes

- **Jan 2026**: OAuth (Google/GitHub), email verification
- **Dec 2025**: Prompt encryption to database, enhanced bootstrapping
- **Dec 2025**: Consumption profile enforcement, financial governance
- **Nov 2025**: Multi-user auth, profile system, RAG constructors
- **Nov 2025**: Knowledge repositories, marketplace integration
