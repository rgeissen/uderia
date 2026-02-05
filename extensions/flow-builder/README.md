# Uderia Flow Builder

Visual agent flow development extension for the Uderia Platform. Enables building complex AI workflows with conditional branching, loops, parallel execution, and human-in-the-loop interactions.

## Architecture

The Flow Builder is a **completely isolated extension** that communicates with Uderia via REST API:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Flow Builder (Isolated Extension)                                      │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐               │
│  │ React UI    │────►│ Flow API    │────►│ Flow        │               │
│  │ (Frontend)  │     │ (REST)      │     │ Executor    │               │
│  └─────────────┘     └─────────────┘     └─────────────┘               │
│       Port 5050           Port 5051           │                         │
│       (embedded)                              │ REST API                │
│                                               ▼                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Uderia Core (Unchanged)                       │   │
│  │  POST /v1/sessions           - Create session                    │   │
│  │  POST /v1/sessions/{id}/query - Execute query in profile        │   │
│  │  GET  /v1/tasks/{id}         - Poll for results                 │   │
│  │  GET  /v1/profiles           - List available profiles          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Node Types

| Node | Description | Use Case |
|------|-------------|----------|
| **Start** | Flow entry point | Initial query input |
| **End** | Flow exit point | Final output formatting |
| **Profile** | Execute Uderia profile | AI agent execution |
| **Condition** | Binary branch (if/else) | Decision routing |
| **Merge** | Combine multiple inputs | Aggregate results |
| **Transform** | Modify/filter data | Data processing |
| **Loop** | Iterate over collection | Batch processing |
| **Human** | Pause for user input | Review/approval |
| **Parallel** | Execute simultaneously | Concurrent execution |

## Quick Start

### 1. Build the Frontend

```bash
cd extensions/flow-builder
./build.sh
```

This builds the React app and outputs to `static/js/flowBuilder/dist/`.

### 2. Install Backend Dependencies

```bash
cd extensions/flow-builder/backend
pip install -r ../requirements.txt
```

### 3. Start the Flow Builder Backend

```bash
python main.py
# Running on http://localhost:5051
```

### 4. Start Uderia

```bash
cd /path/to/uderia
python -m trusted_data_agent.main
# Running on http://localhost:5050
```

### 5. Access Flow Builder

Open Uderia in your browser and click "Flow Builder" in the navigation menu.

## Development

### Frontend Development (with hot reload)

```bash
cd extensions/flow-builder/frontend
npm install
npm run dev
# Development server on http://localhost:5173
```

### Backend Development

```bash
cd extensions/flow-builder/backend
python main.py
# API server on http://localhost:5051
```

## API Endpoints

### Flow Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/flows` | Create flow |
| GET | `/api/v1/flows` | List flows |
| GET | `/api/v1/flows/{id}` | Get flow |
| PUT | `/api/v1/flows/{id}` | Update flow |
| DELETE | `/api/v1/flows/{id}` | Delete flow |

### Execution

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/flows/{id}/execute` | Execute flow |
| GET | `/api/v1/flow-executions/{id}` | Get execution status |
| GET | `/api/v1/flow-executions/{id}/stream` | SSE event stream |
| POST | `/api/v1/flow-executions/{id}/cancel` | Cancel execution |
| POST | `/api/v1/flow-executions/{id}/respond` | Human response |

### Utilities

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/flows/{id}/validate` | Validate flow |
| POST | `/api/v1/flows/{id}/duplicate` | Duplicate flow |
| GET | `/api/v1/flow-templates` | List templates |
| GET | `/api/v1/profiles` | Get Uderia profiles |

## File Structure

```
extensions/flow-builder/
├── backend/
│   ├── main.py              # Quart app entry point
│   ├── flow_routes.py       # REST API endpoints
│   ├── flow_manager.py      # Flow persistence
│   ├── flow_executor.py     # DAG execution engine
│   ├── flow_graph.py        # Graph utilities
│   └── database.py          # SQLite connection
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main React component
│   │   ├── components/
│   │   │   ├── FlowCanvas.jsx     # React Flow canvas
│   │   │   ├── NodePalette.jsx    # Draggable nodes
│   │   │   ├── ExecutionPanel.jsx # Execution status
│   │   │   ├── FlowToolbar.jsx    # Save/Run actions
│   │   │   └── nodes/             # 9 node components
│   │   ├── store/
│   │   │   └── flowStore.js       # Zustand state
│   │   └── api/
│   │       └── flowApi.js         # API client
│   ├── package.json
│   └── vite.config.js
├── schema/
│   └── flows.sql            # Database schema
├── requirements.txt
├── build.sh
└── README.md
```

## Database

The Flow Builder uses a separate SQLite database (`tda_flows.db`) to maintain isolation from Uderia's core database.

### Tables

- `flows` - Flow definitions (nodes, edges, metadata)
- `flow_executions` - Execution history
- `flow_node_executions` - Per-node execution tracking
- `flow_human_responses` - Human-in-the-loop responses
- `flow_templates` - Pre-built flow templates
- `flow_execution_events` - Detailed event log

## Flow Definition Format

```json
{
  "nodes": [
    {
      "id": "node-1",
      "type": "profile",
      "position": { "x": 100, "y": 100 },
      "data": {
        "label": "Query Executor",
        "profileId": "profile-xxx",
        "profileTag": "@OPTIMIZER"
      }
    }
  ],
  "edges": [
    {
      "id": "edge-1",
      "source": "node-1",
      "target": "node-2",
      "sourceHandle": "output",
      "targetHandle": "input"
    }
  ]
}
```

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Cmd/Ctrl + S | Save flow |
| Cmd/Ctrl + Enter | Run flow |
| Delete | Remove selected node |
| Double-click | Add profile node |

## Technology Stack

- **Frontend**: React 18, React Flow 11, Zustand, Tailwind CSS
- **Backend**: Python 3.12+, Quart, aiosqlite, httpx
- **Build**: Vite 5
