-- Flow Builder Database Schema
-- Stored in tda_flows.db (separate from tda_auth.db)
-- Version: 1.0.0

-- Core flow definition
CREATE TABLE IF NOT EXISTS flows (
    id TEXT PRIMARY KEY,
    user_uuid TEXT NOT NULL,  -- Links to Uderia user (validated via JWT)
    name TEXT NOT NULL,
    description TEXT,
    definition TEXT NOT NULL,  -- JSON: nodes, edges, variables
    uderia_base_url TEXT DEFAULT 'http://localhost:5050',
    status TEXT DEFAULT 'draft',  -- draft, published, archived
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for user lookup
CREATE INDEX IF NOT EXISTS idx_flows_user_uuid ON flows(user_uuid);
CREATE INDEX IF NOT EXISTS idx_flows_status ON flows(status);

-- Flow execution history
CREATE TABLE IF NOT EXISTS flow_executions (
    id TEXT PRIMARY KEY,
    flow_id TEXT NOT NULL,
    user_uuid TEXT NOT NULL,
    status TEXT DEFAULT 'running',  -- pending, running, completed, failed, cancelled, paused
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    input_json TEXT,  -- Initial query/input
    result_json TEXT,  -- Final result
    token_usage_json TEXT,  -- Token tracking across all nodes
    uderia_sessions_json TEXT,  -- Track Uderia sessions created for this execution
    error_message TEXT,
    FOREIGN KEY (flow_id) REFERENCES flows(id) ON DELETE CASCADE
);

-- Indexes for execution lookup
CREATE INDEX IF NOT EXISTS idx_flow_executions_flow_id ON flow_executions(flow_id);
CREATE INDEX IF NOT EXISTS idx_flow_executions_user_uuid ON flow_executions(user_uuid);
CREATE INDEX IF NOT EXISTS idx_flow_executions_status ON flow_executions(status);

-- Per-node execution tracking
CREATE TABLE IF NOT EXISTS flow_node_executions (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    node_id TEXT NOT NULL,  -- Node ID from flow definition
    node_type TEXT NOT NULL,  -- start, end, profile, condition, etc.
    node_label TEXT,  -- Human-readable label
    status TEXT DEFAULT 'pending',  -- pending, running, completed, failed, skipped
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    input_json TEXT,  -- Input data for this node
    output_json TEXT,  -- Output/result from this node
    uderia_session_id TEXT,  -- Uderia session ID (for profile nodes)
    uderia_task_id TEXT,  -- Uderia task ID (for profile nodes)
    error_message TEXT,
    duration_ms INTEGER,  -- Execution duration in milliseconds
    FOREIGN KEY (execution_id) REFERENCES flow_executions(id) ON DELETE CASCADE
);

-- Indexes for node execution lookup
CREATE INDEX IF NOT EXISTS idx_flow_node_executions_execution_id ON flow_node_executions(execution_id);
CREATE INDEX IF NOT EXISTS idx_flow_node_executions_node_id ON flow_node_executions(node_id);
CREATE INDEX IF NOT EXISTS idx_flow_node_executions_status ON flow_node_executions(status);

-- Human-in-the-loop pending responses
CREATE TABLE IF NOT EXISTS flow_human_responses (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    input_type TEXT DEFAULT 'text',  -- text, choice, approval
    choices_json TEXT,  -- JSON array of choices (if input_type is 'choice')
    response TEXT,  -- User's response
    responded_at TIMESTAMP,
    timeout_at TIMESTAMP,
    status TEXT DEFAULT 'pending',  -- pending, responded, timeout
    FOREIGN KEY (execution_id) REFERENCES flow_executions(id) ON DELETE CASCADE
);

-- Index for pending responses
CREATE INDEX IF NOT EXISTS idx_flow_human_responses_execution_id ON flow_human_responses(execution_id);
CREATE INDEX IF NOT EXISTS idx_flow_human_responses_status ON flow_human_responses(status);

-- Flow templates (pre-built flow patterns)
CREATE TABLE IF NOT EXISTS flow_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,  -- query_summarize, loop_process, parallel_analysis, etc.
    definition TEXT NOT NULL,  -- JSON: nodes, edges (without profile IDs)
    icon TEXT,  -- Icon identifier
    is_system BOOLEAN DEFAULT FALSE,  -- System templates vs user-created
    user_uuid TEXT,  -- NULL for system templates
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for template lookup
CREATE INDEX IF NOT EXISTS idx_flow_templates_category ON flow_templates(category);
CREATE INDEX IF NOT EXISTS idx_flow_templates_is_system ON flow_templates(is_system);

-- Flow execution events (for real-time streaming)
CREATE TABLE IF NOT EXISTS flow_execution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL,
    event_type TEXT NOT NULL,  -- node_started, node_completed, condition_evaluated, etc.
    event_data TEXT NOT NULL,  -- JSON payload
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (execution_id) REFERENCES flow_executions(id) ON DELETE CASCADE
);

