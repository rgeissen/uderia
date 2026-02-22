# Skill Architecture

> **Pre-processing prompt injections** — reusable markdown instruction documents injected into LLM context before query execution.

Skills provide transparent, auditable context enhancement. They are **fully transient**: skill content is injected into local variables per-request and never enters persistent chat history (`chat_object`).

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Backend Architecture](#2-backend-architecture)
3. [Skill Discovery Pipeline](#3-skill-discovery-pipeline)
4. [Content Resolution & Param Blocks](#4-content-resolution--param-blocks)
5. [Injection Points by Profile Type](#5-injection-points-by-profile-type)
6. [Skill Lifecycle & Transience](#6-skill-lifecycle--transience)
7. [Database Schema](#7-database-schema)
8. [REST API Endpoints](#8-rest-api-endpoints)
9. [Frontend Architecture](#9-frontend-architecture)
10. [Built-in Skills](#10-built-in-skills)
11. [Admin Governance](#11-admin-governance)
12. [CSS & Visual Design](#12-css--visual-design)
13. [File Reference](#13-file-reference)

---

## 1. System Overview

### What Skills Do

Skills inject markdown instructions into LLM context to modify behavior — response style, domain expertise, formatting rules — without modifying system prompts permanently or polluting conversation history.

### Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Transient** | Injected into local variables, never stored in `chat_object` |
| **Transparent** | `skills_applied` SSE event shows what was injected and token cost |
| **Parameterizable** | `<!-- param:strict -->` blocks enable runtime behavior variants |
| **Governed** | Admin controls disable/enable skills globally or selectively |
| **Portable** | Export/import as `.zip`; flat `.md` files auto-discover |

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│ FRONTEND                                                             │
│                                                                      │
│  User types !sql-expert:strict                                      │
│       ↓                                                              │
│  Badge rendered in input area                                        │
│       ↓                                                              │
│  submitQuestion() → POST /ask_stream                                │
│     { message: "...", skills: [{name: "sql-expert", param: "strict"}] }
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ BACKEND: execution_service.py                                        │
│                                                                      │
│  1. Save original user_input to chat_object (line 312)              │
│  2. Resolve skills (line 455-494):                                  │
│     - Filter by admin governance (is_skill_available)               │
│     - Load content via SkillManager.resolve_skills()                │
│     - Emit skills_applied SSE event                                 │
│  3. Pass SkillResult to PlanExecutor (line 619)                     │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ EXECUTOR / PLANNER (profile-dependent injection)                     │
│                                                                      │
│  tool_enabled  → planner.py:2752   → planning_prompt (local var)    │
│  llm_only      → executor.py:2654  → system_prompt + user_message   │
│  rag_focused   → executor.py:3564  → system_prompt + user_message   │
│                                                                      │
│  All injection targets are LOCAL VARIABLES — never persisted         │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────┐
│ LLM CALL                                                             │
│                                                                      │
│  LLM receives context augmented with skill content                  │
│  Generates response influenced by skill instructions                │
│  Response saved to chat_object (skill content is NOT)               │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Backend Architecture

### Module Structure

```
src/trusted_data_agent/skills/
├── __init__.py
├── models.py          # Data classes: SkillSpec, SkillContent, SkillResult
├── loader.py          # Content loading, param block resolution
├── manager.py         # Discovery, registry, singleton manager
├── db.py              # Per-user activation persistence (SQLite)
└── settings.py        # Admin governance (skill_settings table)

skills/
├── skill_registry.json    # Registry of built-in skills
├── schemas/               # JSON schemas for validation
└── builtin/               # 5 built-in skill directories
    ├── sql-expert/
    ├── table-format/
    ├── concise/
    ├── detailed/
    └── step-by-step/
```

### Data Models (`models.py`)

#### SkillSpec
Parsed from user input (e.g., `!sql-expert:strict`):

```python
@dataclass
class SkillSpec:
    name: str                    # Activation name
    param: Optional[str] = None  # Optional parameter
```

#### SkillContent
Loaded content from a single skill:

```python
@dataclass
class SkillContent:
    skill_name: str
    content: str                              # Markdown to inject
    injection_target: str = "system_prompt"   # "system_prompt" | "user_context"
    metadata: Dict[str, Any]                  # Full manifest
    param: Optional[str] = None

    @property
    def content_length(self) -> int: ...
    @property
    def estimated_tokens(self) -> int: ...    # len(content) // 4
```

#### SkillResult
Merged result from all selected skills for a query:

```python
@dataclass
class SkillResult:
    system_prompt_additions: List[str]             # Skills targeting system prompt
    user_context_additions: List[str]              # Skills targeting user context
    skill_contents: Dict[str, SkillContent]        # Per-skill details

    @property
    def has_content(self) -> bool: ...
    @property
    def total_estimated_tokens(self) -> int: ...

    def get_system_prompt_block(self) -> str: ...   # Concatenated with \n\n
    def get_user_context_block(self) -> str: ...     # Concatenated with \n\n
    def to_applied_list(self) -> List[Dict]: ...     # Metadata for SSE event
```

The `to_applied_list()` method builds the `skills_applied` event payload:

```python
[{
    "name": "sql-expert",
    "param": "strict",
    "injection_target": "system_prompt",
    "content_length": 2847,
    "estimated_tokens": 711
}]
```

---

## 3. Skill Discovery Pipeline

The `SkillManager` (singleton via `get_skill_manager()`) discovers skills from multiple sources with user overrides taking priority.

### Four Discovery Modes

| Mode | Source | Trigger | Manifest |
|------|--------|---------|----------|
| **Registry** | `skills/builtin/` | Listed in `skill_registry.json` | Required (`skill.json`) |
| **User Override** | `~/.tda/skills/` | Same name as registry skill | Required (`skill.json`) |
| **Manifest-Free** | `~/.tda/skills/<dir>/` | Subdirectory with `.md` file | Auto-generated |
| **Flat File** | `~/.tda/skills/*.md` | Direct `.md` file | Auto-generated |

### Discovery Order

```
1. Load skill_registry.json
   └─ For each entry:
      ├─ Check ~/.tda/skills/<name>/ first (user override)
      └─ Fall back to skills/builtin/<name>/

2. Auto-discover ~/.tda/skills/
   ├─ Mode A: Subdirs with skill.json (manifest mode)
   ├─ Mode B: Subdirs with .md but no skill.json (manifest-free)
   └─ Mode C: Direct .md files (flat mode)
```

Later sources override earlier ones by skill name.

### Auto-Generated Manifests

For manifest-free and flat-file modes, the manager builds a manifest from the `.md` file:

```python
{
    "name": skill_id,                    # From filename/dirname
    "version": "1.0.0",
    "description": "<first non-heading line>",
    "author": "User",
    "main_file": "skill-name.md",
    "last_updated": "<YYYY-MM-DD>",
    "_is_user": True,
    "_auto_generated": True,
}
```

### Resolve Flow

```python
manager = get_skill_manager()
result = manager.resolve_skills([
    SkillSpec(name="sql-expert", param="strict"),
    SkillSpec(name="concise", param=None),
])
# result.get_system_prompt_block() → concatenated skill content
```

For each spec:
1. Look up manifest in `self.manifests[name]`
2. Call `load_skill_content(skill_dir, manifest, param)`
3. Wrap in delimited block: `--- Skill: SQL Expert (strict) ---\n\n{content}`
4. Route to `system_prompt_additions` or `user_context_additions`
5. Store in `result.skill_contents[name]`

---

## 4. Content Resolution & Param Blocks

### Param Block Syntax

Skills support optional parameter-specific content using HTML comments (invisible to non-Uderia markdown renderers):

```markdown
# SQL Expert

Base instructions that always apply.
Use explicit JOINs. Qualify column names.

<!-- param:strict -->
Enforce ANSI SQL compliance strictly.
Flag any deviation from standards.
<!-- /param:strict -->

<!-- param:lenient -->
Suggest improvements but accept valid SQL.
Focus on correctness over standards.
<!-- /param:lenient -->
```

### Resolution Algorithm (`loader.py`)

| Scenario | Result |
|----------|--------|
| No param | Strip ALL param blocks → base content only |
| `param="strict"` | Base content + `<!-- param:strict -->` block |
| Invalid param | Warning logged → base content only |

```python
def _resolve_content(raw: str, param: Optional[str]) -> str:
    if param is None:
        return _ALL_PARAM_BLOCKS_RE.sub("", raw).strip()

    match = _PARAM_BLOCK_RE.search(raw)  # Find matching block
    base = _ALL_PARAM_BLOCKS_RE.sub("", raw).strip()

    if match:
        return f"{base}\n\n{match.group(2).strip()}"
    return base  # Param not found, fallback
```

### Manifest Configuration

Parameters are declared in the `uderia` section of `skill.json`:

```json
{
    "uderia": {
        "allowed_params": ["strict", "lenient"],
        "param_descriptions": {
            "strict": "Enforce all SQL standards strictly",
            "lenient": "Suggest improvements but accept any valid SQL"
        },
        "injection_target": "system_prompt"
    }
}
```

### Editor Functions

The loader also exposes functions for the skill editor:

| Function | Purpose |
|----------|---------|
| `extract_param_blocks(raw)` | Returns `{param_name: content}` dict |
| `get_base_content(raw)` | Returns content outside all param blocks |
| `build_full_content(base, param_blocks)` | Reconstructs full markdown |

---

## 5. Injection Points by Profile Type

Skill content is injected at exactly one point per profile type, always into **local variables** that are scoped to a single LLM call.

### Tool-Enabled Profile (Fusion Optimizer)

**File:** `planner.py:2752-2759`

```python
if self.executor.skill_result and self.executor.skill_result.has_content:
    sp_block = self.executor.skill_result.get_system_prompt_block()
    if sp_block:
        planning_prompt = f"{planning_prompt}\n\n{sp_block}"
    uc_block = self.executor.skill_result.get_user_context_block()
    if uc_block:
        planning_prompt = f"{uc_block}\n\n{planning_prompt}"
```

Injected into the **strategic planning prompt** (meta-plan generation). The `planning_prompt` is a local variable — never saved.

### LLM-Only Profile (Conversation Focused)

**File:** `executor.py:2654-2679`

```python
# System prompt injection
if self.skill_result and self.skill_result.has_content:
    sp_block = self.skill_result.get_system_prompt_block()
    if sp_block:
        system_prompt = f"{system_prompt}\n\n{sp_block}"

# User context injection (after building user_message)
if self.skill_result and self.skill_result.has_content:
    uc_block = self.skill_result.get_user_context_block()
    if uc_block:
        user_message = f"{uc_block}\n\n{user_message}"
```

Both `system_prompt` and `user_message` are local variables.

### RAG-Focused Profile (Knowledge Focused)

**File:** `executor.py:3564-3587`

Same pattern as LLM-Only — skill content appended to local `system_prompt` and prepended to local `user_message` used for RAG synthesis.

### Summary Table

| Profile | Injection Variable | File:Line | Scope |
|---------|-------------------|-----------|-------|
| `tool_enabled` | `planning_prompt` (local) | `planner.py:2752` | Single `plan_strategy()` call |
| `llm_only` | `system_prompt` + `user_message` (local) | `executor.py:2654-2679` | Single conversation LLM call |
| `rag_focused` | `system_prompt` + `user_message` (local) | `executor.py:3564-3587` | Single RAG synthesis call |

---

## 6. Skill Lifecycle & Transience

### Why Skill Content Never Enters `chat_object`

The user message is saved to `chat_object` at `execution_service.py:312` — **before** skill resolution happens at line 455. The saved message contains only the original `user_input`, not the skill-augmented content.

### Timeline: Turn with Skill → Turn without Skill

```
Turn 1 (skill !concise activated):
  execution_service.py:312  → save original "What is X?" to chat_object
  execution_service.py:477  → resolve skills → SkillResult with markdown
  executor.py:2655          → system_prompt += skill markdown (LOCAL var)
  executor.py:2676          → user_message = skill_context + user_input (LOCAL var)
  LLM call                  → receives augmented prompt
  LLM response saved        → response text to chat_object
  SkillResult               → discarded (request-scoped)

Turn 2 (skill deactivated):
  Load chat_object from disk → contains:
    [0] user: "What is X?"           ← NO skill content
    [1] assistant: "X is..."          ← plain response text
  execution_service.py:477  → no skill_specs → skill_result = None
  executor.py:2655          → no injection
  LLM call                  → receives history WITHOUT any skill content
```

### What IS Persisted

Only **metadata references** are stored — never the actual markdown content:

| Storage | What's Stored | Content? |
|---------|--------------|----------|
| `session_history` message | `skill_specs: [{name, param}]` | No |
| Workflow history (`executor.py:1913`) | `skills_applied: [{name, param, injection_target, content_length, estimated_tokens}]` | No |

### Deactivation = Complete Elimination

- No cleanup needed — there's nothing to clean up
- Skill content never enters any persistent store
- The LLM's response text IS stored (it may reflect the skill's influence), but this is the LLM's own output

---

## 7. Database Schema

### `user_skills` Table

Per-user skill activations with custom naming.

```sql
CREATE TABLE IF NOT EXISTS user_skills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_uuid       VARCHAR(36) NOT NULL,
    skill_id        VARCHAR(100) NOT NULL,          -- Base skill (e.g., "sql-expert")
    activation_name VARCHAR(100) NOT NULL,          -- User-facing name (e.g., "sql-expert2")
    is_active       BOOLEAN NOT NULL DEFAULT 1,
    default_param   VARCHAR(255),                   -- Default parameter value
    config_json     TEXT,                           -- JSON configuration
    activated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_uuid) REFERENCES users(id),
    UNIQUE(user_uuid, activation_name)
);

CREATE INDEX idx_user_skills_user ON user_skills(user_uuid, is_active);
CREATE INDEX idx_user_skills_name ON user_skills(user_uuid, activation_name);
```

**Activation name auto-generation** (`db.py`): First activation uses `skill_id` directly. Subsequent activations of the same skill append incrementing numbers: `sql-expert`, `sql-expert2`, `sql-expert3`.

### `skill_settings` Table

Admin governance controls.

```sql
CREATE TABLE IF NOT EXISTS skill_settings (
    id            INTEGER PRIMARY KEY,
    setting_key   TEXT NOT NULL UNIQUE,
    setting_value TEXT NOT NULL,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Defaults
INSERT OR IGNORE INTO skill_settings (setting_key, setting_value) VALUES
    ('skills_mode', 'all'),             -- 'all' | 'selective'
    ('disabled_skills', '[]'),          -- JSON array of skill_ids
    ('user_skills_enabled', 'true'),    -- Can users create skills?
    ('auto_skills_enabled', 'false');   -- Phase 2: automatic skill selection
```

### Schema Files

| File | Table |
|------|-------|
| `schema/15_skills.sql` | `user_skills` |
| `schema/16_skill_settings.sql` | `skill_settings` |

---

## 8. REST API Endpoints

### Skill Discovery & Content

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/skills` | GET | List all available skills (filtered by governance) |
| `/v1/skills/reload` | POST | Hot-reload skills from disk |
| `/v1/skills/{skill_id}/content` | GET | Full content + manifest (for editor) |
| `/v1/skills/{skill_id}` | PUT | Create or update user skill |
| `/v1/skills/{skill_id}` | DELETE | Delete user-created skill |
| `/v1/skills/{skill_id}/export` | POST | Export skill as `.zip` |
| `/v1/skills/import` | POST | Import skill from `.zip` file |

### User Activations

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/skills/activated` | GET | User's active skills (for `!` autocomplete) |
| `/v1/skills/{skill_id}/activate` | POST | Activate skill with optional custom name |
| `/v1/skills/activations/{name}/deactivate` | POST | Soft-deactivate (set `is_active=0`) |
| `/v1/skills/activations/{name}/config` | PUT | Update default param |
| `/v1/skills/activations/{name}/rename` | PUT | Rename activation |
| `/v1/skills/activations/{name}` | DELETE | Hard-delete activation record |

### Admin Governance

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v1/admin/skill-settings` | GET | Get governance settings + builtin skill list |
| `/v1/admin/skill-settings` | POST | Save governance (disabled_skills, user_skills_enabled) |

### Query Execution with Skills

**SSE Route** (`routes.py`):
```
POST /ask_stream
Body: { message, session_id, skills: [{name, param}], ... }
```

**REST Route** (`rest_routes.py`):
```
POST /v1/sessions/{session_id}/query
Body: { prompt, skills: [{name, param}], ... }
```

Both routes extract `skill_specs` and pass to `execution_service.run_agent_execution()`.

### Execution Service Flow (`execution_service.py:455-494`)

```python
# 1. Filter by governance
for spec in skill_specs:
    if not is_skill_available(spec["name"]):
        continue  # Skip disabled skills
    resolved_specs.append(SkillSpec(name=spec["name"], param=spec.get("param")))

# 2. Resolve content
skill_result = skill_manager.resolve_skills(resolved_specs)

# 3. Emit transparency event
if skill_result.has_content:
    await event_handler({
        "type": "skills_applied",
        "payload": {
            "skills": skill_result.to_applied_list(),
            "total_estimated_tokens": skill_result.total_estimated_tokens,
        }
    }, "notification")

# 4. Pass to executor
executor = PlanExecutor(..., skill_result=skill_result)
```

---

## 9. Frontend Architecture

### State Management

```javascript
// main.js — Per-query skill selection
let activeSkills = [];        // [{name, param}] — cleared after each submission
window.activeSkills = activeSkills;

// main.js — Available skills from server
window.skillState = {
    activated: [              // From GET /v1/skills/activated
        {
            skill_id: "sql-expert",
            activation_name: "sql-expert",
            allowed_params: ["strict", "lenient"],
            param_descriptions: { strict: "...", lenient: "..." },
            ...
        }
    ]
};
```

### User Interaction Flow

```
1. PAGE LOAD
   └─ loadActivatedSkills() → GET /v1/skills/activated
      └─ window.skillState.activated = [skills...]

2. USER TYPES "!"
   └─ Input handler matches /!(\w*)$/
      └─ Filter activated skills by prefix
         └─ showSkillSelector(filtered) → emerald dropdown

3. USER SELECTS SKILL (Tab/Enter/Click)
   └─ selectSkill(index)
      └─ activeSkills.push({name, param: null})
         └─ _renderSkillBadges() → emerald badge in input area

4. USER TYPES ":param" (optional)
   └─ Input handler matches /^:(\S*)$/
      └─ activeSkills[last].param = typedParam
         └─ _renderSkillBadges() → badge updates to !name:param
         └─ showParamPicker() if allowed_params exist

5. USER SUBMITS QUERY
   └─ submitQuestion()
      └─ addMessage('user', text, ..., skillSpecs) → skill tags in chat
         └─ POST /ask_stream { skills: [...activeSkills] }
            └─ activeSkills = [] → cleared for next query

6. SSE EVENT: skills_applied
   └─ processStream() → UI.updateStatusWindow(..., 'skills')
      └─ _renderSkillStep() → emerald section in Live Status
```

### Event Handling

**SSE Streaming** (`eventHandlers.js:1093`):
```javascript
if (eventData.type === 'skills_applied') {
    UI.updateStatusWindow({
        step: 'Skills applied',
        details: eventData.payload,
        type: 'skills_applied'
    }, false, 'skills');
}
```

**REST Notifications** (`notifications.js`):
```javascript
if (eventType === 'skills_applied') {
    UI.updateStatusWindow({
        step: 'Skills applied',
        details: event.payload,
        type: 'skills_applied'
    }, false, 'skills');
    return;
}
```

**Historical Turn Reload** (`eventHandlers.js:1797`):
```javascript
function _renderSkillEventsForReload(turnData, container) {
    const skills = turnData.skills_applied || [];
    if (skills.length === 0) return;
    // Render emerald divider + skill names
}
```

### Chat Message Rendering (`ui.js:1127-1140`)

```javascript
// In addMessage() — skill tags for user messages
if (role === 'user' && skillSpecs && skillSpecs.length > 0) {
    skillSpecs.forEach(spec => {
        const skillTag = document.createElement('span');
        skillTag.className = 'skill-tag';
        skillTag.textContent = `!${spec.name}${spec.param ? ':' + spec.param : ''}`;
        metaContainer.appendChild(skillTag);
    });
}
```

### Session Load Path (`sessionManagement.js:750`)

When loading a session from the server, skill tags are restored from stored metadata:

```javascript
UI.addMessage('user', msg.content, ..., msg.skill_specs || null);
```

### Skill Configuration Tab (`skillHandler.js`)

The Skills tab in the Setup panel provides:

- **Skill Grid**: Cards showing all available skills with activation toggle
- **Filter Bar**: By tag, source (built-in/user), status (active/inactive), sort order
- **Skill Editor**: Three-level progressive disclosure (Citizen/Intermediate/Expert)
- **Import/Export**: `.zip` format for portability
- **Hot Reload**: Refresh skills from disk without restart

#### Editor Levels

| Level | Fields |
|-------|--------|
| **Citizen** | Name, description, instructions (markdown), tags, token estimate |
| **Intermediate** | + Injection target, parameter editor, param descriptions |
| **Expert** | Raw markdown content, raw manifest.json |

---

## 10. Built-in Skills

Five built-in skills ship with the platform in `skills/builtin/`:

### sql-expert

| Field | Value |
|-------|-------|
| **Purpose** | SQL best practices, optimization, conventions |
| **Injection** | `system_prompt` |
| **Params** | `strict` (enforce ANSI compliance), `lenient` (accept valid SQL) |
| **Tags** | sql, database, best-practices, optimization |
| **Use Cases** | Writing queries, optimizing slow queries, SQL conventions |

### table-format

| Field | Value |
|-------|-------|
| **Purpose** | Format all data as clean Markdown tables |
| **Injection** | `system_prompt` |
| **Params** | None |
| **Tags** | formatting, table, markdown |
| **Use Cases** | Query results as tables, side-by-side comparisons |

### concise

| Field | Value |
|-------|-------|
| **Purpose** | Brief, focused responses without filler |
| **Injection** | `system_prompt` |
| **Params** | None |
| **Tags** | style, brevity, concise |
| **Use Cases** | Quick answers, batch processing, dashboard summaries |

### detailed

| Field | Value |
|-------|-------|
| **Purpose** | Thorough analysis with reasoning and alternatives |
| **Injection** | `system_prompt` |
| **Params** | None |
| **Tags** | style, thorough, analysis |
| **Use Cases** | Deep analysis, decision support, complex relationships |

### step-by-step

| Field | Value |
|-------|-------|
| **Purpose** | Chain-of-thought reasoning with numbered steps |
| **Injection** | `system_prompt` |
| **Params** | None |
| **Tags** | reasoning, chain-of-thought, methodology |
| **Use Cases** | Understanding query logic, debugging data issues |

---

## 11. Admin Governance

### Settings (`settings.py`)

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `skills_mode` | `"all"` \| `"selective"` | `"all"` | Filter mode |
| `disabled_skills` | `List[str]` | `[]` | Skills to block (in selective mode) |
| `user_skills_enabled` | `bool` | `true` | Can users create custom skills? |
| `auto_skills_enabled` | `bool` | `false` | Phase 2: automatic skill selection |

### Governance Predicates

```python
is_skill_available(skill_id)    # True unless mode="selective" AND in disabled list
are_user_skills_enabled()       # Whether custom creation is allowed
are_auto_skills_enabled()       # Phase 2 feature flag
```

### Enforcement Points

1. **API Level**: `GET /v1/skills` and `GET /v1/skills/activated` filter by governance
2. **Execution Level**: `execution_service.py:465` checks `is_skill_available()` before resolving
3. **Frontend Level**: Disabled skills hidden from `!` autocomplete (filtered server-side)

---

## 12. CSS & Visual Design

### Color Scheme: Emerald Green

Skills use emerald green throughout the UI, distinct from extensions (amber/yellow).

| Token | Value | Usage |
|-------|-------|-------|
| Primary | `#10b981` | Borders, accents |
| Display | `#34d399` | Text, badge labels |
| Light | `#6ee7b7` | Highlights |
| BG 20% | `rgba(16, 185, 129, 0.2)` | Badge backgrounds |
| BG 15% | `rgba(16, 185, 129, 0.15)` | Dropdown items |
| Border | `rgba(16, 185, 129, 0.3)` | Borders |
| Invalid | `rgba(239, 68, 68, 0.6)` | Invalid param state |

### Key CSS Classes

| Class | Location | Purpose |
|-------|----------|---------|
| `.skill-tag` | Chat messages | Emerald badge on user messages |
| `.active-skill-badge` | Input area | Selected skill badge |
| `.active-skill-badge--invalid` | Input area | Invalid parameter indicator |
| `.active-skill-badge__remove` | Input area | Remove button (x) |
| `#skill-selector` | Dropdown | `!` autocomplete container |
| `.skill-item` | Dropdown | Individual skill entry |
| `.skill-item.skill-highlighted` | Dropdown | Keyboard-selected item |
| `.skill-item-badge` | Dropdown | `!name` badge in item |
| `.skill-item-name` | Dropdown | Skill display name |
| `.skill-item-description` | Dropdown | Skill description text |
| `.skill-step` | Live Status | Skill event in status window |

### Visual Comparison

```
Skills (emerald):     Extensions (amber):
┌─────────────────┐   ┌─────────────────┐
│ !sql-expert     │   │ @json-export    │
│ #34d399 text    │   │ #fbbf24 text    │
│ emerald border  │   │ amber border    │
└─────────────────┘   └─────────────────┘
```

---

## 13. File Reference

### Backend

| File | Purpose |
|------|---------|
| `src/trusted_data_agent/skills/models.py` | `SkillSpec`, `SkillContent`, `SkillResult` data classes |
| `src/trusted_data_agent/skills/loader.py` | Content loading, param block resolution |
| `src/trusted_data_agent/skills/manager.py` | Discovery pipeline, singleton `SkillManager` |
| `src/trusted_data_agent/skills/db.py` | Per-user activation CRUD (`user_skills` table) |
| `src/trusted_data_agent/skills/settings.py` | Admin governance (`skill_settings` table) |
| `src/trusted_data_agent/agent/execution_service.py` | Skill resolution at lines 455-494, history at 312-324 |
| `src/trusted_data_agent/agent/executor.py` | Injection at 2654-2679 (llm_only), 3564-3587 (rag_focused) |
| `src/trusted_data_agent/agent/planner.py` | Injection at 2752-2759 (tool_enabled) |
| `src/trusted_data_agent/api/rest_routes.py` | REST skill endpoints, skill_specs in query execution |
| `src/trusted_data_agent/api/routes.py` | SSE skill passthrough in `/ask_stream` |
| `src/trusted_data_agent/api/admin_routes.py` | Skill governance endpoints |

### Frontend

| File | Purpose |
|------|---------|
| `static/js/handlers/skillHandler.js` | Skills tab, card grid, filter bar, editor dialog |
| `static/js/main.js` | `!` trigger, badge system, `loadActivatedSkills()`, autocomplete |
| `static/js/ui.js` | `addMessage()` skill tags, `_renderSkillStep()`, status window routing |
| `static/js/eventHandlers.js` | `processStream()` skill events, `_renderSkillEventsForReload()` |
| `static/js/notifications.js` | `skills_applied` handler in `_dispatchRestEvent()` |
| `static/js/handlers/sessionManagement.js` | Session load with `skill_specs` passthrough |
| `static/css/main.css` | All `.skill-*` CSS classes |

### Built-in Skills

| Directory | Skill |
|-----------|-------|
| `skills/builtin/sql-expert/` | SQL best practices with strict/lenient params |
| `skills/builtin/table-format/` | Markdown table formatting |
| `skills/builtin/concise/` | Brief, focused responses |
| `skills/builtin/detailed/` | Thorough analysis |
| `skills/builtin/step-by-step/` | Chain-of-thought reasoning |

### Database

| File | Table |
|------|-------|
| `schema/15_skills.sql` | `user_skills` |
| `schema/16_skill_settings.sql` | `skill_settings` |
