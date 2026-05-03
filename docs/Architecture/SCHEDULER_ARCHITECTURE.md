# Task Scheduler Architecture

> **Always-on autonomous execution** — transforms Uderia from a reactive assistant into a proactive agent by running scheduled prompts through the identical execution pipeline as user-submitted queries, with per-task governance, concurrency control, and multi-channel result delivery.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [File Structure](#2-file-structure)
3. [Architecture Diagram](#3-architecture-diagram)
4. [Component Layer (TDA_Scheduler)](#4-component-layer-tda_scheduler)
   - [Tool Definition](#tool-definition)
   - [Handler](#handler)
   - [Actions Reference](#actions-reference)
5. [Execution Engine (task_scheduler.py)](#5-execution-engine-task_schedulerpy)
   - [APScheduler Integration](#apscheduler-integration)
   - [Schedule Formats](#schedule-formats)
   - [Execution Pipeline](#execution-pipeline)
   - [Session Context Model](#session-context-model)
   - [Overlap Policy](#overlap-policy)
   - [Token Budget Guard](#token-budget-guard)
   - [Result Delivery Channels](#result-delivery-channels)
6. [Frontend Renderer](#6-frontend-renderer)
   - [Render Modes](#render-modes)
   - [Split Panel State Machine](#split-panel-state-machine)
   - [Task Card Anatomy](#task-card-anatomy)
   - [In-Panel Actions](#in-panel-actions)
7. [Database Schema](#7-database-schema)
8. [Notification Pipeline](#8-notification-pipeline)
9. [REST API Endpoints](#9-rest-api-endpoints)
10. [Governance Model](#10-governance-model)
11. [LLM Instructions](#11-llm-instructions)
12. [Design Decisions](#12-design-decisions)
13. [File Reference](#13-file-reference)

---

## 1. System Overview

### What the Scheduler Does

The Task Scheduler allows users — through natural conversation — to create recurring agent tasks. Each task stores a prompt and a schedule (cron expression or fixed interval). When a task fires, it runs through the identical `execute_query()` pipeline as any user-submitted query: the same LLM, the same profile, the same MCP tools. The only additions are:

- **Persistence** — tasks and run history stored in SQLite
- **Concurrency governance** — overlap policy controls what happens when a run fires while the previous one is still executing
- **Token budget** — optional per-task token limit, checked post-run
- **Delivery channels** — results routed to email or webhook in addition to the live session feed

### Design Principle

> A scheduled task is not a special execution mode — it is a queued user query with a timer.

This means scheduled tasks benefit automatically from every platform improvement: new LLM providers, updated prompts, MCP tool changes, profile improvements. There is no separate "agent runner" to maintain.

### Architecture Position

```
                ┌──────────────────┐
                │   User (chat)    │
                └────────┬─────────┘
                         │ natural language
                         ▼
               ┌─────────────────────┐
               │   LLM + TDA_Sched.  │  ← component tool call
               └─────────┬───────────┘
                         │ ComponentRenderPayload
                         ▼
               ┌─────────────────────┐
               │  Scheduler Handler  │  ← handler.py (CRUD + list)
               └─────────┬───────────┘
                         │ upsert / query
                         ▼
               ┌─────────────────────┐
               │   SQLite DB         │  ← scheduled_tasks / scheduled_task_runs
               └─────────┬───────────┘
                         │ load on startup, live mutations
                         ▼
               ┌─────────────────────┐
               │   APScheduler       │  ← in-process async scheduler
               └─────────┬───────────┘
                         │ fires at schedule time
                         ▼
               ┌─────────────────────┐
               │ run_agent_execution │  ← identical to interactive query path
               └─────────┬───────────┘
                         │ notification events
                         ▼
               ┌─────────────────────┐
               │ SSE / Email / Hook  │  ← result delivery
               └─────────────────────┘
```

---

## 2. File Structure

```
components/builtin/scheduler/
├── manifest.json          # Component metadata, tool definition, render targets
├── handler.py             # SchedulerComponentHandler — CRUD + list via task_scheduler.py
├── renderer.js            # Split-panel interactive canvas (~950 lines)
└── instructions.json      # Intensity-keyed LLM guidance (none / medium / heavy)

src/trusted_data_agent/core/
└── task_scheduler.py      # APScheduler integration, execution engine, delivery channels

src/trusted_data_agent/api/
└── rest_routes.py         # 8 REST endpoints (list, create, read, update, delete, runs, run-now, status)

schema/
└── 28_scheduled_tasks.sql # DDL: scheduled_tasks, scheduled_task_runs, messaging_identities
```

---

## 3. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  CONVERSATION LAYER                                                  │
│                                                                      │
│  User: "Run the weekly sales report every Monday at 9 AM"           │
│       ↓                                                              │
│  LLM calls TDA_Scheduler(action='create', name='Weekly Sales',      │
│    prompt='Generate weekly sales report', schedule='0 9 * * 1',     │
│    session_context='new')                                            │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  COMPONENT LAYER  (components/builtin/scheduler/)                    │
│                                                                      │
│  handler.py                                                          │
│    process(arguments, context)                                       │
│      → create_task() / list_tasks() / delete_task() / etc.          │
│      → enrich tasks with _human_schedule, _next_runs, _session_ctx  │
│      → return ComponentRenderPayload(spec, tts_text)                │
│                                                                      │
│  renderer.js                                                         │
│    renderScheduler(containerId, payload)                             │
│      → _renderInlineToast()   — confirmation badge in chat          │
│      → openSchedulerSplitPanel() — live canvas on list/history      │
│      → _renderPanelBody()     — task grid with cards                │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PERSISTENCE LAYER  (task_scheduler.py + SQLite)                     │
│                                                                      │
│  scheduled_tasks           scheduled_task_runs                       │
│  ├── id (sched-{hex12})    ├── id                                   │
│  ├── user_uuid             ├── task_id → scheduled_tasks            │
│  ├── profile_id            ├── status (running/success/error/skip)  │
│  ├── name / prompt         ├── tokens_used / cost_usd               │
│  ├── schedule (cron/intv)  └── result_summary / skip_reason         │
│  ├── enabled                                                         │
│  ├── session_id (pinned)                                             │
│  ├── overlap_policy                                                  │
│  └── max_tokens_per_run                                              │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  SCHEDULING LAYER  (APScheduler AsyncIOScheduler)                    │
│                                                                      │
│  start_scheduler()                                                   │
│    → loads all enabled tasks from DB                                │
│    → registers each as CronTrigger or IntervalTrigger               │
│    → misfire_grace_time=60s, coalesce=True                          │
│                                                                      │
│  _fire_task(task_id)  ← called by APScheduler at schedule time      │
│    → loop.create_task(_execute_task_async(task_id))                  │
│                                                                      │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  EXECUTION LAYER  (run_agent_execution — identical to interactive)   │
│                                                                      │
│  _execute_task_async(task_id)                                        │
│    1. Overlap check (skip / queue / allow)                           │
│    2. Resolve session (pinned or create ephemeral)                  │
│    3. Emit new_session_created (if ephemeral)                        │
│    4. run_agent_execution(prompt, profile, source='scheduler')       │
│    5. Capture tokens + final_answer via _event_handler               │
│    6. Post-run token budget check (if max_tokens_per_run set)       │
│    7. Emit rest_task_complete → frontend renders Q&A                │
│    8. _deliver_result() → email / webhook / google_mail (deferred)  │
│    9. _record_run_end() → scheduled_task_runs row updated           │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Component Layer (TDA_Scheduler)

### Tool Definition

The tool is declared in `manifest.json` and exposed to the LLM as `TDA_Scheduler`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `action` | string | ✓ | `create` \| `list` \| `update` \| `delete` \| `enable` \| `disable` \| `run_now` \| `history` |
| `name` | string | create | Human-readable task name |
| `prompt` | string | create | Exact query the agent will run on schedule |
| `schedule` | string | create | Cron (e.g. `0 9 * * *`) or interval (e.g. `interval:1h`) |
| `task_id` | string | mutations | Required for update / delete / enable / disable / run_now / history |
| `session_context` | string | — | `'new'` (default, fresh session each run) or `'current'` (pin to invoking session) |
| `output_channel` | string | — | `'email'` \| `'webhook'` \| `null` |
| `output_config` | dict | — | Channel config: `{'to_address': '...'}` or `{'webhook_url': '...', 'bearer_token': '...'}` |
| `overlap_policy` | string | — | `'skip'` (default) \| `'queue'` \| `'allow'` |
| `max_tokens_per_run` | integer | — | Token budget per execution; `null` = unlimited |

### Handler

`SchedulerComponentHandler.process()` in `handler.py`:

1. Dispatches to the appropriate `task_scheduler.py` function based on `action`
2. For `create`: resolves `session_context` → passes `session_id=current_session` or `None`
3. Calls `list_tasks(user_uuid, profile_id)` after every mutation to return current state
4. Enriches each task with display-only fields (`_human_schedule`, `_next_runs`, `_session_context`)
5. Returns a `ComponentRenderPayload` with `spec`, `title`, `tts_text`, and metadata

The handler is marked `is_deterministic = True` — the component system skips LLM repair and passes the spec through unchanged to the renderer.

### Actions Reference

| Action | DB operation | Returns `affected_task_id`? | Panel behaviour |
|---|---|---|---|
| `create` | INSERT | ✓ (new task) | Toast; panel open → refresh; panel closed → no-op |
| `list` | SELECT | — | Toast + auto-opens split panel |
| `update` | UPDATE | ✓ | Toast; panel refreshed if open |
| `delete` | DELETE | — | Toast; panel refreshed if open |
| `enable` | UPDATE enabled=1 | ✓ | Toast; card re-rendered in place |
| `disable` | UPDATE enabled=0 | ✓ | Toast; card re-rendered in place |
| `run_now` | INSERT run record + trigger | ✓ | Toast; panel refreshed |
| `history` | SELECT runs | ✓ | Toast + opens panel in history view |

The `affected_task_id` drives the sort in `_renderPanelBody` — the modified task always floats to the top of the card grid.

---

## 5. Execution Engine (task_scheduler.py)

### APScheduler Integration

APScheduler's `AsyncIOScheduler` is started at app startup inside `@app.before_serving` in `main.py`:

```python
await start_scheduler()   # startup
await stop_scheduler()    # shutdown (@app.after_serving)
```

On startup, `start_scheduler()` loads all `enabled = 1` tasks from the DB and calls `_register_job(task)` for each. APScheduler runs in the same asyncio event loop as Quart — no threads, no separate processes.

APScheduler is an **optional dependency**. If not installed, a warning is logged and the scheduler starts in a disabled state. All REST endpoints remain available but `run-now` will fail gracefully.

### Schedule Formats

Two formats are supported, stored in the `schedule` column:

**Cron expression** (5-field, standard POSIX syntax):
```
"0 9 * * 1-5"   → weekdays at 09:00
"0 9 * * 1"     → every Monday at 09:00
"*/30 * * * *"  → every 30 minutes
```

**Interval shorthand** (prefix `interval:`):
```
"interval:30m"  → every 30 minutes
"interval:2h"   → every 2 hours
"interval:1d"   → every 24 hours
"interval:300s" → every 300 seconds
```

Both formats map to APScheduler trigger types:
- `interval:*` → `IntervalTrigger(seconds=N)`
- everything else → `CronTrigger(minute, hour, day, month, day_of_week)`

**APScheduler job settings** applied to every job:
- `misfire_grace_time=60` — if the server was down when the trigger fired, run it within 60 seconds of recovery
- `coalesce=True` — collapse multiple missed firings into one (prevents burst catch-up)
- `replace_existing=True` — update/enable/disable replace the job in-place without duplicates

### Execution Pipeline

When APScheduler fires a job, the synchronous `_fire_task(task_id)` wrapper posts `_execute_task_async(task_id)` onto the asyncio event loop:

```
APScheduler fires
    → _fire_task(task_id)  [sync]
    → loop.create_task(_execute_task_async(task_id))  [async]
        → overlap check
        → session resolution
        → run_agent_execution(prompt, profile, source='scheduler')
        → token budget check
        → rest_task_complete notification
        → result delivery
        → _record_run_end()
```

`run_agent_execution()` is the identical function used for interactive queries — the scheduler passes `source='scheduler'` so the frontend renders a "Scheduled" badge on the message.

### Session Context Model

Each task stores an optional `session_id` (the "pinned session"):

| `session_context` | `session_id` in DB | Execution behaviour |
|---|---|---|
| `'new'` (default) | `NULL` | Fresh ephemeral session created per run; `new_session_created` notification emitted; session appears in sidebar |
| `'current'` | Set at create time to the invoking session's ID | Task runs inside the user's existing session, inheriting full conversation history and profile context |

**Pinned session fallback**: if the pinned session was archived or deleted, execution falls back to creating a new ephemeral session with a log warning. The pinned `session_id` is NOT cleared — the next run may succeed if the session is restored.

**new_session_created suppression**: for pinned-session runs, `new_session_created` is intentionally NOT emitted (the session already exists in the sidebar).

### Overlap Policy

Controlled by the `overlap_policy` column (default: `'skip'`):

| Policy | Behaviour when previous run is still executing |
|---|---|
| `skip` | New run is immediately recorded as `status='skipped'` with `skip_reason='Previous run still active'`; execution is aborted |
| `queue` | New run waits up to 300 seconds for the previous run to complete; proceeds after; if timeout, continues anyway |
| `allow` | Concurrent runs permitted; use only for idempotent tasks that can safely run in parallel |

The `_running_tasks: dict[task_id, asyncio.Task]` module-level dict tracks active executions. It is cleared in the `finally` block of `_execute_task_async`.

### Token Budget Guard

`max_tokens_per_run` (integer, `NULL` = unlimited) provides a post-run cost guard:

```python
if max_tokens and tokens_used > max_tokens:
    _record_run_end(run_id, "error",
        result_summary=f"Token budget exceeded ({tokens_used} > {max_tokens})",
        tokens_used=tokens_used)
    return   # skip result delivery and rest_task_complete notification
```

Mid-run cancellation is not currently supported — the execution pipeline runs to completion and the budget is checked afterward. The practical effect is preventing result delivery and flagging the run as an error when the budget is blown. The `last_run_status` on the task is updated to `'error'`.

### Result Delivery Channels

After successful execution, `_deliver_result(task, result_summary, session_id)` is called if `output_channel` is set:

**`email`**: Calls `EmailService.send_email(to_address, subject, result_summary)` (async). Uses the platform's existing SMTP / SendGrid / SES configuration from `email_service.py`. Subject format: `[Uderia] Scheduled task: {task_name}`.

**`webhook`**: POSTs a JSON payload to `webhook_url` via `httpx.AsyncClient`. Supports optional `bearer_token` in the `Authorization` header. Payload:
```json
{
  "task_id": "sched-...",
  "task_name": "...",
  "session_id": "...",
  "result": "...",
  "completed_at": "2026-05-01T09:00:00+00:00"
}
```

**`google_mail`**: Deferred to Track C (Google OAuth connector). Currently logs an info message and skips delivery.

All delivery failures are caught and logged as warnings — they do not fail the run record.

---

## 6. Frontend Renderer

### Render Modes

The renderer (`renderer.js`) operates in two modes depending on the action:

| Mode | Trigger | What renders |
|---|---|---|
| **Inline toast** | Every action | A compact confirmation badge in the chat message container |
| **Split panel** | `list` or `history` action (auto); any action when panel already open | Persistent side panel occupying ≈50% of the chat area |

### Split Panel State Machine

The split panel follows a mutual-exclusion pattern shared across scheduler, canvas, and knowledge graph — only one panel can be open at a time.

```
renderScheduler(containerId, payload)
    │
    ├── _renderInlineToast(container, spec)
    │       │  [list / history only]
    │       └── setTimeout(() => openSchedulerSplitPanel(_currentSpec || spec), 80ms)
    │
    ├── _currentSpec = spec          ← always updated, even when panel is closed
    │
    └── [panel already open?]
            └── _renderPanelBody(spec)   ← immediate refresh
```

**Key invariant**: `_currentSpec` is always the most recent server-side spec, regardless of panel state. This ensures that:
- Click handlers on old "Open Scheduler" toasts show current data, not stale data
- The 80ms delayed auto-open uses `_currentSpec` (not the captured `spec` closure), so if a delete fires within the same LLM turn as a list, the panel opens with post-deletion data

**Mutual exclusion** in `openSchedulerSplitPanel()`: closes canvas split panel and knowledge graph panel before opening, with 350ms CSS transition.

### Task Card Anatomy

Each task renders as a `.sched-card` element:

```
┌─────────────────────────────────────────────────────┐
│  ● Active                           [next run chip] │
│  Task Name                                          │
│  [schedule meta]  ·  [session badge]               │
│  Prompt preview text…                [Show more ▼] │
│  [run-chips row: Mon 09:00  Tue 09:00  ...]         │
│  [Pause] [History] [Run here] [Delete]              │
└─────────────────────────────────────────────────────┘
```

**Status indicator**: green = enabled, grey = disabled, blue pulsing = running.

**Prompt preview**: truncated at 120 characters with an expand/collapse toggle. The full text is stored in `data-full` on the text element and toggled client-side — no server round-trip.

**Session badge**: plain-text label ("current session" / "new session") — never emoji per platform icon policy.

**Run chips**: up to 5 upcoming fire times computed by `_next_runs()` using APScheduler's `CronTrigger.get_next_fire_time()` chain. Shown as compact date+time badges.

**Affected task sort**: the task with `id === affected_task_id` always sorts first in the grid after a mutation, drawing the user's eye to the changed item.

### In-Panel Actions

Button click handlers call the direct REST API (not TDA_Scheduler) for low-latency in-place updates:

| Button | REST call | DOM update |
|---|---|---|
| **Pause / Enable** | `PUT /v1/scheduled-tasks/{id}` | Card re-rendered in place; `_currentSpec.tasks` mutated |
| **Run here** | `window.EventHandlers.triggerChatQuery(prompt)` | Panel closes; prompt submitted to current chat |
| **History** | — | Re-renders panel body in history view; back button returns to task list |
| **Delete** | `DELETE /v1/scheduled-tasks/{id}` | Card animates out (opacity + translateX); `_currentSpec.tasks` filtered; header count updated |

The `_wireCardActions(root, spec)` function attaches all button listeners. It is called both on initial render and after in-place card re-renders (enable/disable) to prevent stale listeners on replaced DOM nodes.

---

## 7. Database Schema

```sql
-- Primary task store
CREATE TABLE scheduled_tasks (
    id               TEXT PRIMARY KEY,       -- 'sched-{hex12}'
    user_uuid        TEXT NOT NULL,
    profile_id       TEXT NOT NULL,
    name             TEXT NOT NULL,
    prompt           TEXT NOT NULL,
    schedule         TEXT NOT NULL,          -- cron or 'interval:Ns/m/h/d'
    enabled          INTEGER DEFAULT 1,
    session_id       TEXT,                   -- NULL = new session each run
    last_run_at      TEXT,
    last_run_status  TEXT,                   -- success | error | timeout | skipped
    next_run_at      TEXT,
    output_channel   TEXT,                   -- null | email | webhook | google_mail
    output_config    TEXT,                   -- JSON blob
    max_tokens_per_run INTEGER,              -- NULL = no limit
    overlap_policy   TEXT DEFAULT 'skip',    -- skip | queue | allow
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
);

-- Immutable run log
CREATE TABLE scheduled_task_runs (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
    bg_task_id      TEXT,                    -- links to live notification stream
    started_at      TEXT,
    completed_at    TEXT,
    status          TEXT,                    -- running | success | error | skipped
    skip_reason     TEXT,
    result_summary  TEXT,                    -- first 500 chars of final_answer
    tokens_used     INTEGER,
    cost_usd        REAL
);

-- Future: Google OAuth tokens for google_mail delivery (Track C)
CREATE TABLE messaging_identities (
    user_uuid        TEXT NOT NULL,
    platform         TEXT NOT NULL,          -- 'google'
    platform_user_id TEXT NOT NULL,
    access_token     TEXT,                   -- Fernet-encrypted
    refresh_token    TEXT,                   -- Fernet-encrypted
    token_expiry     TEXT,
    PRIMARY KEY (user_uuid, platform)
);
```

**Indexes**:
- `idx_scheduled_task_runs_task_id` — fast history queries per task
- `idx_scheduled_tasks_user_uuid` — fast per-user task listing
- `idx_scheduled_tasks_enabled` — fast startup load of enabled tasks

**Schema migration**: `_ensure_columns()` in `task_scheduler.py` runs at startup and after schema creation to add any missing columns (e.g. `session_id`) to existing databases via `ALTER TABLE`. It is a no-op when the column already exists or the table doesn't exist yet.

---

## 8. Notification Pipeline

Scheduled task executions push the same notification events as the REST query pipeline. This is what makes ephemeral task sessions appear live in the sidebar and renders the Q&A in the chat log when a user switches to a task session.

```
_execute_task_async()
    │
    ├── new_session_created         ← session appears in sidebar (ephemeral only)
    │
    ├── rest_task_update (× N)      ← wraps every execution event (status, tokens, etc.)
    │       payload: { task_id: bg_task_id, session_id, event }
    │
    └── rest_task_complete          ← triggers frontend Q&A render
            payload: {
              task_id: bg_task_id,
              session_id,
              turn_id,
              user_input: task.prompt,
              final_answer,
              profile_tag,
              source: 'scheduler'    ← renders "Scheduled" badge on message
            }
```

Events are delivered via `_emit_notification(user_uuid, notification)` which enqueues to all active SSE queues for that user (`APP_STATE['notification_queues'][user_uuid]`). If the user is not connected (no active SSE), events are silently dropped — notifications are fire-and-forget.

The `source: 'scheduler'` field in `rest_task_complete` causes `notifications.js` to display a "Scheduled" source badge on both the user message and assistant message when they are rendered in the chat log.

---

## 9. REST API Endpoints

All endpoints require JWT authentication (`@require_auth`). Users can only access their own tasks.

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/scheduled-tasks` | List tasks (optional `?profile_id=` filter) |
| `POST` | `/v1/scheduled-tasks` | Create task — validates admin enable state |
| `GET` | `/v1/scheduled-tasks/{id}` | Read single task |
| `PUT` | `/v1/scheduled-tasks/{id}` | Update task fields (name, prompt, schedule, enabled, etc.) |
| `DELETE` | `/v1/scheduled-tasks/{id}` | Delete task and deregister from APScheduler |
| `GET` | `/v1/scheduled-tasks/{id}/runs` | Run history (max 100 entries) |
| `POST` | `/v1/scheduled-tasks/{id}/run-now` | Manually trigger; returns `{ run_id }` |
| `GET` | `/v1/scheduler/status` | Health check: `{ running, globally_enabled, job_count }` |

**POST `/v1/scheduled-tasks` guards**:
1. Checks `is_scheduler_globally_enabled()` — returns 403 if admin has disabled the component
2. Validates required fields: `name`, `prompt`, `schedule`

**PUT `/v1/scheduled-tasks/{id}`** re-registers the job in APScheduler after any field update (via `update_task()` which calls `_unregister_job` + `_register_job`).

**DELETE `/v1/scheduled-tasks/{id}`** calls `delete_task()` which deletes from DB and calls `_unregister_job()`.

---

## 10. Governance Model

### Admin Enable

The scheduler component is governed by the platform's component settings system. Admins can disable it globally via the Platform Components panel. The `is_scheduler_globally_enabled()` function checks `component_settings.disabled_components`.

When globally disabled:
- `TDA_Scheduler` tool calls return a `ComponentRenderPayload` with an error message
- REST `POST /v1/scheduled-tasks` returns HTTP 403
- Already-running APScheduler jobs continue until the next app restart

### Profile Enable

Individual profiles must have the scheduler component enabled in their `componentConfig`:

```json
{
  "componentConfig": {
    "scheduler": { "enabled": true, "intensity": "medium" }
  }
}
```

This is checked in `is_scheduler_enabled_for_profile(profile_id, user_uuid)` at the component level.

### Task Ownership

All DB operations filter by `user_uuid`. Users cannot access, modify, or trigger other users' tasks. Tasks are also scoped by `profile_id` in list queries — tasks created with profile A do not appear when listing from profile B, unless `profile_id = ''` (legacy tasks with no profile scope).

---

## 11. LLM Instructions

Instructions are stored in `instructions.json` with three intensity levels:

| Level | Behaviour |
|---|---|
| `none` | Empty — LLM receives no guidance; tool won't be invoked proactively |
| `medium` | Invoke when user **explicitly asks** about scheduling; includes cron/interval examples |
| `heavy` | **Proactively suggest** scheduling after recurring queries; always clarify `session_context` preference |

Both `medium` and `heavy` include:
- All 8 action descriptions with required parameters
- Cron examples (`0 9 * * *`, `0 9 * * 1-5`, `0 * * * *`)
- Interval examples (`interval:30m`, `interval:2h`, `interval:1d`)
- `session_context` explanation — always ask user for preference when creating
- **No emoji rule** — the renderer handles all visual state; LLM text must use plain words

---

## 12. Design Decisions

### Same Pipeline, Not a Separate Runner

The scheduler does not implement its own LLM invocation or MCP tool execution. It calls `run_agent_execution()` — the same function used for every interactive query. This was a deliberate choice: it means every platform improvement (new models, updated prompts, MCP tool additions) benefits scheduled tasks automatically, with zero maintenance overhead.

### `_currentSpec` Always Updated

The renderer's `_currentSpec` is updated on every `renderScheduler()` call, even when the split panel is closed. Earlier versions only updated it when the panel was open, causing stale data when the user deleted a task and then asked to reopen the scheduler — the panel would show the pre-deletion task list because `_currentSpec` hadn't been refreshed. Always writing `_currentSpec` ensures click handlers and future auto-opens always have the latest server state.

### Inline Toast + Split Panel Separation

Non-list actions (create, delete, enable, disable, run_now) render only an inline confirmation toast in the chat — they do not auto-open the split panel. This respects the user's panel state: if they closed the panel, a create action won't force it back open. The panel is only auto-opened by `list` and `history` actions, which are explicit requests to see the canvas.

### coalesce=True on APScheduler Jobs

Every job is registered with `coalesce=True`. If the server was down for several trigger intervals, APScheduler will fire the job once (not once per missed interval) after recovery. This prevents burst catch-up runs that could overwhelm the system or send duplicate results.

### Post-Run Token Budget

`max_tokens_per_run` is enforced post-run, not pre-run. Mid-run cancellation would require threading a cancellation signal through the entire execution pipeline — a significant architectural change. The post-run guard achieves the core goal (preventing runaway cost) at the cost of charging for the over-budget run. The run is marked `status='error'` and result delivery is skipped.

### Ephemeral Sessions for New-Context Tasks

When `session_context='new'`, a fresh ephemeral session is created per run. This is marked `is_temporary=True` with a `temporary_purpose` label so the session management UI can identify and clean them up. The session appears in the sidebar with the `new_session_created` notification so users can inspect the execution history.

---

## 13. File Reference

| File | Role |
|---|---|
| [components/builtin/scheduler/manifest.json](../../components/builtin/scheduler/manifest.json) | Component declaration: tool definition, render targets, profile defaults |
| [components/builtin/scheduler/handler.py](../../components/builtin/scheduler/handler.py) | `SchedulerComponentHandler` — all 8 actions, task enrichment, ComponentRenderPayload |
| [components/builtin/scheduler/renderer.js](../../components/builtin/scheduler/renderer.js) | Split panel UI, inline toasts, task cards, prompt expand/collapse, in-panel CRUD |
| [components/builtin/scheduler/instructions.json](../../components/builtin/scheduler/instructions.json) | LLM guidance at none / medium / heavy intensity |
| [src/trusted_data_agent/core/task_scheduler.py](../../src/trusted_data_agent/core/task_scheduler.py) | APScheduler integration, CRUD, execution engine, delivery channels |
| [src/trusted_data_agent/api/rest_routes.py](../../src/trusted_data_agent/api/rest_routes.py) | 8 REST endpoints (lines ~15811–15952) |
| [schema/28_scheduled_tasks.sql](../../schema/28_scheduled_tasks.sql) | DDL: `scheduled_tasks`, `scheduled_task_runs`, `messaging_identities` |
| [src/trusted_data_agent/main.py](../../src/trusted_data_agent/main.py) | `start_scheduler()` / `stop_scheduler()` wired to Quart app lifecycle |
| [src/trusted_data_agent/auth/email_service.py](../../src/trusted_data_agent/auth/email_service.py) | `EmailService.send_email()` — used by email delivery channel |