-- Index for event streaming
CREATE INDEX IF NOT EXISTS idx_flow_execution_events_execution_id ON flow_execution_events(execution_id);
CREATE INDEX IF NOT EXISTS idx_flow_execution_events_created_at ON flow_execution_events(created_at);

-- Insert default templates
INSERT OR IGNORE INTO flow_templates (id, name, description, category, definition, icon, is_system) VALUES
('tpl-query-summarize', 'Query → Summarize', 'Execute a query and summarize the results', 'basic', '{"nodes":[{"id":"start","type":"start","position":{"x":250,"y":50},"data":{"label":"Start"}},{"id":"query","type":"profile","position":{"x":250,"y":150},"data":{"label":"Query","profileType":"tool_enabled"}},{"id":"summarize","type":"profile","position":{"x":250,"y":250},"data":{"label":"Summarize","profileType":"llm_only"}},{"id":"end","type":"end","position":{"x":250,"y":350},"data":{"label":"End"}}],"edges":[{"id":"e1","source":"start","target":"query"},{"id":"e2","source":"query","target":"summarize"},{"id":"e3","source":"summarize","target":"end"}]}', 'workflow', TRUE),
('tpl-conditional-routing', 'Conditional Routing', 'Route based on result conditions', 'branching', '{"nodes":[{"id":"start","type":"start","position":{"x":250,"y":50},"data":{"label":"Start"}},{"id":"query","type":"profile","position":{"x":250,"y":150},"data":{"label":"Query","profileType":"tool_enabled"}},{"id":"condition","type":"condition","position":{"x":250,"y":250},"data":{"label":"Large Result?","expression":"result.rows > 10"}},{"id":"detailed","type":"profile","position":{"x":100,"y":350},"data":{"label":"Detailed Analysis","profileType":"llm_only"}},{"id":"summary","type":"profile","position":{"x":400,"y":350},"data":{"label":"Quick Summary","profileType":"llm_only"}},{"id":"end","type":"end","position":{"x":250,"y":450},"data":{"label":"End"}}],"edges":[{"id":"e1","source":"start","target":"query"},{"id":"e2","source":"query","target":"condition"},{"id":"e3","source":"condition","target":"detailed","sourceHandle":"true"},{"id":"e4","source":"condition","target":"summary","sourceHandle":"false"},{"id":"e5","source":"detailed","target":"end"},{"id":"e6","source":"summary","target":"end"}]}', 'git-branch', TRUE),
('tpl-human-review', 'Human Review', 'Execute with human approval step', 'interactive', '{"nodes":[{"id":"start","type":"start","position":{"x":250,"y":50},"data":{"label":"Start"}},{"id":"query","type":"profile","position":{"x":250,"y":150},"data":{"label":"Query","profileType":"tool_enabled"}},{"id":"human","type":"human","position":{"x":250,"y":250},"data":{"label":"Review Results","prompt":"Please review the results:","inputType":"approval","choices":["Approve","Reject"]}},{"id":"end","type":"end","position":{"x":250,"y":350},"data":{"label":"End"}}],"edges":[{"id":"e1","source":"start","target":"query"},{"id":"e2","source":"query","target":"human"},{"id":"e3","source":"human","target":"end"}]}', 'user-check', TRUE),
('tpl-parallel-analysis', 'Parallel Analysis', 'Run multiple analyses simultaneously', 'advanced', '{"nodes":[{"id":"start","type":"start","position":{"x":250,"y":50},"data":{"label":"Start"}},{"id":"parallel","type":"parallel","position":{"x":250,"y":150},"data":{"label":"Parallel","waitStrategy":"all"}},{"id":"analysis1","type":"profile","position":{"x":100,"y":250},"data":{"label":"Analysis 1","profileType":"tool_enabled"}},{"id":"analysis2","type":"profile","position":{"x":400,"y":250},"data":{"label":"Analysis 2","profileType":"tool_enabled"}},{"id":"merge","type":"merge","position":{"x":250,"y":350},"data":{"label":"Merge","strategy":"concat"}},{"id":"end","type":"end","position":{"x":250,"y":450},"data":{"label":"End"}}],"edges":[{"id":"e1","source":"start","target":"parallel"},{"id":"e2","source":"parallel","target":"analysis1"},{"id":"e3","source":"parallel","target":"analysis2"},{"id":"e4","source":"analysis1","target":"merge"},{"id":"e5","source":"analysis2","target":"merge"},{"id":"e6","source":"merge","target":"end"}]}', 'git-merge', TRUE);
