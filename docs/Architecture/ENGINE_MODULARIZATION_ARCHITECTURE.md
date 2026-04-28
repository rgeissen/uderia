# Engine Modularization Architecture

## Overview

Prior to this refactor, all four IFOC profile type execution paths lived inside a single `PlanExecutor.run()` method in `executor.py` (~6,800 lines). The engine modularization extracts each path into a dedicated, independently maintainable **engine class** wired through a lightweight **EngineRegistry**, following the [Method Object](https://refactoring.guru/replace-method-with-method-object) pattern.

**Key invariant:** `executor.py` remains the single shared infrastructure hub (session management, LLM handler, MCP adapter, context window). Engines receive the initialized `PlanExecutor` instance as their execution context — they do not duplicate any infrastructure.

---

## Package Structure

```
src/trusted_data_agent/agent/engines/
├── __init__.py           # Import-order-controlled registration; exports all engine classes
├── base.py               # ExecutionEngine ABC
├── registry.py           # EngineRegistry (register decorator + resolve)
├── ideate_engine.py      # IdeateEngine     — llm_only
├── focus_engine.py       # FocusEngine      — rag_focused
├── coordinate_engine.py  # CoordinateEngine — genie
├── optimize_engine.py    # OptimizeEngine   — tool_enabled
└── conversation_engine.py# ConversationEngine — llm_only + useMcpTools / component tools
```

---

## Core Abstractions

### `ExecutionEngine` (base.py)

Abstract base class. Every engine declares a `profile_type` class variable and implements `run()`.

```python
class ExecutionEngine(ABC):
    profile_type: ClassVar[str] = ""

    @classmethod
    def applies_to(cls, profile: Dict[str, Any]) -> bool:
        """Override for complex eligibility (e.g. llm_only + useMcpTools routing)."""
        return bool(cls.profile_type) and profile.get("profile_type") == cls.profile_type

    @abstractmethod
    async def run(self, executor: "PlanExecutor") -> AsyncGenerator[str, None]:
        """Yield SSE-formatted event strings. Must end with a final_answer event."""
```

### `EngineRegistry` (registry.py)

Class-level list of all registered engine classes. Last-registered wins (specialisations override base engines).

```python
@EngineRegistry.register          # decorator fires at import time
class MyEngine(ExecutionEngine):
    profile_type = "my_new_type"
    ...
```

Registration happens automatically when `engines/__init__.py` imports each engine module. No manual registration step.

---

## Registered Engines

| Engine | Profile Type | IFOC Label | Colour |
|--------|-------------|-----------|--------|
| `IdeateEngine` | `llm_only` | Ideate | Green |
| `ConversationEngine` | `llm_only_with_tools`¹ | Ideate + tools | Green |
| `FocusEngine` | `rag_focused` | Focus | Blue |
| `OptimizeEngine` | `tool_enabled` | Optimize | Orange |
| `CoordinateEngine` | `genie` | Coordinate | Purple |

¹ `ConversationEngine.applies_to()` is overridden: it claims `llm_only` profiles where `useMcpTools=True`. The `has_component_tools` case requires a runtime check (component manager) and is detected in `executor.run()` before the registry is consulted.

---

## Dispatch Flow

`executor.run()` dispatches to engines **directly** (not via `EngineRegistry.resolve()`). The runtime conditions that determine which engine runs were already computed earlier in `run()`, so the dispatch is a series of `if/elif` guards that delegate to the appropriate engine:

```python
# executor.py — simplified dispatch sequence
if is_llm_only:
    async for event in IdeateEngine().run(self): yield event; return

if is_conversation_with_tools:
    async for event in ConversationEngine().run(self): yield event; return

if is_rag_focused:
    async for event in FocusEngine().run(self): yield event; return

# Default: tool_enabled → OptimizeEngine
async for event in OptimizeEngine().run(self): yield event
```

Genie profiles are dispatched differently: `execution_service.py` calls `CoordinateEngine().execute_genie()` directly (not via `run()`). A future unification phase will route genie through `EngineRegistry.resolve()` → `CoordinateEngine.run()` so it benefits from the same PlanExecutor safeguards as other profiles.

---

## What Each Engine Does

### IdeateEngine (llm_only)
Direct LLM conversation. Optional knowledge retrieval when `knowledgeConfig.enabled=True`. No MCP tools, no strategic planning. Single LLM call per turn. Extracted from `PlanExecutor.run()` (formerly ~670 lines).

### ConversationEngine (llm_only + tools)
LangChain ReAct agent path. Wraps `_execute_conversation_with_tools()`. Used when `useMcpTools=True` or active component tools are present. Enables tool calling without the multi-phase planning overhead of OptimizeEngine. Extracted as Phase 5 (~715 lines).

### FocusEngine (rag_focused)
Mandatory knowledge retrieval from configured collections followed by LLM synthesis. No MCP tools, no Planner/Executor pipeline. Extracted from `PlanExecutor.run()` (formerly ~1,073 lines).

### CoordinateEngine (genie)
Multi-expert coordinator. Wraps `GenieCoordinator` to route queries to child (slave) profiles and synthesise their responses. Extracted from `execution_service.py` (formerly inline `execute_genie()` function). Also exposes `execute_genie()` as a public method for the current dispatch path in `execution_service.py`.

### OptimizeEngine (tool_enabled)
Full Planner/Executor pipeline: strategic planning → 9 rewrite passes → phase-by-phase tactical execution → self-correction → autonomous recovery. The most complex engine. Extracted from `PlanExecutor.run()` (formerly ~1,085 lines). **executor.py was reduced from ~6,800 → ~3,160 lines** as a result of the full modularization.

---

## Adding a New Engine

1. **Create the file:** `src/trusted_data_agent/agent/engines/my_engine.py`
2. **Subclass and register:**
   ```python
   from .registry import EngineRegistry
   from .base import ExecutionEngine

   @EngineRegistry.register
   class MyEngine(ExecutionEngine):
       profile_type = "my_new_type"  # must match profile.profile_type in DB

       async def run(self, executor):
           # access all shared state via executor.*
           yield executor._format_sse_with_depth({"step": "...", "type": "..."})
   ```
3. **Register on import:** Add `from .my_engine import MyEngine  # noqa: F401` to `engines/__init__.py`
4. **Wire dispatch:** Add the eligibility check in `executor.run()` and delegate.

No other file changes required.

---

## Extraction Phases

The extraction was performed in 5 sequential phases, each independently committed and testable:

| Phase | Engine | Lines Extracted | executor.py After |
|-------|--------|----------------|-------------------|
| 0 | Base infrastructure (ABC + registry) | — | ~6,800 |
| 1 | IdeateEngine | ~670 | ~6,130 |
| 2 | FocusEngine | ~1,073 | ~5,060 |
| 3 | CoordinateEngine | ~360 | ~4,700 |
| 4 | OptimizeEngine | ~1,085 | ~3,875 |
| 5 | ConversationEngine | ~715 | ~3,160 |

---

## Design Rationale

### Why Method Object (not dependency injection)?

All shared infrastructure (LLM client, MCP adapter, session manager, context window) already lives on `PlanExecutor`. The shortest path to modularization is to pass `self` (the executor) as the engine's context, giving engines full access without duplication or re-wiring.

### Why direct import dispatch instead of EngineRegistry.resolve()?

The conditions for routing (is_llm_only, is_rag_focused, etc.) are computed several hundred lines before dispatch and depend on decrypted profile data, runtime feature flags, and component state — not just `profile.profile_type`. Encoding these conditions in `applies_to()` would require engines to import and re-evaluate the same config, coupling them to things they don't otherwise need. The registry is still useful for programmatic introspection and as the mechanism for a future unified genie dispatch.

### Why no EngineContext dataclass yet?

Introducing a dataclass would require identifying every `executor.*` attribute accessed by every engine — a broad surface area that risks introducing bugs. The Method Object pattern is the minimum-change extraction; a lean `EngineContext` is a follow-up refactor once the extraction is stable.

---

## File Reference

| File | Purpose |
|------|---------|
| `src/trusted_data_agent/agent/engines/__init__.py` | Import-order-controlled registration; package public API |
| `src/trusted_data_agent/agent/engines/base.py` | `ExecutionEngine` ABC with `applies_to()` and `run()` |
| `src/trusted_data_agent/agent/engines/registry.py` | `EngineRegistry` — register decorator, resolve, introspection |
| `src/trusted_data_agent/agent/engines/ideate_engine.py` | `IdeateEngine` (llm_only) |
| `src/trusted_data_agent/agent/engines/focus_engine.py` | `FocusEngine` (rag_focused) |
| `src/trusted_data_agent/agent/engines/coordinate_engine.py` | `CoordinateEngine` (genie) |
| `src/trusted_data_agent/agent/engines/optimize_engine.py` | `OptimizeEngine` (tool_enabled) |
| `src/trusted_data_agent/agent/engines/conversation_engine.py` | `ConversationEngine` (llm_only + tools) |
| `src/trusted_data_agent/agent/executor.py` | `PlanExecutor` — shared infrastructure + dispatch routing |
| `src/trusted_data_agent/agent/execution_service.py` | Genie dispatch via `CoordinateEngine().execute_genie()` |

---

## Related Documents

- [Fusion Optimizer Architecture](FUSION_OPTIMIZER_ARCHITECTURE.md) — End-to-end execution pipeline for OptimizeEngine
- [Coordinator Architecture](COORDINATOR_ARCHITECTURE.md) — GenieCoordinator internals wrapped by CoordinateEngine
- [Context Window Architecture](CONTEXT_WINDOW_ARCHITECTURE.md) — Shared context management used by all engines
