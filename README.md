# Uderia Platform - Your Trusted Data Agent
### Cloud-Level Reasoning. Zero-Trust Privacy.

The **Uderia Platform** delivers enterprise-grade AI orchestration with unmatched flexibility. Whether you leverage hyperscaler intelligence for maximum capability, run private local models for absolute sovereignty, or blend both approaches, you get cloud-level reasoning with complete control over your data and costs.

Experience a fundamental transformation in how you work with enterprise data:

- **From Days to Seconds** - Discover insights via conversation. Operationalize them via API. Your conversational discovery is your production-ready automation.
- **From Guesswork to Clarity** - Full transparency eliminates the AI black box. See every strategic plan, tool execution, and self-correction in real-time.
- **From $$$ to ¢¢¢** - Revolutionary Fusion Optimizer with strategic planning, proactive optimization, and autonomous self-correction for cost-effective execution.
- **From Data Exposure to Data Sovereignty** - Your data, your rules, your environment. Execute with cloud intelligence while maintaining local privacy.
- **From Hidden Costs to Total Visibility** - Complete financial governance with real-time tracking, comprehensive analytics, and fine-grained cost control.
- **From Isolated Expertise to Collective Intelligence** - Transform individual insights into organizational knowledge through the Intelligence Marketplace.

Whether on-premises or in the cloud, you get **enterprise results** with **optimized speed** and **minimal token cost**, built on the six core principles detailed below.

![Demo](./images/AppOverview.gif)

---


### Table Of Contents

1. [Core Principles: A Superior Approach](#core-principles-a-superior-approach)
2. [Key Features](#-key-features)
3. [The Heart of the Application - The Engine & its Fusion Optimizer](#-the-heart-of-the-application---the-engine--its-fusion-optimizer)
4. [Retrieval-Augmented Generation (RAG) for Self-Improving AI](#-retrieval-augmented-generation-rag-for-self-improving-ai)
5. [How It Works: Architecture](#%EF%B8%8F-how-it-works-architecture)
6. [Installation and Setup Guide](#-installation-and-setup-guide)
7. [Developer Mode: Unlocking Models](#developer-mode-unlocking-models)
8. [User Guide](#-user-guide)
   - [Getting Started](#getting-started)
   - [Using the Interface](#using-the-interface)
   - [Advanced Context Management](#advanced-context-management)
   - [REST API Integration](#rest-api-integration)
   - [Real-Time Monitoring](#real-time-monitoring)
   - [Operationalization](#operationalization)
   - [Troubleshooting](#troubleshooting)
9. [Docker Deployment](#docker-deployment)
10. [License](#license)
11. [Author & Contributions](#author-contributions)
12. [Appendix: Feature Update List](#appendix-feature-update-list)


---

## Core Principles: A Superior Approach

The Uderia Platform transcends typical data chat applications by delivering a seamless and powerful experience based on six core principles:

### 🚀 Actionable
Go from conversational discovery to a production-ready, automated workflow in seconds. The agent's unique two-in-one approach means your interactive queries can be immediately operationalized via a REST API, eliminating the friction and redundancy of traditional data operations. What once took data experts weeks is now at your fingertips.

### 🔍 Transparent
Eliminate the "black box" of AI. The Uderia Platform is built on a foundation of absolute trust, with a Live Status Window that shows you every step of the agent's thought process. From the initial high-level plan to every tool execution and self-correction, you have a clear, real-time view, leaving no room for guesswork.

### ⚡ Efficient
Powered by the intelligent Fusion Optimizer, the agent features a revolutionary multi-layered architecture for resilient and cost-effective task execution. Through strategic and tactical planning, proactive optimization, and autonomous self-correction, the agent ensures enterprise-grade performance and reliability.

### 🛡️ Sovereignty
Your data, your rules, your environment. The agent gives you the ultimate freedom to choose your data exposure strategy. Leverage the power of hyperscaler LLMs, or run fully private models on your own infrastructure with Ollama, keeping your data governed entirely by your rules. The agent connects to the models you trust.

### 💰 Financial Governance
Complete cost transparency and control over your LLM spending. The agent provides real-time cost tracking, comprehensive analytics, and detailed visibility into every token consumed. With accurate per-model pricing, cost attribution by provider, and powerful administrative tools, you maintain full financial oversight of your AI operations.

### 🤝 Collaborative
Transform isolated expertise into collective intelligence. The Intelligence Marketplace enables you to share proven execution patterns and domain knowledge with the community, subscribe to curated collections from experts, and fork specialized repositories for your unique needs. By leveraging community-validated RAG collections, you reduce token costs, accelerate onboarding, and benefit from battle-tested strategies—turning individual insights into a powerful, shared ecosystem.

[⬆️ Back to Table of Contents](#table-of-contents)

---

## 🌟 Key Features

The Uderia Platform's features are organized around the six core principles that define its value proposition. Each principle is realized through a comprehensive set of capabilities designed to deliver enterprise-grade AI orchestration.

---

### 🚀 Actionable: From Discovery to Production in Seconds

Eliminate the friction between conversational exploration and production automation. The agent's unique architecture enables seamless operationalization of interactive queries.

* **Comprehensive REST API**: Full programmatic control with asynchronous task-based architecture for reliable, scalable automation:
  - Session management (create, delete, list with conversation history)
  - Query execution with async submit + poll pattern
  - Task management (status polling, cancellation, result retrieval)
  - Configuration management (profiles, LLM providers, MCP servers)
  - RAG collection CRUD operations
  - Analytics endpoints (session costs, token usage, efficiency metrics)

* **Apache Airflow Integration**: Production-ready DAG examples for batch query automation:
  - Session reuse via `tda_session_id` variable
  - Profile override via `tda_profile_id` for specialized workloads
  - Bearer token authentication for secure API access
  - Async polling pattern for reliable long-running executions
  - Complete example DAG (`tda_00_execute_questions.py`) included

* **Profile System for Modular Configuration**: Separate infrastructure from usage patterns:
  - Combine LLM Providers + MCP Servers into named profiles
  - Profile tags (e.g., "PROD", "COST") for quick identification
  - Default profile for standard operations
  - Temporary overrides via `@TAG` syntax for single queries
  - Active for consumption toggle for available alternatives
  - Classification modes: Light (tool/prompt filtering) vs. Full (LLM-assisted categorization)

* **Long-Lived Access Tokens**: Secure automation without session management:
  - Configurable expiration (90 days default, or never)
  - SHA256 hashed storage with audit trail
  - Usage tracking (last used timestamp, use count, IP address)
  - Soft-delete preservation for compliance
  - One-time display at creation for enhanced security

* **Docker Deployment Support**: Production-ready containerization:
  - Multi-user support in single shared container
  - Environment variable overrides
  - Volume mounts for sessions, logs, and keys
  - Load balancer ready for horizontal scaling

* **Flowise Integration**: Low-code workflow automation and chatbot development:
  - Pre-built agent flow for TDA Conversation handling
  - Asynchronous submit & poll pattern implementation
  - Session management with multi-turn conversation support
  - Bearer token authentication for secure API access
  - Profile override capability for specialized workflows
  - TTS payload extraction for voice-enabled chatbots
  - Visual workflow designer for complex orchestration
  - Import-ready JSON template included ([see docs/Flowise](docs/Flowise/Flowise.md))

---

### 🔍 Transparent: Eliminate the AI Black Box

Build trust through complete visibility into every decision, action, and data point the agent processes.

* **Live Status Panel**: Real-time window into the agent's reasoning process:
  - Strategic plan visualization with phase-by-phase breakdown
  - Tactical decision display showing tool selection rationale
  - Raw data inspection for every tool response
  - Self-correction events with recovery strategy visibility
  - Streaming updates via Server-Sent Events (SSE)

* **Dynamic Capability Discovery**: Instant overview of agent potential:
  - Automatic loading of all MCP Tools from connected servers
  - Prompt library display with categorization
  - Resource enumeration for data source visibility
  - Real-time capability updates on configuration changes
  - Visual organization in tabbed Capabilities Panel

* **Rich Data Rendering**: Intelligently formats and displays various data types:
  - Query results in interactive tables with sorting/filtering
  - SQL DDL in syntax-highlighted code blocks
  - Key metrics in summary cards
  - Integrated charting engine for data visualization
  - Real-time rendering as data streams in

* **Comprehensive Token Tracking**: Per-turn visibility into LLM consumption:
  - Input token counts for every request
  - Output token counts for every response
  - Token-to-cost mapping with provider-specific pricing
  - Historical token trends across sessions
  - Optimization insights for cost-conscious users

* **Execution Monitoring Dashboard**: Cross-source workload tracking:
  - Real-time task list (running, completed, failed)
  - Detailed execution logs with reasoning steps
  - Tool invocation history with arguments and responses
  - Error messages and stack traces for debugging
  - Task control (cancel, retry) for operational flexibility

* **Audit Logging**: Complete activity trail for compliance:
  - User authentication and authorization events
  - Configuration changes with before/after snapshots
  - API usage patterns and access history
  - Admin actions on user accounts and system settings
  - Exportable logs for regulatory compliance

* **Advanced Context Controls**: Surgical precision over agent memory:
  - Turn-level activation/deactivation with visual feedback
  - Context purge for complete memory reset
  - Query replay for exploring alternative approaches
  - Full Context vs. Turn Summaries modes
  - Context indicator with real-time status

* **System Customization**: Take control of agent behavior:
  - System Prompt Editor for per-model instruction customization
  - Save and reset capabilities for experimentation
  - Direct Model Chat for baseline testing without tools
  - Dynamic Capability Management (enable/disable tools/prompts)
  - Phased rollouts without server restart

---

### ⚡ Efficient: Intelligent Optimization Engine

The Fusion Optimizer and self-improving RAG system deliver enterprise-grade performance, cost efficiency, and reliability. See the dedicated section below (**[The Heart of the Application - The Engine & its Fusion Optimizer](#the-heart-of-the-application---the-engine-its-fusion-optimizer)**) for comprehensive details on:

* Multi-layered strategic and tactical planning
* Proactive optimization (Plan Hydration, Tactical Fast Path, Specialized Orchestrators)
* Autonomous self-correction and healing
* RAG-powered continuous improvement
* Deterministic plan validation and hallucination prevention

**Key efficiency highlights:**

* **Self-Improving RAG System**: Closed-loop learning from past successes:
  - Automatic capture and archiving of all successful interactions
  - Token-based efficiency analysis to identify "champion" strategies
  - Few-shot learning through injection of best-in-class examples
  - Asynchronous processing to eliminate user-facing latency
  - Per-user cost savings attribution and tracking

* **Planner Repository Constructors**: Modular plugin system for domain-specific optimization:
  - Self-contained templates with validation schemas
  - SQL query templates with extensibility for document Q&A, API workflows
  - LLM-assisted auto-generation from database schemas
  - Dynamic runtime registration from `rag_templates/` directory
  - Programmatic population via REST API for CI/CD integration

* **Knowledge Repositories**: Domain context injection for better planning:
  - PDF, TXT, DOCX, MD document support
  - Configurable chunking strategies (fixed-size, paragraph, sentence, semantic)
  - Planning-time retrieval via `_retrieve_knowledge_for_planning()`
  - Semantic search for relevant background information
  - Marketplace integration for community knowledge sharing

---

### 🛡️ Sovereignty: Your Data, Your Rules, Your Environment

Maintain complete control over your data exposure strategy with flexible deployment and provider options.

* **Multi-Provider LLM Support**: Freedom to choose your AI infrastructure:
  - **Cloud Hyperscalers**: Google (Gemini), Anthropic (Claude), OpenAI (GPT-4o), Azure OpenAI
  - **AWS Bedrock**: Foundation models and inference profiles for custom/provisioned models
  - **Friendli.AI**: High-performance serverless and dedicated endpoint support
  - **Ollama**: Fully local, offline LLM execution on your own infrastructure
  - Dynamic provider switching without configuration restart
  - Live model refresh to fetch latest available models

* **Comparative LLM Testing**: Validate model behavior across providers:
  - Identical MCP tools and prompts across different LLMs
  - Side-by-side performance comparison
  - Model capability robustness validation
  - Direct model chat for baseline reasoning assessment
  - Profile-based A/B testing with `@TAG` overrides

* **Encrypted Credential Storage**: Enterprise-grade security:
  - Fernet symmetric encryption for all API keys
  - Per-user credential isolation in SQLite database
  - Credentials never logged or exposed in UI/API responses
  - Secure passthrough to LLM/MCP providers
  - Admin oversight without credential access

* **Multi-User Isolation**: Complete session and data segregation:
  - JWT-based authentication with 24-hour expiry
  - User-specific sessions in separate directories
  - Database-level user UUID isolation
  - Role-based access control (User, Developer, Admin)
  - Simultaneous multi-user support with no cross-contamination

* **Flexible Deployment Options**: Adapt to your infrastructure:
  - Single-user development (local Python process)
  - Multi-user production (load-balanced containers or shared instance)
  - HTTPS support via reverse proxy configuration
  
  - Docker volume mounts for persistent data

* **Voice Conversation Privacy**: Optional Google Cloud TTS with user-provided credentials:
  - User-controlled API key management
  - No server-side credential storage for voice features
  - Browser-based Speech Recognition (local processing)
  - Hands-free operation with configurable voice modes
  - Key observations handling (autoplay-off, autoplay-on, off)

---

### 💰 Financial Governance: Track Every Penny, Control Every Cost

Transparent, real-time cost tracking with fine-grained control over spending at every level of abstraction.

* **Real-Time Cost Tracking**: Per-interaction visibility:
  - Automatic cost calculation using up-to-date provider pricing
  - Per-turn breakdown (input tokens, output tokens, total cost)
  - Session-level cumulative cost tracking
  - User-level cost aggregation across all sessions
  - Historical cost trends and analytics

* **Provider-Specific Pricing Models**: Accurate cost attribution:
  - Google Gemini (1.5 Pro, 1.5 Flash, etc.) with context length tiers
  - Anthropic Claude (Opus, Sonnet, Haiku) with standard/batch pricing
  - OpenAI GPT-4o and GPT-4o-mini with tiered pricing
  - Azure OpenAI (GPT-4, GPT-3.5-Turbo) with regional pricing
  - AWS Bedrock (foundation models, inference profiles)
  - Friendli.AI serverless and dedicated endpoints
  - Ollama (local models, zero external cost)

* **Database-Backed Cost Persistence**: Complete financial audit trail:
  - `llm_model_costs` table with versioned pricing
  - `efficiency_metrics` table tracking token usage and RAG savings
  - `user_sessions` table with per-session cost summaries
  - `long_lived_access_tokens` with usage tracking
  - Exportable cost reports for budgeting and forecasting

* **Profile-Based Spending Controls**: Optimize costs by workload:
  - Tag profiles by cost characteristics (e.g., "COST" for Gemini Flash)
  - Quick switching between expensive (Claude Opus) and economical (Gemini Flash) models
  - Profile override via `@TAG` syntax for cost-conscious queries
  - REST API profile selection for automated cost optimization

* **Efficiency Attribution**: Quantify RAG system savings:
  - Before/after token comparison for RAG-guided planning
  - Estimated cost savings from few-shot learning
  - Per-user attribution of efficiency gains
  - Efficiency leaderboard for gamification
  - Continuous improvement ROI visibility

* **Cost Optimization Recommendations**: Actionable insights:
  - Model selection guidance based on task complexity
  - Context pruning opportunities for token reduction
  - RAG case population priorities for maximum savings
  - Profile configuration suggestions for workload patterns

* **Consumption Profile Enforcement**: Granular usage controls and quotas:
  - Four predefined tiers: Free, Pro, Enterprise, Unlimited
  - Per-user prompt rate limits (hourly and daily)
  - Monthly token quotas (input and output tokens separately)
  - Configuration change rate limits per hour
  - Profile activation/deactivation for testing
  - Global override mode for emergency rate limiting
  - Admin bypass for unrestricted system access
  - Real-time enforcement with clear error messages
  - Database-backed consumption tracking and audit trail

---

### 🤝 Collaborative: Build and Share Intelligence

The Intelligence Marketplace transforms individual agent expertise into collective organizational knowledge.

* **Template Marketplace for RAG Cases**: Crowdsourced knowledge repository:
  - Create templates from your best RAG cases with "Create Template" button
  - Browse and discover templates created by other users
  - One-click deployment: "Deploy to My Repository" for instant activation
  - Star rating system for quality curation
  - Usage statistics and popularity tracking

* **Template Metadata and Discovery**: Rich categorization:
  - Structured metadata: name, description, creator, timestamps
  - Tag-based categorization for easy browsing
  - Target repository specification ("Planner Repository" vs. custom)
  - Version tracking for template evolution
  - Search and filtering by tags, creator, or rating

* **Template Deployment Workflow**: Seamless integration:
  - User selects target repository during deployment
  - System validates compatibility with repository schema
  - Deployed cases immediately available for RAG retrieval
  - Duplicate detection to prevent redundant cases
  - Deployment confirmation with success feedback

* **Admin Marketplace Controls**: Governance for enterprise use:
  - Admin review queue for template approval
  - Quality gates before marketplace publication
  - Template flagging for inappropriate content
  - Usage analytics for template ROI measurement
  - Bulk operations (approve, reject, delete)

* **Community Knowledge Sharing**: Accelerate organizational learning:
  - Share SQL query patterns across data teams
  - Distribute API workflow best practices
  - Propagate domain expertise from power users to beginners
  - Build institutional memory that survives employee turnover
  - Create center-of-excellence pattern libraries

* **Marketplace Analytics**: Track collaborative value:
  - Most deployed templates
  - Top contributors by template count and ratings
  - Deployment velocity and adoption rates
  - Cost savings from marketplace-sourced knowledge
  - Community engagement metrics

### Financial Governance and Cost Management

* **Real-Time Cost Tracking**: Every LLM interaction is tracked with precise cost calculation based on actual token usage (input/output tokens) and model-specific pricing. View cumulative costs across all sessions with transparent, token-level granularity.

* **Comprehensive Cost Analytics Dashboard**: Admin-accessible analytics provide deep insights into spending patterns:
  - Total cost across all sessions
  - Average cost per session and per turn
  - Cost distribution by LLM provider (Google, Anthropic, OpenAI, AWS, Azure, Friendli, Ollama)
  - Top 5 most expensive models with usage breakdowns
  - 30-day cost trend visualization
  - Most expensive sessions and queries with drill-down capabilities

* **Intelligent Pricing Management**: Dynamic model cost database with multiple data sources:
  - **Automatic Sync**: Integration with LiteLLM for up-to-date pricing from all major providers
  - **Manual Overrides**: Administrators can add or edit pricing for custom models or enterprise agreements
  - **Fallback Mechanism**: Configurable default costs for unknown or newly released models
  - **Source Tracking**: Distinguish between LiteLLM-synced, manually entered, and system default pricing
  - **Audit Trail**: Full timestamp tracking for all pricing changes with last updated dates

* **Cost Configuration Tools**: Powerful administrative interface for cost management:
  - Inline editing of model pricing with immediate effect
  - Bulk pricing sync from LiteLLM with one-click updates
  - Protected manual entries (preserved during automatic syncs)
  - Configurable fallback pricing for cost predictability
  - Search and filter capabilities for large model catalogs
  - Visual badges distinguishing manual vs. automatic pricing

* **Token Usage Visibility**: Transparent token consumption tracking displayed for every LLM interaction, enabling users to understand the cost implications of their queries and optimize their usage patterns.

* **RAG Efficiency Tracking**: Cost savings metrics from RAG system reuse, showing cumulative cost saved through champion case retrieval and per-user cost savings attribution.

* **Multi-Provider Cost Comparison**: Compare actual spending across different LLM providers with identical workloads, enabling data-driven decisions for cost optimization and provider selection strategies.

The cost management system stores all pricing data locally in SQLite (`llm_model_costs` table) with encrypted credential storage, ensuring data sovereignty while providing enterprise-grade financial visibility. All cost-related REST API endpoints require admin authentication, ensuring secure access to financial data.

[⬆️ Back to Table of Contents](#table-of-contents)

---

### Collaborative Intelligence Marketplace

* **Dual Repository Sharing**: Share and discover both repository types through a unified marketplace:
  - **Planner Repositories (📋):** Proven execution patterns and strategies for task completion
  - **Knowledge Repositories (📄):** Reference documents and domain knowledge for planning context
  - Visual separation with dedicated tabs and distinct badges (blue for Planner, purple for Knowledge)

* **Smart Discovery & Search**: Find exactly what you need through powerful search and filtering:
  - Keyword search across collection names and descriptions
  - Filter by repository type (Planner vs. Knowledge)
  - Filter by visibility (Public, Unlisted)
  - Pagination for browsing large catalogs
  - View metadata: owner, subscriber count, ratings, case/document counts

* **Reference-Based Subscriptions**: Access shared collections without data duplication:
  - Subscribe to expert-curated collections with one click
  - Automatic integration into your RAG system
  - Planner retrieves cases from subscribed collections seamlessly
  - No storage overhead—references original collection
  - Unsubscribe anytime to manage your collection portfolio

* **Fork for Customization**: Create independent copies for your specific needs:
  - Full copy including embeddings, files, and metadata
  - Customize forked collections without affecting originals
  - Perfect for adapting community patterns to your domain
  - Iterative refinement through fork-and-improve workflow
  - Build on proven strategies while maintaining independence

* **Community Quality Assurance**: Trust community validation through ratings and reviews:
  - 1-5 star rating system with optional text reviews
  - Average ratings displayed on collection cards
  - Cannot rate own collections (ensures objectivity)
  - Browse top-rated collections for proven quality
  - Community feedback guides collection discovery

* **Flexible Publishing Options**: Share your expertise with granular visibility control:
  - **Public:** Fully discoverable in marketplace browse
  - **Unlisted:** Accessible via direct link only (share with specific teams)
  - **Private:** Owner-only access (default)
  - Update visibility anytime
  - Must have at least 1 RAG case/document to publish
  - Maintain full ownership and control

* **Cost Reduction Through Reuse**: Leverage proven patterns to minimize token consumption:
  - Reuse champion execution strategies instead of trial-and-error
  - Access domain expertise without rebuilding from scratch
  - Community-validated patterns reduce failed attempts
  - Lower onboarding costs for new users and use cases
  - Network effects: more users = more valuable patterns

* **Secure Access Control**: Enterprise-grade authorization and privacy:
  - JWT-authenticated API endpoints
  - Ownership validation on all operations
  - Cannot subscribe to own collections
  - Must be owner to publish or modify
  - Usernames visible for transparency and attribution
  - Privacy-first design with granular visibility controls

* **REST API Integration**: Programmatic marketplace operations for automation:
  - Browse collections with search/filter parameters
  - Subscribe/unsubscribe programmatically
  - Fork collections via API for CI/CD workflows
  - Publish collections as part of deployment pipelines
  - Rate collections for automated quality tracking
  - Full CRUD operations for marketplace management

The marketplace transforms the Uderia Platform from a single-user tool into a **collaborative intelligence platform**. By enabling pattern sharing, community validation, and knowledge reuse, it reduces costs, improves quality, and accelerates time-to-value for all users. Whether you're publishing your expertise or subscribing to community wisdom, the marketplace creates a powerful ecosystem where collective intelligence amplifies individual capabilities.

[⬆️ Back to Table of Contents](#table-of-contents)

---

### Two-Tier Repository Architecture

The application supports two distinct types of repositories, each serving a different purpose in the AI agent ecosystem:

#### Planner Repositories
**Purpose:** Store execution strategies and planning patterns
- Capture successful agent interactions as few-shot learning examples
- Contain SQL query patterns, API workflows, and proven execution traces
- Retrieved by the RAG system to guide future planning decisions
- Built via **Planner Repository Constructors** - modular templates for domain-specific pattern generation
- Automatically populated from agent execution history or manually via REST API
- Enable the agent to learn from past successes and improve over time
- **Available in Intelligence Marketplace** for community sharing and discovery

#### Knowledge Repositories
**Purpose:** Provide reference documentation and domain knowledge
- Store general documents, technical manuals, and business context
- Support for PDF, TXT, DOCX, MD, and other document formats
- Configurable chunking strategies (fixed-size, paragraph, sentence, semantic)
- Integrated with the planner via `_retrieve_knowledge_for_planning()` method
- Retrieved during planning to inject domain context into strategic decision-making
- Enable the agent to query relevant background information when making decisions
- **Available in Intelligence Marketplace** for community sharing and discovery
- **Feature Status:** ✅ Fully integrated (Phase 1 complete - Nov 2025)

#### Intelligence Marketplace

The **Intelligence Marketplace** enables users to share, discover, and leverage both repository types:

- **Browse Collections:** Search and filter by repository type (Planner or Knowledge)
- **Subscribe:** Reference-based subscriptions (no data duplication)
- **Fork:** Create independent copies for customization
- **Rate & Review:** Community-driven quality assurance (1-5 stars)
- **Publish:** Share collections as public (discoverable) or unlisted (link-only)
- **Visual Separation:** Dedicated tabs and badges distinguish Planner (📋 blue) from Knowledge (📄 purple)

This separation ensures that execution patterns (how to accomplish tasks) remain distinct from domain knowledge (what the agent needs to know), while both can be leveraged through the unified RAG system and shared via the marketplace.

[⬆️ Back to Table of Contents](#table-of-contents)

---

## 🎯 The Heart of the Application - The Engine & its Fusion Optimizer

The Uderia Platform is engineered to be far more than a simple LLM wrapper. Its revolutionary core is the **Fusion Optimizer**, a multi-layered engine designed for resilient, intelligent, and efficient task execution in complex enterprise environments. It transforms the agent from a mere tool into a reliable analytical partner.

### 🧠 The Multi-Layered Planning Process

The Optimizer deconstructs every user request into a sophisticated, hierarchical plan.

1. **Strategic Planner**: For any non-trivial request, the agent first generates a high-level **meta-plan**. This strategic blueprint outlines the major phases required to fulfill the user's goal, such as "Phase 1: Gather table metadata" followed by "Phase 2: Analyze column statistics."

2. **Tactical Execution**: Within each phase, the agent operates tactically, determining the single best next action (a tool or prompt call) to advance the plan.

3. **Recursive Delegation**: The Planner is fully recursive. A single phase in a high-level plan can delegate its execution to a new, subordinate instance of the Planner. This allows the agent to solve complex problems by breaking them down into smaller, self-contained sub-tasks, executing them, and then returning the results to the parent process.

### 🔧 Proactive Optimization Engine

Before and during execution, the Optimizer actively seeks to enhance performance and efficiency.

* **Plan Hydration**: The agent intelligently inspects a new plan to see if its initial steps require data that was already generated in the *immediately preceding turn*. If so, it "hydrates" the new plan by injecting the previous results, skipping redundant tool calls and delivering answers faster. This is particularly effective for follow-up clarifications and iterative refinements.

* **Tactical Fast Path**: For simple, single-tool phases where all required arguments are known, the Optimizer bypasses the tactical LLM call entirely and executes the tool directly, dramatically reducing latency. This eliminates unnecessary LLM calls for trivial interactions while maintaining conversational fluidity.

* **Specialized Orchestrators**: The agent is equipped with programmatic orchestrators to handle common complex patterns. For example, it can recognize a date range query (e.g., "last week") and automatically execute a single-day tool iteratively for each day in the range. The **Comparative Llama Invocation Orchestrator** executes deterministic prompt sequences across multiple LLMs, collects responses, and generates analytical comparisons for model behavior analysis.

* **Context Distillation**: To prevent context window overflow with large datasets, the agent automatically distills large tool outputs into concise metadata summaries before passing them to the LLM for planning, ensuring robust performance even with enterprise-scale data.

### 📚 RAG-Powered Continuous Improvement

The agent learns from every successful interaction, building an ever-growing repository of "champion" strategies that guide future planning. This closed-loop learning system transforms individual successes into organizational knowledge.

* **Automatic Case Capture**: Every completed session is analyzed and archived:
  - Full conversation history with query-response pairs
  - Complete tool invocation sequences with arguments
  - Strategic plan and tactical execution details
  - Token usage and cost metrics
  - Success indicators (no errors, user satisfaction signals)

* **Efficiency Analysis and Scoring**: Each case is evaluated for optimization potential:
  - Token reduction opportunities (e.g., plan hydration candidates)
  - Fast-path opportunities (e.g., queries that didn't need tools)
  - Tool selection improvements (e.g., more direct paths to answers)
  - Context management efficiency (e.g., Turn Summaries vs. Full Context)
  - Before/after cost comparison for savings attribution

* **Champion Strategy Selection**: The RAG system identifies best-in-class examples:
  - Lowest token count for similar query patterns
  - Fastest execution time for interactive workloads
  - Highest success rate for complex multi-step tasks
  - Most elegant tool orchestration sequences
  - User-endorsed solutions (via explicit feedback)

* **Few-Shot Learning Injection**: Planning-time retrieval enhances strategic decisions:
  - `_retrieve_similar_plans()` searches the Planner Repository for analogous cases
  - Top-K similar cases injected into strategic planner context
  - LLM leverages past successes to guide current planning
  - Continuous improvement without model retraining
  - Per-user savings attribution for efficiency tracking

* **Asynchronous Processing**: Zero user-facing latency:
  - Case archiving happens in background threads
  - RAG retrieval during planning overlaps with user response rendering
  - No blocking operations on critical path
  - Graceful degradation if RAG system unavailable

### 📊 Performance Metrics and Resource Limits

The engine provides comprehensive observability and built-in safeguards against runaway execution.

**Real-Time Performance Tracking:**

* **Token Consumption Monitoring**: Per-turn and cumulative tracking:
  - Input tokens (prompt + context + few-shot examples)
  - Output tokens (strategic plan + tactical steps + tool arguments + final response)
  - Token-to-cost mapping with provider-specific pricing
  - Historical trends and anomaly detection

* **Execution Time Profiling**: Detailed timing breakdown:
  - Strategic planning latency
  - Tactical loop execution time per iteration
  - Tool invocation duration (network + processing)
  - Response generation time
  - End-to-end query latency with percentile metrics

* **Resource Utilization**: System-level metrics:
  - Active session count and concurrency
  - MCP server connection pool status
  - ChromaDB vector store query performance
  - SQLite database read/write latency
  - Memory footprint per session

**Built-in Safeguards:**

* **Tactical Loop Iteration Limit**: Maximum 15 cycles per query to prevent infinite loops
* **Maximum Tool Invocations**: Cap on tool calls per tactical iteration to contain runaway execution
* **Context Window Management**: Automatic context pruning when approaching model limits
* **Timeout Enforcement**: Configurable query timeout with graceful degradation
* **Error Accumulation Threshold**: Abort after N consecutive tool failures to prevent thrashing

### 🔄 Autonomous Self-Correction & Healing

When errors occur, the Optimizer initiates a sophisticated, multi-tiered recovery process.

1. **Pattern-Based Correction**: The agent first checks for known, recoverable errors (e.g., "table not found," "column not found").

2. **Targeted Recovery Prompts**: For these specific errors, it uses highly targeted, specialized prompts that provide the LLM with the exact context of the failure and guide it toward a precise correction (e.g., "You tried to query table 'X', which does not exist. Here is a list of similar tables...").

3. **Generic Recovery & Replanning**: If the error is novel, the agent falls back to a generic error-handling mechanism or, in the case of persistent failure, can escalate to generating an entirely new strategic plan to achieve the user's goal via an alternative route.

4. **Strategic Correction with RAG**: The integrated **Retrieval-Augmented Generation (RAG)** system provides the highest level of self-healing. By retrieving "champion" strategies from past successes, the agent can discard a flawed or inefficient plan entirely and adopt a proven, optimal approach, learning from its own history to correct its course.

### 🛡️ Robust Safeguards

The Optimizer is built with enterprise-grade reliability in mind.

* **Deterministic Plan Validation**: Before execution begins, the agent deterministically validates the LLM-generated meta-plan for common structural errors (e.g., misclassifying a prompt as a tool) and corrects them, preventing entire classes of failures proactively.

* **Hallucination Prevention**: Specialized orchestrators detect and correct "hallucinated loops," where the LLM incorrectly plans to iterate over a list of strings instead of a valid data source. The agent semantically understands the intent and executes a deterministic, correct loop instead.

* **Definitive Error Handling**: The agent recognizes unrecoverable errors (e.g., database permission denied) and halts execution immediately, providing a clear explanation to the user instead of wasting resources on futile retry attempts.

[⬆️ Back to Table of Contents](#table-of-contents)

---

## 🧬 Retrieval-Augmented Generation (RAG) for Self-Improving AI

The Uderia Platform integrates a powerful **Retrieval-Augmented Generation (RAG)** system designed to create a self-improving agent. This closed-loop feedback mechanism allows the agent's Planner to learn from its own past successes, continuously enhancing its decision-making capabilities over time.

The core value of this RAG implementation is its ability to automatically identify and leverage the most efficient strategies for given tasks. It works by:

1.  **Capturing and Archiving:** Every successful agent interaction is captured and stored as a "case study."
2.  **Analyzing Efficiency:** The system analyzes each case based on token cost to determine its efficiency.
3.  **Identifying Champions:** It identifies the single "best-in-class" or "champion" strategy for any given user query.
4.  **Augmenting Future Prompts:** When a similar query is received in the future, the system retrieves the champion case and injects it into the Planner's prompt as a "few-shot" example.

This process guides the Planner to generate higher-quality, more efficient plans based on proven, successful strategies, reducing token consumption and improving response quality without manual intervention. The entire process runs asynchronously in the background to ensure no impact on user-facing performance.

### Planner Repository Constructors: Modular Plugin System (New - Nov 2025)

The RAG system now features a **modular template architecture** that enables domain-specific customization and extensibility:

* **Plugin-Based Design**: Templates are self-contained plugins with their own schemas, validation logic, and population strategies
* **Template Types**: Support for SQL query templates, with extensibility for document Q&A, API workflows, and custom domains
* **Manifest System**: Each template declares its capabilities, required fields, and validation rules via a standardized manifest
* **Dynamic Registration**: Templates are automatically discovered and registered at runtime from the `rag_templates/` directory
* **Programmatic & LLM-Assisted Population**: Templates can be populated via REST API with structured examples or through LLM-assisted generation in the UI
* **Auto-Generation**: Built-in LLM workflows to automatically generate domain-specific examples from database schema or documentation

This modular approach allows organizations to extend the RAG system with custom templates tailored to their specific data patterns, query types, and business domains without modifying core agent code.

For a comprehensive overview of the RAG architecture, template development, and maintenance utilities, please see the detailed documentation:
[**RAG System Documentation (docs/RAG/RAG.md)**](docs/RAG/RAG.md)  
[**RAG Template Plugin Development (rag_templates/README.md)**](rag_templates/README.md)

[⬆️ Back to Table of Contents](#table-of-contents)

---

## 🏗️ How It Works: Architecture

### System Overview

The Uderia Platform is built on a modern, asynchronous client-server architecture with four primary layers:

```
┌──────────┐      ┌─────────────┐      ┌──────────┐      ┌─────┐      ┌─────────┐
│  Browser │ SSE  │   Backend   │ HTTP │   LLM    │ HTTP │ MCP │ SQL  │ Data    │
│   (UI)   │◄────►│   (Quart)   │─────►│ Provider │      │ Svr │─────►│ Source  │
└──────────┘      └─────────────┘      └──────────┘      └─────┘      └─────────┘
```

**Communication Flow:**
1. User sends query via browser → Backend receives via REST/SSE
2. Backend orchestrates → LLM generates plan
3. LLM requests tools → MCP Server executes against data source
4. Results flow back → Backend formats → Browser renders in real-time

### Component Layers

#### Frontend Layer
- **Technology:** Single-page app (Vanilla JS, Tailwind CSS, HTML)
- **Communication:** REST API for requests, Server-Sent Events (SSE) for real-time updates
- **Key Features:** Live status monitoring, session management, context controls
- **State Management:** Browser localStorage (respects server persistence settings)

#### Backend Layer (`src/trusted_data_agent/`)
- **Technology:** Quart (async Python web framework)
- **Responsibilities:** 
  - Session management and user isolation
  - LLM orchestration with Fusion Optimizer engine
  - Configuration management and credential handling
  - RAG system integration
- **Key Modules:**
  - `api/` - REST endpoints and SSE handlers
  - `agent/` - Executor, Formatter, and planning logic
  - `llm/` - Multi-provider LLM connectors
  - `mcp/` - MCP protocol client
  - `core/` - Configuration, sessions, utilities

#### LLM Integration Layer
- **Supported Providers:** Google (Gemini), Anthropic (Claude), OpenAI, Azure OpenAI, AWS Bedrock, Friendli.AI, Ollama
- **Authentication:** Dynamic credential handling per session
- **Protocol:** REST API calls with structured prompts (system + user + tools)

#### MCP Integration Layer
- **Protocol:** Model Context Protocol - standardized tool/prompt/resource exposure
- **Connection:** HTTP/WebSocket to MCP Server
- **Security:** Credential passthrough, no credential storage in agent

### Data Flow & Session Management

**Authentication Flow:**
1. User logs in → Backend validates credentials
2. JWT token issued (24-hour expiry) → Stored in browser localStorage as `tda_auth_token`
3. All API requests include `Authorization: Bearer <token>` header
4. Token refreshed automatically or user re-authenticates

**Configuration Flow:**
1. User enters credentials (LLM + MCP) → Validated by backend
2. Credentials encrypted using Fernet → Stored per-user in `tda_auth.db`
3. MCP/LLM profiles created → Associated with user account
4. Configuration persists across sessions (user-specific)

**Query Execution Flow:**
1. User query → Backend authenticates JWT → Creates/loads session
2. Backend invokes Fusion Optimizer with context (conversation history + workflow summaries)
3. Optimizer generates strategic plan → Executes via LLM + MCP tools
4. Results streamed via SSE → UI updates in real-time
5. Session persisted with turn history and summaries

**Session Isolation:**
- Each user identified by database user ID (from JWT token)
- Sessions stored in `tda_sessions/{session_id}/` with conversation and workflow history
- User credentials isolated in encrypted database storage
- Multi-user support: Multiple users can access simultaneously with separate sessions

**Deployment Architectures:**

**Single-User (Development):**
```
Local Machine → Python Process → localhost:5050
```

**Multi-User (Production):**
```
Option 1: Load Balancer → Multiple Container Instances (port 5050, 5051, 5052...)

```

**Security Considerations:**

- **Credentials:** LLM/MCP credentials never logged or exposed in UI
- **Isolation:** Session data segregated by user UUID
- **Transport:** HTTPS recommended for production (configure via reverse proxy)


[⬆️ Back to Table of Contents](#table-of-contents)

---

## 📦 Installation and Setup Guide

### Prerequisites

* **Python 3.8+** and `pip`.

* Access to a running **MCP Server**.

* An **API Key** from a supported LLM provider or a **local Ollama installation**. The initial validated providers are **Google**, **Anthropic**, **Amazon Web Services (AWS)**, **Friendli.AI**, and **Ollama**.

  * You can obtain a Gemini API key from the [Google AI Studio](https://aistudio.google.com/app/apikey).

  * You can obtain a Claude API key from the [Anthropic Console](https://console.anthropic.com/dashboard).

  * For **Azure**, you will need an **Azure OpenAI Endpoint**, **API Key**, **API Version**, and a **Model Deployment Name**.

  * For AWS, you will need an **AWS Access Key ID**, **Secret Access Key**, and the **Region** for your Bedrock service.

  * You can obtain a Friendli.AI API key from the [Friendli Suite](https://suite.friendli.ai/).

  * For Ollama, download and install it from [ollama.com](https://ollama.com/) and pull a model (e.g., `ollama run llama2`).

### Step 1: Clone the Repository

```
git clone https://github.com/rgeissen/uderia.git
cd uderia

```

### Step 2: Set Up the Python Environment

It is highly recommended to use a Python virtual environment.

**Option A: Using Python venv**

1. **Create and activate a virtual environment:**

   ```
   # For macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   
   # For Windows
   python -m venv venv
   .\venv\Scripts\activate
   
   ```

2. **Install the required packages:**

   ```
   pip install -r requirements.txt
   
   ```

**Option B: Using Conda (Recommended for consistent environments)**

1. **Create and activate a conda environment:**

   ```
   conda create -n tda python=3.13
   conda activate tda
   
   ```

2. **Install the required packages:**

   ```
   pip install -r requirements.txt
   
   ```

### Step 3: 🔐 Regenerate JWT Secret Key (Security)

> **⚠️ CRITICAL SECURITY STEP**

The application ships with a default JWT secret key for user authentication. You **must** regenerate this key for your installation to ensure security.

```bash
python maintenance/regenerate_jwt_secret.py
```

This will:
- Generate a new unique JWT secret key for your installation
- Save it to `tda_keys/jwt_secret.key` with secure permissions (600)
- Ensure your user authentication tokens cannot be forged

**Note:** If you skip this step, your installation will use the default key, which is a **security risk**.

### Step 4: Create the Project Configuration File

In the project's root directory, create a new file named `pyproject.toml`. This file is essential for Python to recognize the project structure.

Copy and paste the following content into `pyproject.toml`:

```
[project]
name = "uderia"
version = "0.1.0"
requires-python = ">=3.8"

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

```

### Step 5: Install the Application in Editable Mode

This crucial step links your source code to your Python environment, resolving all import paths. **Run this command from the project's root directory.**

```
pip install -e .

```

The `-e` flag stands for "editable," meaning any changes you make to the source code will be immediately effective without needing to reinstall.

### Step 6: Bootstrap Configuration (Optional)

The application uses a **bootstrap configuration system** with `tda_config.json` as a read-only template. This file provides default profiles, MCP servers, and LLM configurations that are copied to each user on their first login.

**Understanding the Bootstrap System:**

- **tda_config.json** - Read-only template containing default configurations
- **First Login** - Configuration is copied from template to user's database record
- **Per-User Storage** - All subsequent changes are stored in the user's database (isolated from other users)
- **Future Users** - New users automatically receive the current template configuration
- **Admin Customization** - Administrators can modify `tda_config.json` to customize defaults for future users

**Default Bootstrap Configuration:**

The template includes:
- **2 Profiles**: Google "Reduced Stack" (GOGET, default) and Friendly AI "Reduced Stack" (FRGOT)
- **1 MCP Server**: Teradata MCP (requires configuration of host/port)
- **6 LLM Configurations**: Google, Anthropic, OpenAI, Azure, AWS Bedrock, Friendli.AI (require API keys)
- **30 Tools** and **1 Prompt** enabled by default in profiles

**Customizing the Bootstrap (Optional):**

Before starting the application for the first time, you can customize `tda_config.json` to pre-configure settings for all future users:

1. **Edit `tda_config.json`** in the project root
2. **Modify MCP Servers** - Add your production MCP server connection details
3. **Adjust Profiles** - Change default profiles, tools, or prompts
4. **Set LLM Defaults** - Pre-configure LLM provider settings (API keys should still be entered per-user)

**⚠️ Important Notes:**
- Changes to `tda_config.json` **only affect new users** created after the modification
- Existing users retain their database-stored configuration (not affected by template changes)
- Each user's configuration is **completely isolated** - changes by one user don't affect others
- The application **never modifies** `tda_config.json` - it remains a read-only template

### Step 7: Start the Application

The application uses a **multi-user authentication system** with JWT tokens and encrypted credential storage. Authentication is **always required** for all users.

**Run the application:**

```bash
python -m trusted_data_agent.main
```

The application will:
- Automatically create `tda_auth.db` (SQLite database with encrypted credentials)
- Initialize default admin account: `admin` / `admin` (⚠️ **change immediately!**)
- Start the web server on `http://localhost:5050`

### Step 8: First Login and Security

1. **Open your browser** to `http://localhost:5050`
2. **Login** with default credentials: `admin` / `admin`
3. **⚠️ IMPORTANT:** Immediately change the admin password in the **Administration** panel
4. **Bootstrap Applied** - On first login, your account receives the template configuration from `tda_config.json`
5. **Configure Setup** - Complete your setup in the **Setup** panel:
   - Add API keys for LLM providers
   - Configure MCP server connection details (host, port, path)
   - Enable/disable profiles as needed
6. **Create User Accounts** - Admin users can create additional users (each receives the bootstrap configuration)

**Authentication Features:**
- ✅ JWT tokens (24-hour expiry) for web UI sessions
- ✅ Long-lived access tokens for REST API automation
- ✅ Per-user credential encryption using Fernet
- ✅ User tiers: `user`, `developer`, `admin`
- ✅ Soft-delete audit trail for revoked tokens
- ✅ Session management with persistent context
- ✅ Bootstrap configuration copied to each user on first login
- ✅ Consumption profile enforcement with granular usage quotas
- ℹ️ Rate limiting disabled by default (configurable in Administration → App Config)

---

### Consumption Profiles and Usage Quotas

The Uderia Platform includes a comprehensive **consumption profile enforcement system** that provides granular control over resource usage across different user tiers and deployment scenarios.

#### Overview

Consumption profiles enable administrators to:
- Set per-user rate limits on prompts (hourly and daily)
- Enforce monthly token quotas (input and output tokens tracked separately)
- Control configuration change frequency
- Test profiles before activation
- Override profiles with global emergency limits
- Track usage in real-time with detailed audit trails

#### Predefined Profile Tiers

Four consumption profiles are available out-of-the-box:

| Profile | Prompts/Hour | Prompts/Day | Input Tokens/Month | Output Tokens/Month | Config Changes/Hour |
|---------|--------------|-------------|-------------------|---------------------|---------------------|
| **Free** | 50 | 500 | 100,000 | 50,000 | 5 |
| **Pro** | 200 | 2,000 | 500,000 | 250,000 | 10 |
| **Enterprise** | 500 | 5,000 | 2,000,000 | 1,000,000 | 20 |
| **Unlimited** | 1,000 | 10,000 | ∞ | ∞ | 50 |

By default, new users receive the **Unlimited** profile. Administrators can change the default profile or assign specific profiles to individual users.

#### Profile Management

**Administrators can:**
- Create and configure custom consumption profiles
- Assign profiles to specific users
- Activate/deactivate profiles for testing without deleting them
- View real-time consumption statistics per user
- Set global override mode for emergency rate limiting

**Profile Testing:**
Each profile includes a **"Toggle Active for Consumption"** button that:
1. Temporarily activates the profile for testing
2. Classifies and validates profile configuration
3. Shows real-time enforcement without affecting other users
4. Allows safe testing before production deployment

#### Rate Limiting Configuration

Access rate limiting controls through **Administration → App Config → Security & Rate Limiting**:

**Enable Rate Limiting:**
- Master switch for all consumption enforcement
- Must be enabled for profiles to work
- Disabled by default for single-user installations

**Global Override Mode:**
- Emergency toggle to override ALL user profiles
- Forces global limits on all users (including Enterprise/Unlimited)
- Per-user fallback limits applied when profiles aren't assigned
- Useful for system-wide capacity management

**Per-User Limits (when Global Override is enabled):**
- Prompts per Hour (default: 100)
- Prompts per Day (default: 1,000)
- Configuration Changes per Hour (default: 10)

**Per-IP Limits (always enforced for anonymous traffic):**
- Login attempts per minute
- Registrations per hour
- API calls per minute

#### Enforcement Behavior

**For authenticated users:**
1. **Admin users** bypass all consumption limits
2. **Regular users** with profiles assigned → profile limits enforced
3. **Users without profiles** → falls back to default profile or global limits
4. **Global override enabled** → overrides all profiles with global settings

**Error handling:**
- Clear error messages when limits are exceeded
- Retry-after information in responses
- Fail-open design: allows execution if enforcement check fails
- Full audit trail in logs and database

#### Usage Tracking and Reporting

The system maintains detailed consumption records:
- **Per-turn tracking** - Individual prompt costs and token usage
- **Session aggregation** - Cumulative costs per conversation
- **User summaries** - Total consumption across all sessions
- **Historical trends** - Month-over-month usage analytics
- **Audit trail** - Complete record of all consumption events

View consumption details through:
- **Dashboard** - Real-time cost and usage overview
- **REST API** - Programmatic access to consumption data
- **Database exports** - Complete audit trail for compliance

#### Best Practices

**For single-user installations:**
- Leave rate limiting disabled (default)
- Use Unlimited profile for maximum flexibility

**For team deployments:**
- Enable rate limiting
- Assign profiles based on user roles
- Use Global Override for emergency capacity management
- Monitor consumption trends through Dashboard

**For testing:**
- Use "Toggle Active for Consumption" to test profiles
- Set low limits (1 prompt/hour) to verify enforcement
- Check logs for detailed enforcement flow
- Test with non-admin users for accurate results

**For production:**
- Enable rate limiting before go-live
- Set appropriate default profile for new users
- Monitor consumption patterns and adjust profiles
- Use token quotas to manage monthly costs
- Review audit logs periodically for anomalies

---

**Supported LLM Providers:**
- AWS Bedrock (requires: Access Key, Secret Key, Region)
- Anthropic Claude (requires: API Key)
- OpenAI (requires: API Key)
- Google Gemini (requires: API Key)
- Azure OpenAI (requires: Endpoint, API Key, Deployment Name)
- Friendli.AI (requires: API Key)
- Ollama (local - requires: Ollama installation)

### Running the Application

**Important:** All commands must be run from the project's **root directory**.

#### Standard Mode

For standard operation with the certified models:

```
python -m trusted_data_agent.main

```

[⬆️ Back to Table of Contents](#table-of-contents)

---

## Developer Mode: Unlocking Models

To enable all discovered models for testing and development purposes, start the server with the `--all-models` flag.

```
python -m trusted_data_agent.main --all-models

```

**Note:** **No Ollama models are currently certified.** For testing purposes, Ollama models can be evaluated by starting the server with the `--all-models` developer flag.

[⬆️ Back to Table of Contents](#table-of-contents)

---

## 📖 User Guide

This comprehensive guide covers everything you need to know to use the Uderia Platform effectively, from basic operations to advanced features and automation.

---

### Getting Started

#### Prerequisites Before First Use

⚠️ **Important:** Before you can start conversations with the agent, you must complete the initial configuration. The agent requires three components to function:

1. **MCP Server Connection** - Where your data and tools live
2. **LLM Provider Configuration** - The AI model that powers the agent
3. **Profile Creation** - Combines MCP + LLM into a usable configuration

Without these configurations, the **"Start Conversation"** button will remain disabled.

#### Initial Configuration

The Uderia Platform uses a modern, modular configuration system that separates infrastructure (MCP Servers, LLM Providers) from usage patterns (Profiles). This architecture provides maximum flexibility for different use cases.

**Configuration Flow:** MCP Servers → LLM Providers → Profiles → Start Conversation

##### Step 1: Configure MCP Servers

1. **Login:** Navigate to `http://localhost:5050` and login with your credentials.

2. **Navigate to Setup:** Click on the **Setup** panel in the left sidebar (person icon).

3. **MCP Servers Tab:** Select the "MCP Servers" tab and configure one or more MCP Server connections:
   - **Name:** A friendly identifier for this server (e.g., "Production Database", "Dev Environment")
   - **Host:** The hostname or IP address of your MCP Server
   - **Port:** The port number (e.g., 8888)
   - **Path:** The endpoint path (e.g., /mcp)

4. **Save:** Click "Add MCP Server" to save. You can configure multiple servers for different environments.

##### Step 2: Configure LLM Providers

1. **LLM Providers Tab:** Configure one or more LLM provider connections:
   - **Name:** A descriptive name (e.g., "Google Gemini 2.0", "Claude Sonnet")
   - **Provider:** Select from Google, Anthropic, OpenAI, Azure, AWS Bedrock, Friendli.AI, or Ollama
   - **Model:** Choose a specific model from the provider
   - **Credentials:** Enter required authentication details:
     - **Cloud providers:** API Key
     - **Azure:** Endpoint URL, API Key, API Version, Deployment Name
     - **AWS:** Access Key ID, Secret Access Key, Region
     - **Ollama:** Host URL (e.g., `http://localhost:11434`)

2. **Fetch Models:** Click the refresh icon to retrieve available models from your provider.

3. **Save:** Click "Add LLM Configuration" to save. You can configure multiple LLM providers to compare performance.

##### Step 3: Create Profiles

Profiles combine an MCP Server with an LLM Provider to create named configurations for different use cases.

1. **Profiles Tab:** After configuring at least one MCP Server and one LLM Provider, create profiles:
   - **Profile Name:** Descriptive name (e.g., "Production Analysis", "Cost-Optimized Research")
   - **Tag:** Short identifier for quick selection (e.g., "PROD", "COST") - used for temporary overrides
   - **MCP Server:** Select which MCP Server this profile uses
   - **LLM Provider:** Select which LLM configuration this profile uses
   - **Description:** Optional details about when to use this profile
   - **Set as Default:** Mark one profile as the default for all queries

2. **Active for Consumption:** Toggle which profiles are available for temporary override selection (see below).

3. **Save:** Click "Add Profile" to create the profile.

##### Step 4: Start Conversation

1. Navigate back to the **Conversations** panel using the left sidebar (chat icon).

2. Click the **"Start Conversation"** button to activate your default profile.

3. The application will:
   - Validate your MCP Server connection
   - Authenticate with your LLM provider
   - Load all available tools, prompts, and resources from the MCP Server
   - Display them in the **Capabilities Panel** at the top
   - Enable the chat input for you to start asking questions

**✅ You're Ready!** Once you see the capabilities loaded and the chat input is active, you can start interacting with your data through natural language queries.

**Example First Query:** `"What databases are available?"` or `"Show me all tables in the DEMO_DB database"`

---

### Using the Interface

#### Navigation and Panel Structure

The application provides a multi-panel interface accessible through the left sidebar navigation. Click the hamburger menu (☰) in the top-left to expand/collapse the sidebar.

**Available Panels:**

1. **Conversations** - Main conversational interface with the agent
2. **Executions** - Real-time dashboard for monitoring all agent tasks
3. **Intelligence** - Manage knowledge base collections and Planner Repository Constructors
4. **Marketplace** - Browse and install Planner Repository Constructors from the community
5. **Setup** - Configure LLM providers, MCP Servers, and profiles
6. **Administration** - User management and system settings (admin only)

#### The Conversation Panel

When you select the **Conversations** panel, the interface is organized into several key areas:

* **Session History (Left):** Lists all your conversation sessions. Click to switch between sessions or start a new conversation with the "+" button.

* **Capabilities Panel (Top):** Your library of available actions from the connected MCP Server, organized into tabs:

  * **Tools:** Single-action functions the agent can call (e.g., `base_tableList`)
  
  * **Prompts:** Pre-defined, multi-step workflows the agent can execute (e.g., `qlty_tableQualityReport`)
  
  * **Resources:** Other available assets from the MCP Server

* **Chat Window (Center):** Where your conversation with the agent appears, showing both user queries and agent responses.

* **Chat Input (Bottom):** Type your questions in natural language here. Supports profile overrides and voice input.

* **Live Status Panel (Right):** The transparency window showing real-time logs of the agent's internal reasoning, tool executions, and raw data responses.

#### The Executions Panel

The **Executions** panel provides a comprehensive, real-time dashboard for monitoring all agent workloads across the application:

* **Task List:** View all running, completed, and failed tasks with their status, duration, and resource usage
* **Real-time Updates:** Tasks automatically update as they progress through stages (planning, execution, synthesis)
* **Detailed Execution View:** Click any task to see its full execution log, including:
  - Agent reasoning and planning steps
  - Tool invocations and responses
  - Error messages and stack traces
  - Token usage and cost estimates
* **Task Control:** Cancel running tasks or retry failed executions
* **Cross-Source Monitoring:** Track tasks initiated from the UI, REST API, or scheduled workflows

This panel is especially valuable for monitoring REST API-triggered workloads and debugging complex agent behaviors.

#### The Intelligence Panel

The **Intelligence** panel is your control center for managing both types of repositories in the system:

* **Planner Repositories:**
  - Execution strategies and planning patterns from successful agent interactions
  - View, create, update, or delete collections
  - Inspect individual execution traces and their embeddings
  - Bulk import/export collection data
  - Automatically populated from agent executions or via Planner Repository Constructors
  
* **Knowledge Repositories:**
  - General documents and reference materials for planning context
  - Upload PDF, TXT, DOCX, MD files with configurable chunking strategies
  - View document metadata, chunk counts, and storage details
  - Delete documents or entire collections
  - Search within Knowledge repositories using semantic similarity
  - **Fully integrated** with planner for domain context retrieval
  
* **Planner Repository Constructors:**
  - Browse installed constructors (templates for building Planner Repositories)
  - Configure constructor parameters and populate collections
  - LLM-assisted auto-generation from database schemas or documentation
  - View usage statistics and manage constructor lifecycle
  - Enable/disable specific constructors

* **Content Operations:**
  - Generate contextual questions for documents
  - Populate collections with new content via manual or automated workflows
  - Provide feedback on RAG retrieval quality
  - Preview document chunking before committing
  - Clean orphaned or invalid entries

For detailed RAG workflows and maintenance procedures, see the [RAG Maintenance Guide](maintenance/RAG_MAINTENANCE_GUIDE.md).

#### The Marketplace Panel

The **Intelligence Marketplace** enables discovery and sharing of both Planner and Knowledge repositories:

* **Repository Type Separation:**
  - **Planner Repositories Tab (📋):** Execution patterns and strategies for proven task completion
  - **Knowledge Repositories Tab (📄):** Reference documents and domain knowledge for planning context
  - Visual badges and dedicated tabs for clear distinction
  
* **Collection Discovery:**
  - Browse public collections or search by keywords
  - Filter by repository type, visibility (public/unlisted), and rating
  - Pagination support for large catalogs
  - View owner, subscriber count, ratings, and collection metadata

* **Collection Operations:**
  - **Subscribe:** Reference collections without data duplication
  - **Fork:** Create independent copies for customization (includes embeddings and files)
  - **Rate & Review:** Community quality assurance (1-5 stars with optional reviews)
  - **Publish:** Share your collections as public (discoverable) or unlisted (link-only)

* **My Collections View:**
  - Manage your owned collections
  - Track subscriptions and usage
  - Update visibility and metadata
  - Monitor subscriber counts and ratings

The marketplace transforms isolated knowledge bases into a collaborative ecosystem where users benefit from proven execution patterns and domain expertise, reducing token costs and improving response quality.

#### The Setup Panel

The **Setup** panel is where you configure all external connections and create profiles. This is typically the first panel you'll use when setting up the application:

* **MCP Servers Tab:**
  - Configure Model Context Protocol server connections
  - Test server connectivity and capability discovery
  - Manage server-specific settings and parameters

* **LLM Providers Tab:**
  - Add connections to Google, Anthropic, OpenAI, Azure, AWS Bedrock, Friendli.AI, or Ollama
  - Configure API keys, endpoints, and authentication
  - Test model availability and fetch model lists
  - Compare multiple providers side-by-side

* **Profiles Tab:**
  - Create named profiles combining MCP servers with LLM providers
  - Set default profiles and configure profile tags for quick switching
  - Enable/disable profiles for temporary override selection
  - Manage profile-specific settings and descriptions

* **Advanced Settings Tab:**
  - **Access Token Management:** Create, view, and revoke long-lived API tokens for REST API automation
  - **Token Security:** Tokens are shown only once at creation and stored as SHA256 hashes
  - **Usage Tracking:** Monitor token usage with last used timestamps, use counts, and IP addresses
  - **Audit Trail:** Revoked tokens remain visible with revocation dates for compliance and forensics
  - **Charting Configuration:** Toggle chart rendering on/off and configure charting intensity levels

All credential data is encrypted using Fernet encryption and stored securely in the user database.

#### The Administration Panel

The **Administration** panel provides system-level management capabilities (visible only to admin users):

* **User Management:**
  - Create, modify, and deactivate user accounts
  - Assign roles and permissions
  - Monitor user activity and session history
  - Reset passwords and manage authentication

* **System Configuration:**
  - Configure application-wide settings
  - Manage logging levels and retention
  - Set resource limits and quotas
  - Monitor system health and performance

* **Audit Logs:**
  - View all system activities and changes
  - Track API usage and access patterns
  - Export audit data for compliance reporting

#### Quick Navigation Tips

* **Sidebar Toggle:** Click the hamburger menu (☰) or use keyboard shortcut to expand/collapse the navigation sidebar
* **Panel Switching:** Click any panel name in the sidebar to instantly switch views
* **Multi-Panel Workflow:** Open the Setup panel to configure connections, then switch to Conversations to start chatting
* **Monitoring While Working:** Keep the Executions panel open in a separate browser tab to monitor long-running tasks
* **Keyboard Shortcuts:** Use `Ctrl/Cmd + Number` to jump directly to panels (where supported)

**Example Workflow:**
1. **Setup** → Configure LLM providers and MCP servers → Create profiles
2. **Marketplace** → Browse and install Planner Repository Constructors for your domain
3. **Intelligence** → Populate knowledge collections with your knowledge base
4. **Conversations** → Start chatting with the agent using your enriched context
5. **Executions** → Monitor task progress and review execution logs

---

#### Asking Questions

Simply type your request into the chat input at the bottom of the **Conversations** panel and press Enter.

* **Example:** `"What tables are in the DEMO_DB database?"`

The agent will analyze your request using your **default profile**, display its thought process in the **Live Status** panel, execute the necessary tool (e.g., `base_tableList`), and then present the final answer in the chat window.

#### Temporary Profile Override

The profile system allows you to temporarily switch to a different LLM provider for a single query without changing your default configuration. This is powerful for:
- **Testing:** Compare how different LLMs handle the same question
- **Cost Optimization:** Use cheaper models for simple queries, premium models for complex analysis
- **Specialized Tasks:** Route specific query types to models optimized for that domain

**How to Use Profile Override:**

1. **Type `@` in the question box** - A dropdown appears showing all profiles marked as "Active for Consumption"

2. **Select a profile** - The default profile appears first (non-selectable), followed by available alternatives:
   - Use **arrow keys** to navigate
   - Press **Tab** or **Enter** to select
   - Or **click** on a profile

3. **Profile badge appears** - A colored badge shows the active override profile with the provider color

4. **Type your question** - The query will be executed using the selected profile's LLM provider

5. **Remove override** - Click the **×** on the badge or press **Backspace** (when input is empty) to revert to the default profile

**Visual Indicators:**
- **Question Box Badge:** Shows the temporary override profile with provider-specific colors
- **Session Header:** Displays both the default profile (★ icon) and override profile (⚡ icon with subtle animation)
- **Color Coding:** Each LLM provider has a distinct color (Google=blue, Anthropic=purple, OpenAI=green, etc.)

**Example Workflow:**
```
1. Default: "Google Gemini 2.0" profile
2. Type: @CLAUDE <Tab>
3. Badge shows: @CLAUDE (purple)
4. Ask: "Analyze the performance metrics"
5. Query uses Claude instead of Gemini
6. Click × to return to default
```

#### Using Prompts Manually

You can directly trigger a multi-step workflow without typing a complex request.

1. Go to the **Capabilities Panel** and click the **"Prompts"** tab.

2. Browse the categories and find the prompt you want to run (e.g., `base_tableBusinessDesc`).

3. Click on the prompt. A modal will appear asking for the required arguments (e.g., `db_name`, `table_name`).

4. Fill in the arguments and click **"Run Prompt"**.

The agent will execute the entire workflow and present a structured report.

#### Customizing the Agent's Behavior

You can change how the agent thinks and behaves by editing its core instructions (available in the **Conversations** panel).

1. Click the **"System Prompt"** button in the conversation header.

2. The editor modal will appear, showing the current set of instructions for the selected model.

3. You can make any changes you want to the text.

4. Click **"Save"** to apply your changes. The agent will use your new instructions for all subsequent requests in the session.

5. Click **"Reset to Default"** to revert to the original, certified prompt for that model.

#### Direct Chat with the LLM

To test the raw intelligence of a model without the agent's tool-using logic, you can use the direct chat feature (available in the **Conversations** panel).

1. Click the **"Chat"** button in the conversation header.

2. A modal will appear, allowing you to have a direct, tool-less conversation with the currently configured LLM. This is useful for evaluating a model's baseline knowledge or creative capabilities.

---

### Advanced Context Management

The Uderia Platform provides several advanced features for managing the context that is sent to the Large Language Model (LLM). Understanding and using these features can help you refine the agent's behavior, save costs by reducing token count, and get more accurate results.

### Understanding Context Elements

The agent's "memory" is composed of three distinct context elements:

1.  **LLM Conversation History (`chat_object`):** This is the raw, turn-by-turn dialogue between you and the agent. It provides the immediate conversational context, allowing the agent to understand follow-up questions and references to previous messages.

2.  **Chat History (`session_history`):** This history is used exclusively for rendering the conversation in the user interface. It is **not** sent to the LLM for context.

3.  **Turn Summaries (`workflow_history`):** This is a structured summary of the agent's actions. For each turn, it includes the plan that was generated, the tools that were executed, and a summary of the results. This history is sent to the agent's **planner** to help it make better decisions and learn from past actions.

### Context Management Features

You have several ways to control the agent's context directly from the UI:

#### Activate/Deactivate Turn Context

You can activate or deactivate the context of any individual turn by clicking on the small numbered badge that appears on the user ("U") and assistant ("A") avatars.

*   **Clicking a badge** will toggle the `isValid` status for that entire turn.
*   **Inactive turns** are visually dimmed and their conversational history is **completely excluded** from the context sent to the LLM. This is a powerful way to surgically remove parts of the conversation that might be confusing the agent.

#### Purge Context

You can deactivate all previous turns at once by clicking the **Context Indicator** dot in the main header (next to the "MCP" and "LLM" indicators).

*   **Clicking the dot** will prompt you for confirmation.
*   **Upon confirmation,** all past turns in the session will be marked as inactive (`isValid = false`), and the indicator will blink white three times. This effectively resets the agent's conversational and planning memory, forcing it to start fresh from your next query.

#### Replay Original Query

You can re-execute the original query for any turn by **clicking and holding** the assistant ("A") avatar for that turn.

*   **Press and hold for 1.5 seconds.** A circular animation will appear to indicate the action.
*   Upon completion, the agent will re-run the original user query for that turn, generating a brand new plan. This is useful for retrying a failed turn or exploring an alternative approach.

### Context Modes

The agent provides two primary modes for handling conversational history, allowing you to control the context sent to the LLM for each query. You can see the current mode in the hint text below the chat input bar.

**Important Note:** In both modes, only turns that are currently **active** (`isValid = true`) are included in the context. Deactivated turns are completely ignored by the LLM and the planner.

#### Full Session Context Mode (Default)

In this mode, the agent maintains a complete conversational memory. It sends the **LLM Conversation History (`chat_object`)** from all active turns with each new request.

*   **Best for:** Conversational queries, follow-up questions, and tasks that require the agent to remember the back-and-forth of the dialogue.
*   **Impact:** Uses more tokens, as the conversation history from all active turns is included in the context.

#### Turn Summaries Mode

When activated, this mode disables the **LLM Conversation History**. The agent becomes conversationally "stateless" but still operates with full knowledge of its past actions from active turns.

*   **What it sends:**
    1.  The Current User Prompt.
    2.  The **Turn Summaries (`workflow_history`)** from all active turns.
    3.  The full System Prompt (including all available tools).
*   **Best for:** "One-shot" commands, saving tokens, or preventing a long, complex conversation from confusing the planner.
*   **How to activate:**
    *   **Hold `Alt`** while sending a message to use it for a single query.
    *   **Press `Shift` + `Alt`** to lock the mode on for subsequent queries.

---

### REST API Integration

The Uderia Platform includes a powerful, asynchronous REST API to enable programmatic control, automation, and integration into larger enterprise workflows.

This API exposes the core functionalities of the agent, allowing developers to build custom applications, automate complex analytical tasks, and manage the agent's configuration without using the web interface.

**Authentication:**

The REST API uses **Bearer token authentication** for all protected endpoints. You have two authentication options:

1. **JWT Tokens (Web UI):** 24-hour tokens automatically issued when you log in to the web interface
2. **Access Tokens (REST API):** Long-lived tokens created in the **Advanced Settings** panel for automation

**Creating Access Tokens:**

1. Navigate to **Setup** → **Advanced Settings**
2. Click **"Create Token"**
3. Provide a descriptive name (e.g., "Production Server", "CI/CD Pipeline")
4. Set expiration (default: 90 days, or never expires)
5. **Copy the token immediately** - it's shown only once!
6. Store securely (e.g., environment variables, secrets manager)

**Using Access Tokens:**

```bash
# Set your token as an environment variable
export TDA_ACCESS_TOKEN="tda_9DqZMBXh-OK4H4F7iI2t3EcGctldT-iX"

# Use with example scripts
./docs/RestAPI/scripts/rest_run_query.sh "$TDA_ACCESS_TOKEN" "What tables exist?"

# Or directly with curl
curl -X POST http://localhost:5050/api/v1/configure \
  -H "Authorization: Bearer $TDA_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"provider": "Google", "model": "gemini-2.0-flash-exp"}'
```

**Token Management:**
- View all tokens and usage statistics in **Advanced Settings**
- Revoke tokens immediately (soft-delete preserves audit trail)
- Monitor token usage: last used timestamp, use count, IP address
- Tokens are SHA256 hashed in database for security

**Important Notes:**
*   Example scripts (`rest_run_query.sh`, `rest_check_status.sh`) now require an access token as the first argument
*   The `rest_run_query.sh` script can optionally accept a `--session-id` to run a query in an existing session
*   Example scripts support a `--verbose` flag - by default they output only JSON to `stdout`

### Key Capabilities

* **Asynchronous Architecture**: The API is built on a robust, task-based pattern. Long-running queries are handled as background jobs, preventing timeouts and allowing clients to poll for status and retrieve results when ready.

* **Programmatic Configuration**: Automate the entire application setup process. The API provides an endpoint to configure LLM providers, credentials, and the MCP server connection, making it ideal for CI/CD pipelines and scripted deployments.

* **Full Agent Functionality**: Create sessions and submit natural language queries or execute pre-defined prompts programmatically, receiving the same rich, structured JSON output as the web UI.

For complete technical details, endpoint definitions, and cURL examples, please see the full documentation:
[**REST API Documentation (docs/RestAPI/restAPI.md)**](docs/RestAPI/restAPI.md)

---

### Real-Time Monitoring

The Uderia Platform's UI serves as a powerful, real-time monitoring tool that provides full visibility into all agent workloads, regardless of whether they are initiated from the user interface or the REST API. This capability is particularly valuable for developers and administrators interacting with the agent programmatically.

When a task is triggered via a REST call, it is not a "black box" operation. Instead, the entire execution workflow is visualized in real-time within the UI's Live Status panel. This provides a granular, step-by-step view of the agent's process, including:

*   **Planner Activity:** See the strategic plan the agent creates to address the request.
*   **Tool Execution:** Watch as the agent executes specific tools and gathers data.
*   **Response Synthesis:** Observe the final phase where the agent synthesizes the gathered information into a coherent answer.

This provides a level of transparency typically not available for REST API interactions, offering a "glass box" view into the agent's operations. The key benefit is that you can trigger a complex workflow through a single API call and then use the UI to visually monitor its progress, understand how it's being executed, and immediately diagnose any issues that may arise. This turns the UI into an essential tool for the development, debugging, and monitoring of any integration with the Uderia Platform.

---

### Operationalization

#### From Interactive UI to Automated REST API

The Uderia Platform is designed to facilitate a seamless transition from interactive development in the UI to automated, operational workflows via its REST API. This process allows you to build, test, and refine complex data interactions in an intuitive conversational interface and then deploy them as robust, repeatable tasks.

**Step 1: Develop and Refine in the UI**

The primary development environment is the web-based UI. Here, you can:
*   **Prototype Workflows:** Engage in a dialogue with the agent to build out your desired sequence of actions.
*   **Test and Debug:** Interactively test the agent's understanding and execution of your requests. The real-time feedback and detailed status updates in the UI are invaluable for debugging and refining your prompts.
*   **Validate Outcomes:** Ensure the agent produces the correct results and handles edge cases appropriately before moving to automation.

**Step 2: Isolate the Core Workflow Requests**

Once you have a conversation that successfully executes your desired workflow, you can identify the key session turns that drive the process. These are the prompts you will use to build your REST API requests. The UI helps you distill a complex interaction into a series of precise, automatable commands.

**Step 3: Automate via the REST API**

With your workflow defined, you can transition to the REST API for operational use cases. This is done by sending your prompts to the appropriate API endpoint using an access token for authentication.

**Create an Access Token:**
1. Navigate to **Setup** → **Advanced Settings** → **Access Token Management**
2. Click **"Create Token"** and provide a name (e.g., "Production Automation")
3. Copy the token immediately (shown only once!)
4. Store securely in your environment or secrets manager

*   **Example `curl` command:**

```bash
# Set your access token
export TDA_TOKEN="tda_9DqZMBXh-OK4H4F7iI2t3EcGctldT-iX"

# Execute query in a session
curl -X POST http://localhost:5050/api/v1/sessions/{session_id}/query \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TDA_TOKEN" \
  -d '{
    "prompt": "Your refined prompt from the UI"
  }'
```

This allows you to integrate the Uderia Platform into larger automated systems, CI/CD pipelines, or other applications.

For more advanced orchestration and scheduling, the Uderia Platform also integrates with Apache Airflow. You can find detailed documentation and example DAGs in the [Airflow Integration Guide (docs/Airflow/Airflow.md)](docs/Airflow/Airflow.md).

For visual workflow construction and no-code/low-code integration, the agent provides example flows for the Flowise UI. These can be found in the [Flowise Integration Guide (docs/Flowise/Flowise.md)](docs/Flowise/Flowise.md).

**Step 4: Real-Time Monitoring of REST-driven Workflows**

A key feature of the platform is the ability to monitor REST-initiated tasks in real-time through the UI. When a workflow is triggered via the API, the UI (if viewing the corresponding session) will display:

*   The incoming request, flagged with a "Rest Call" tag.
*   The complete sequence of agent thoughts, plans, and tool executions as they happen.
*   Live status updates, providing the same level of transparency as if you were interacting with the agent directly in the UI.

This hybrid approach gives you the best of both worlds: the automation and scalability of a REST API, combined with the rich, real-time monitoring and debugging capabilities of the interactive UI. It provides crucial visibility into your operationalized data workflows.

---

### Troubleshooting

* **`ModuleNotFoundError`:** This error almost always means you are either (1) not in the project's root directory, or (2) you have not run `pip install -e .` successfully in your active virtual environment.

* **Connection Errors:** Double-check all host, port, path, and API key information. Ensure no firewalls are blocking the connection. If you receive an API key error, verify that the key is correct and has permissions for the model you selected.

* **"Failed to fetch models":** This usually indicates an invalid API key, an incorrect Ollama host, or a network issue preventing connection to the provider's API.

* **AWS Bedrock Errors:**

  * Ensure your AWS credentials have the necessary IAM permissions (`bedrock:ListFoundationModels`, `bedrock:ListInferenceProfiles`, `bedrock-runtime:InvokeModel`).

  * Verify that the selected model is enabled for access in the AWS Bedrock console for your specified region.

---

## Docker Deployment

The Uderia Platform can be deployed in Docker containers for production use, testing, and multi-user scenarios. The application includes built-in support for credential isolation in shared deployments.

### Quick Start with Docker

```bash
# Build the image
docker build -t uderia:latest .

# Run the container
docker run -d \
  -p 5050:5050 \
  -e CORS_ALLOWED_ORIGINS=https://your-domain.com \
  uderia:latest
```

### Multi-User Deployment Considerations

**The application now supports true multi-user authentication with user isolation:**

#### Production Deployment (Recommended)
- Single shared container supports multiple simultaneous users
- Each user has their own account with encrypted credentials
- User tiers control access to features (user, developer, admin)
- Session data isolated per user with JWT authentication
- Best for: Production deployments, team collaboration

#### Initial Setup:
```bash
docker run -d \
  -p 5050:5050 \
  -v $(pwd)/tda_auth.db:/app/tda_auth.db \
  -v $(pwd)/tda_sessions:/app/tda_sessions \
  -e CORS_ALLOWED_ORIGINS=https://your-domain.com \
  uderia:latest
```

**Important Security Steps:**
1. Mount volumes for `tda_auth.db` (user database) and `tda_sessions` (session data)
2. Change default admin password immediately after first login
3. Create individual user accounts for team members
4. Configure HTTPS reverse proxy (nginx, traefik) for production
5. Set `TDA_ENCRYPTION_KEY` environment variable for production encryption

**Optional Security Configuration:**
- **Rate Limiting**: Disabled by default, can be enabled and configured through the web UI:
  - Navigate to **Administration** → **App Config** → **Security & Rate Limiting**
  - Toggle "Enable Rate Limiting" and configure limits for your deployment
  - Per-user limits: prompts per hour/day, configuration changes
  - Per-IP limits: login attempts, registrations, API calls
  - Changes take effect within 60 seconds (cache refresh)

### Pre-configuring MCP Server

You can bake MCP Server configuration into the Docker image:

1. **Before building**, edit `tda_config.json`:
```json
{
  "mcp_servers": [
    {
      "name": "Your MCP Server",
      "host": "your-host.com",
      "port": "8888",
      "path": "/mcp",
      "id": "default-server-id"
    }
  ],
  "active_mcp_server_id": "default-server-id"
}
```

2. **Build the image** - MCP configuration is included
3. **Users only need to configure LLM credentials** - much simpler onboarding!



### Detailed Docker Documentation

For comprehensive information on Docker deployment, credential isolation, security considerations, and troubleshooting, see:
[**Docker Credential Isolation Guide (docs/Docker/DOCKER_CREDENTIAL_ISOLATION.md)**](docs/Docker/DOCKER_CREDENTIAL_ISOLATION.md)

---

## License

This project is licensed under the GNU Affero General Public License v3.0. The full license text is available in the `LICENSE` file in the root of this repository.

Under the AGPLv3, you are free to use, modify, and distribute this software. However, if you run a modified version of this software on a network server and allow other users to interact with it, you must also make the source code of your modified version available to those users. There are 4 License Modes available.

### Description of the 4 License Modes

#### Community and Development Tiers (AGPLv3)

*Tiers 1 through 3 are governed by the GNU Affero General Public License v3.0 (AGPLv3). This is a "strong copyleft" license, meaning any modifications made to the software must be shared back with the community if the software is run on a network. This model fosters open collaboration and ensures that improvements benefit all users.*

##### 1. App Developer --- INCLUDED IN THIS PACKAGE

* **Software License:** GNU Affero General Public License v3.0

* **Intended User:** Software developers integrating the standard, out-of-the-box agent into other AGPLv3-compatible projects.

* **Description:** This tier provides full programmatic access to the agent's general-purpose tools, code and associated architetcture. It is designed for developers who need to use the agent as a standard component in a larger system, with the understanding that their combined work will also be licensed under the AGPLv3. **This is a application developer-focused license; access to prompt editing capabilities is not included.**

##### 2. Prompt Engineer

* **Software License:** GNU Affero General Public License v3.0

* **Intended User:** AI developers and specialists focused on creating and testing prompts for community contribution.

* **Description:** A specialized tier for crafting new prompts and workflows. It provides the necessary tools and diagnostic access to develop new prompts that can be contributed back to the open-source project, enhancing the agent for all AGPLv3 users. **This is a prompt developer-focused license; access to prompt editing capabilities is included.**

##### 3. Enterprise Light

* **Software License:** GNU Affero General Public License v3.0

* **Intended User:** Business users or teams requiring a tailored, but not exclusive, data agent.

* **Description:** This license is for a version of the application that has been **customized for specific business needs** (e.g., a "Financial Reporting" or "Marketing Analytics" package). The only difference between this and the "App Developer" license is that the deliverable is a pre-configured solution rather than a general toolkit. It is ideal for organizations using open-source software that need a solution for a specific, common business function. **This is a usage-focused license; access to prompt editing capabilities is not included.**

#### Commercial Tier (MIT)

##### 4. Enterprise

* **Software License:** **MIT License**

* **Intended User:** Commercial organizations, power users, and data scientists requiring maximum flexibility and control for proprietary use.

* **Description:** This is the premium commercial tier and the only one that **uplifts the software license to the permissive MIT License**. This allows organizations to modify the code, integrate it into proprietary applications, and deploy it without any obligation to share their source code. Crucially, this is also is the **only tier that enables full prompt editing capabilities (including the licensing system for prompts)**, giving businesses complete control to customize and protect their unique analytical workflows and intellectual property. This license is designed for commercial entities that need to maintain a competitive advantage.

## Author & Contributions

* **Author/Initiator:** Rainer Geissendoerfer, rainer.geissendoerfer@uderia.com , uderia.com.

* **Source Code & Contributions:** The Uderia Platform is licensed under the GNU Affero General Public License v3.0. Contributions are highly welcome. Please visit the main Git repository to report issues or submit pull requests.

* **Git Repository:** <https://github.com/rgeissen/uderia.git>

## Appendix: Feature Update List

This list reflects the recent enhancements and updates to the Uderia Platform, as shown on the application's welcome screen.

*   **20-Dec-2025:** Extended Prompt Management System - Dynamic Workflow Prompts
*   **17-Dec-2025:** Extended Prompt Management System - Dynamic Variables
*   **15-Dec-2025:** Extended Bootstrapping - Enhanced Bootstraping Parameter Configuration
*   **12-Dec-2025:** Enhanced Prompt Encryption/Decryption Process using Database Encryption 
*   **10-Dec-2025:** Migration from File based Application Configuration to Database Schema
*   **05-Dec-2025:** Consumption Profile Enforcement - Rate Limiting and Usage Quotas
*   **02-Dec-2025:** Financial Governance - Dashboards and LiteLLM Integration
*   **01-Dec-2025:** Planner Constructor: SQL Query - Document Context
*   **01-Dec-2025:** Planner Constructor: SQL Query - Database Context
*   **29-Nov-2025:** Knowledge Repository Constructor - Document Storage
*   **28-Nov-2025:** Knowledge Repository Integration
*   **25-Nov-2025:** Multi-User Authentication - JWT tokens, access tokens, user tiers
*   **22-Nov-2025:** Profile System - Modular Configuration & Temporary Overrides
*   **21-Nov-2025:** Planner Repository Constructors - Modular Plugin System
*   **19-Nov-2025:** Modern UI Design
*   **15-Nov-2025:** Flowise Integration
*   **14-Nov-2025:** Airflow Integration
*   **11-Nov-2025:** Self-Improving AI (RAG)
*   **06-Nov-2025:** UI Real-Time Monitoring of Rest Requests
*   **31-Oct-2025:** Fully configurable Context Management (Turn & Session)
*   **24-Oct-2025:** Turn Replay & Turn Reload Plan
*   **24-Oct-2025:** Stop Button Added - Ability to immediately Stop Workflows
*   **23-Oct-2025:** Robust Multi-Tool Phase Handling
*   **11-Oct-2025:** Friendly.AI Integration
*   **10-Oct-2025:** Context Aware Rendering of the Collateral Report
*   **19-SEP-2025:** Microsoft Azure Integration
*   **18-SEP-2025:** REST Interface for Engine Configuration, Execution & Monitoring
*   **12-SEP-2025:** Significant Formatting Upgrade (Canonical Baseline Model for LLM Provider Rendering)
*   **05-SEP-2025:** Conversation Mode (Google Cloud Credentials required)
