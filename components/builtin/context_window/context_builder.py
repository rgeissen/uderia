"""
Context Builder — single entry point for all LLM context assembly.

Bridges the gap between the context window orchestrator (which manages
budget allocation across modules) and the LLM call sites in planner.py,
phase_executor.py, and executor.py (which need specific template variable
formats).

Architecture:
    Orchestrator (handler.py) → AssembledContext → ContextBuilder → PromptContext
                                  (budget-aware)    (format bridge)   (template-ready)

The builder:
  1. Caches the AssembledContext from the orchestrator's per-turn assembly
  2. Maps module content → prompt template variables, applying format
     adapters where the module's output format differs from what the
     template expects
  3. Merges module content (budget-aware) with caller-supplied control
     data (execution-specific variables like goals, errors, phase info)
  4. Returns PromptContext with ready-to-use template_vars dict

Usage:
    builder = ContextBuilder(executor)
    builder.set_assembled_context(assembled)

    ctx = await builder.build("strategic", {
        "workflow_goal": goal,
        "replan_instructions": replan,
        ...
    })
    prompt = WORKFLOW_META_PLANNING_PROMPT.format(**ctx.template_vars)
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any, Dict, List, Optional

from .prompt_context import PromptContext
from .snapshot import ContextWindowSnapshot, ContributionMetric
from .token_estimator import estimate_tokens

logger = logging.getLogger("quart.app")


class ContextBuilder:
    """
    Single entry point for all LLM context assembly.

    Holds a reference to the executor (duck-typed — no import needed)
    and the cached AssembledContext from the orchestrator. Produces
    PromptContext objects for each LLM call type.
    """

    def __init__(self, executor: Any):
        """
        Args:
            executor: TDAExecutor instance. Accessed for live execution
                state (workflow_state, turn_action_history, session_data,
                dependencies). Duck-typed to avoid circular imports.
        """
        self._executor = executor
        self._assembled: Optional[Any] = None  # AssembledContext
        self._assembly_ctx: Optional[Any] = None  # AssemblyContext (for snapshot building)
        self._cwt: Optional[Dict[str, Any]] = None  # Context window type config

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def set_assembled_context(
        self,
        assembled: Any,
        assembly_ctx: Any = None,
        cwt: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Store the latest orchestrator output for reuse across LLM calls.

        Called from executor._run_context_window_assembly() after the
        orchestrator completes its four-pass assembly.

        Args:
            assembled: AssembledContext with module contributions.
            assembly_ctx: The AssemblyContext used for the assembly.
            cwt: Context window type config dict.
        """
        self._assembled = assembled
        self._assembly_ctx = assembly_ctx
        self._cwt = cwt

    @property
    def has_assembled_context(self) -> bool:
        """Whether the builder has cached module content from the orchestrator."""
        return self._assembled is not None

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def build(
        self,
        call_type: str,
        phase_context: Optional[Dict[str, Any]] = None,
    ) -> PromptContext:
        """
        Build context for a specific LLM call type.

        Args:
            call_type: One of 'strategic', 'tactical', 'synthesis', 'utility'.
            phase_context: Execution-specific variables (goals, errors,
                phase info). Merged into template_vars alongside module
                content. Keys here override module-derived values.

        Returns:
            PromptContext with template_vars ready for .format() injection.
        """
        pc = phase_context or {}

        builders = {
            "strategic": self._build_strategic,
            "tactical": self._build_tactical,
            "synthesis": self._build_synthesis,
            "utility": self._build_utility,
        }

        builder_fn = builders.get(call_type)
        if not builder_fn:
            raise ValueError(
                f"Unknown call_type '{call_type}'. "
                f"Expected one of: {list(builders.keys())}"
            )

        return await builder_fn(pc)

    # ------------------------------------------------------------------
    # Strategic planning builder
    # ------------------------------------------------------------------

    async def _build_strategic(self, pc: Dict[str, Any]) -> PromptContext:
        """
        Build context for strategic meta-planning (WORKFLOW_META_PLANNING_PROMPT).

        Content data from modules (budget-aware):
            available_tools         ← tool_definitions module
            available_prompts       ← APP_STATE prompts (not a module)
            turn_action_history     ← workflow_history module → JSON format
            rag_few_shot_examples   ← rag_context module
            knowledge_context       ← knowledge_context module
            component_tools         ← component_instructions module → tool defs

        Config/derived data:
            mcp_system_name         ← global_parameters table
            sql_consolidation_rule  ← APP_CONFIG
            reporting_tool_name     ← execution context

        Control data (from phase_context):
            workflow_goal, original_user_input, execution_depth,
            replan_instructions, active_prompt_context_section,
            explicit_parameters_section, constraints_section,
            kg_schema_directive
        """
        tv: Dict[str, Any] = {}
        content_blocks: Dict[str, str] = {}

        # --- Module content (budget-aware) ---
        tools_content = self._module_content("tool_definitions")
        if tools_content:
            tv["available_tools"] = tools_content
            content_blocks["tool_definitions"] = tools_content
        else:
            tv["available_tools"] = self._fallback_tools()

        tv["available_prompts"] = self._get_prompts_context()

        # Workflow history: module produces markdown, template needs JSON.
        # Use the module's budget awareness but format as JSON.
        history_content = self._format_strategic_history()
        tv["turn_action_history"] = history_content
        content_blocks["workflow_history"] = history_content

        # RAG context: module produces formatted cases with headers.
        rag_content = self._module_content("rag_context")
        tv["rag_few_shot_examples"] = rag_content or ""
        if rag_content:
            content_blocks["rag_context"] = rag_content

        # Knowledge context: module produces formatted docs.
        # Caller may augment with KG enrichment via phase_context.
        knowledge_content = self._module_content("knowledge_context")
        tv["knowledge_context"] = knowledge_content or ""
        if knowledge_content:
            content_blocks["knowledge_context"] = knowledge_content

        # Component tools: need tool definitions, not instructions.
        component_tools = self._build_component_tools_section()
        tv["component_tools"] = component_tools
        if component_tools:
            content_blocks["component_instructions"] = component_tools

        # --- Config/derived data ---
        tv["mcp_system_name"] = self._get_mcp_system_name()
        tv["sql_consolidation_rule"] = self._get_sql_consolidation_rule()
        tv["reporting_tool_name"] = self._get_reporting_tool_name(pc)

        # --- Control data (passed through) ---
        control_keys = [
            "workflow_goal",
            "original_user_input",
            "execution_depth",
            "replan_instructions",
            "active_prompt_context_section",
            "explicit_parameters_section",
            "constraints_section",
            "kg_schema_directive",
        ]
        for key in control_keys:
            if key in pc:
                tv[key] = pc[key]

        # --- Build snapshot ---
        tokens = sum(estimate_tokens(str(v)) for v in tv.values() if isinstance(v, str))
        snapshot = self._build_call_snapshot("strategic", content_blocks, tokens)

        return PromptContext(
            call_type="strategic",
            template_vars=tv,
            content_blocks=content_blocks,
            snapshot=snapshot,
            tokens_used=tokens,
            source="builder" if self.has_assembled_context else "fallback",
        )

    # ------------------------------------------------------------------
    # Tactical planning builder
    # ------------------------------------------------------------------

    async def _build_tactical(self, pc: Dict[str, Any]) -> PromptContext:
        """
        Build context for tactical phase planning (WORKFLOW_TACTICAL_PROMPT).

        Tactical calls differ from strategic:
        - Tools are FILTERED to the current phase's relevant_tools
        - Workflow data is from the CURRENT turn (not previous turns)
        - Data is distilled (large results → metadata)

        Content from modules + current-turn state:
            permitted_tools_with_details   ← tool_definitions (filtered)
            permitted_prompts_with_details ← from phase_context
            all_collected_data             ← distilled workflow_state
            turn_action_history            ← distilled current-turn actions

        Control data (from phase_context):
            workflow_goal, current_phase_goal, strategic_arguments_section,
            last_attempt_info, loop_context_section, context_enrichment_section
        """
        tv: Dict[str, Any] = {}
        content_blocks: Dict[str, str] = {}

        # --- Phase-filtered tools ---
        phase_tools = pc.pop("phase_tools", [])
        tools_content = self._filter_tools_for_phase(phase_tools)
        tv["permitted_tools_with_details"] = tools_content
        content_blocks["tool_definitions"] = tools_content

        # Prompts (passed through from caller)
        tv["permitted_prompts_with_details"] = pc.pop(
            "permitted_prompts_with_details", "None"
        )

        # --- Current-turn data (distilled) ---
        distilled_state = self._distill_workflow_state()
        tv["all_collected_data"] = distilled_state
        content_blocks["plan_hydration"] = distilled_state

        distilled_history = self._distill_turn_history()
        tv["turn_action_history"] = distilled_history
        content_blocks["workflow_history"] = distilled_history

        # --- Control data (passed through) ---
        control_keys = [
            "workflow_goal",
            "current_phase_goal",
            "strategic_arguments_section",
            "last_attempt_info",
            "loop_context_section",
            "context_enrichment_section",
        ]
        for key in control_keys:
            if key in pc:
                tv[key] = pc[key]

        # --- Build snapshot ---
        tokens = sum(estimate_tokens(str(v)) for v in tv.values() if isinstance(v, str))
        snapshot = self._build_call_snapshot("tactical", content_blocks, tokens)

        return PromptContext(
            call_type="tactical",
            template_vars=tv,
            content_blocks=content_blocks,
            snapshot=snapshot,
            tokens_used=tokens,
            source="builder" if self.has_assembled_context else "fallback",
        )

    # ------------------------------------------------------------------
    # Synthesis builder (Ideate / Focus paths)
    # ------------------------------------------------------------------

    async def _build_synthesis(self, pc: Dict[str, Any]) -> PromptContext:
        """
        Build context for conversation/RAG synthesis paths.

        These paths build a user message from concatenated sections
        rather than using template .format(). The builder provides
        content blocks for the caller to assemble.

        Content blocks:
            conversation_history  ← conversation_history module
            knowledge_context     ← knowledge_context module
            document_context      ← document_context module
            component_instructions ← component_instructions module
        """
        content_blocks: Dict[str, str] = {}

        for module_id in [
            "conversation_history",
            "knowledge_context",
            "document_context",
            "component_instructions",
        ]:
            content = self._module_content(module_id)
            if content:
                content_blocks[module_id] = content

        # System prompt from module
        system_prompt = self._module_content("system_prompt")
        if system_prompt:
            content_blocks["system_prompt"] = system_prompt

        # Pass through any caller-provided content
        tv = dict(pc)

        tokens = sum(estimate_tokens(v) for v in content_blocks.values())
        snapshot = self._build_call_snapshot("synthesis", content_blocks, tokens)

        return PromptContext(
            call_type="synthesis",
            template_vars=tv,
            content_blocks=content_blocks,
            snapshot=snapshot,
            tokens_used=tokens,
            source="builder" if self.has_assembled_context else "fallback",
        )

    # ------------------------------------------------------------------
    # Utility builder (minimal calls)
    # ------------------------------------------------------------------

    async def _build_utility(self, pc: Dict[str, Any]) -> PromptContext:
        """
        Build context for utility LLM calls (classification, enrichment).

        These calls need minimal context — just pass through whatever
        the caller provides. No module content needed.
        """
        tv = dict(pc)
        tokens = sum(estimate_tokens(str(v)) for v in tv.values() if isinstance(v, str))

        return PromptContext(
            call_type="utility",
            template_vars=tv,
            content_blocks={},
            snapshot=None,
            tokens_used=tokens,
            source="passthrough",
        )

    # ==================================================================
    # Module content access
    # ==================================================================

    def _module_content(self, module_id: str) -> str:
        """
        Get a module's content from the cached AssembledContext.

        Returns empty string if no assembled context or module didn't
        contribute.
        """
        if self._assembled is not None:
            return self._assembled.get_content(module_id) or ""
        return ""

    def _module_metadata(self, module_id: str) -> Dict[str, Any]:
        """Get a module's metadata from the cached assembly."""
        if self._assembled is not None:
            contrib = self._assembled.contributions.get(module_id)
            if contrib:
                return contrib.metadata
        return {}

    def _module_tokens(self, module_id: str) -> int:
        """Get a module's token allocation from the cached assembly."""
        if self._assembled is not None:
            contrib = self._assembled.contributions.get(module_id)
            if contrib:
                return contrib.tokens_used
        return 0

    # ==================================================================
    # Format adapters — bridge module content → template variables
    # ==================================================================

    def _fallback_tools(self) -> str:
        """Fallback: get tools from APP_STATE when module content unavailable."""
        try:
            state = self._executor.dependencies.get("STATE", {})
            if isinstance(state, dict):
                return state.get("tools_context", "--- No Tools Available ---")
            return getattr(state, "get", lambda k, d: d)("tools_context", "--- No Tools Available ---")
        except Exception:
            return "--- No Tools Available ---"

    def _get_prompts_context(self) -> str:
        """Get available prompts from APP_STATE (not a module)."""
        try:
            state = self._executor.dependencies.get("STATE", {})
            if isinstance(state, dict):
                return state.get("prompts_context", "--- No Prompts Available ---")
            return getattr(state, "get", lambda k, d: d)("prompts_context", "--- No Prompts Available ---")
        except Exception:
            return "--- No Prompts Available ---"

    def _format_strategic_history(self) -> str:
        """
        Format workflow history as JSON for strategic planning.

        The workflow_history MODULE produces a compact markdown summary
        (budget-aware). But WORKFLOW_META_PLANNING_PROMPT expects rich
        JSON with turn metadata and SQL extraction.

        This method reads the same raw session data, applies the same
        scrubbing/metadata logic as planner._create_summary_from_history(),
        but respects the module's budget allocation.
        """
        # Try to get raw session data from the assembly context
        session_data = {}
        if self._assembly_ctx is not None:
            session_data = getattr(self._assembly_ctx, "session_data", {})
        if not session_data:
            # Fall back to reading from executor's last known session
            try:
                session_data = getattr(self._executor, "_last_session_data", {}) or {}
            except Exception:
                pass

        history = session_data.get("workflow_history", {})
        if not history or not isinstance(history, dict):
            return json.dumps({"workflow_history": []}, indent=2)

        full_wh = history.get("workflow_history", [])
        if not isinstance(full_wh, list):
            return json.dumps({"workflow_history": []}, indent=2)

        # Filter for valid turns
        valid_turns = [
            t for t in full_wh
            if isinstance(t, dict) and t.get("isValid", True) is not False
        ]

        # Scrub and enrich
        scrubbed = []
        ui_only_fields = [
            "genie_events", "slave_sessions", "provider", "model", "status",
            "conversation_agent_events", "knowledge_events", "system_events",
            "knowledge_chunks_ui", "session_input_tokens", "session_output_tokens",
            "final_summary_html", "tts_payload", "raw_llm_plan",
        ]

        for idx, turn in enumerate(valid_turns):
            new_turn = copy.deepcopy(turn)

            # Remove UI-only fields
            for f in ui_only_fields:
                new_turn.pop(f, None)

            # Remove heavy chunks from knowledge retrieval
            kre = new_turn.get("knowledge_retrieval_event")
            if isinstance(kre, dict):
                kre.pop("chunks", None)

            # Scrub TDA_SystemLog from execution trace
            trace = new_turn.get("execution_trace", [])
            if isinstance(trace, list):
                new_turn["execution_trace"] = [
                    e for e in trace
                    if isinstance(e, dict)
                    and (e.get("action", {}) or {}).get("tool_name") != "TDA_SystemLog"
                ]

            # Add turn metadata
            new_turn["turn_metadata"] = {
                "turn_number": new_turn.get("turn", idx + 1),
                "profile_tag": new_turn.get("profile_tag", "unknown"),
                "profile_type": new_turn.get("profile_type", "unknown"),
                "is_most_recent": idx == len(valid_turns) - 1,
            }

            # Extract SQL from final_summary_text
            summary_text = new_turn.get("final_summary_text", "")
            if summary_text:
                sql_matches = _extract_sql_from_text(summary_text)
                if sql_matches:
                    new_turn["turn_metadata"]["sql_mentioned_in_conversation"] = sql_matches

            scrubbed.append(new_turn)

        result = {
            "total_turns": len(scrubbed),
            "most_recent_turn_number": (
                scrubbed[-1].get("turn", len(scrubbed)) if scrubbed else 0
            ),
            "workflow_history": scrubbed,
        }

        # Respect budget from module allocation
        raw_json = json.dumps(result, indent=2)
        budget_tokens = self._module_tokens("workflow_history")
        if budget_tokens > 0:
            from .token_estimator import tokens_to_chars
            char_limit = tokens_to_chars(budget_tokens)
            if len(raw_json) > char_limit and scrubbed:
                # Truncate oldest turns to fit budget
                while len(scrubbed) > 1 and len(raw_json) > char_limit:
                    scrubbed.pop(0)
                    result["total_turns"] = len(scrubbed)
                    result["workflow_history"] = scrubbed
                    raw_json = json.dumps(result, indent=2)

        return raw_json

    def _build_component_tools_section(self) -> str:
        """
        Build the component tools section for strategic planning.

        The component_instructions MODULE produces LLM usage instructions.
        But the strategic template's {component_tools} variable expects
        tool definitions (name, description, arguments).

        This method gets tool definitions from ComponentManager directly,
        which is what planner.py currently does.
        """
        try:
            from trusted_data_agent.components.manager import get_component_manager
            cm = get_component_manager()
            if cm is None:
                return ""

            tool_defs = cm.get_tool_definitions()
            if not tool_defs:
                return ""

            lines = ["--- Available Component Tools ---"]
            for tool in tool_defs:
                name = tool.get("name", "unknown")
                desc = tool.get("description", "")
                lines.append(f"- `{name}` (tool): {desc}")

                params = tool.get("inputSchema", {}).get("properties", {})
                required = tool.get("inputSchema", {}).get("required", [])
                if params:
                    lines.append("  - Arguments:")
                    for param_name, param_info in params.items():
                        ptype = param_info.get("type", "string")
                        req = "required" if param_name in required else "optional"
                        pdesc = param_info.get("description", "")
                        lines.append(f"    - `{param_name}` ({ptype}, {req}): {pdesc}")

            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Could not build component tools section: {e}")
            return ""

    def _filter_tools_for_phase(self, relevant_tool_names: List[str]) -> str:
        """
        Filter tools to only those relevant for the current phase.

        Uses the full tool definitions from the executor's dependencies
        and filters to the tools listed in the strategic plan's
        relevant_tools for this phase.
        """
        if not relevant_tool_names:
            return "No specific tools available for this phase."

        try:
            state = self._executor.dependencies.get("STATE", {})
            if isinstance(state, dict):
                structured_tools = state.get("structured_tools", {})
            else:
                structured_tools = getattr(state, "get", lambda k, d: d)("structured_tools", {})

            lines = []
            for tool_name in relevant_tool_names:
                tool_info = structured_tools.get(tool_name)
                if tool_info:
                    desc = tool_info.get("description", "No description")
                    lines.append(f"- Tool: `{tool_name}`")
                    lines.append(f"  - Description: {desc}")

                    schema = tool_info.get("inputSchema", {})
                    props = schema.get("properties", {})
                    required = schema.get("required", [])
                    if props:
                        lines.append("  - Arguments:")
                        for pname, pinfo in props.items():
                            ptype = pinfo.get("type", "string")
                            req = "required" if pname in required else "optional"
                            pdesc = pinfo.get("description", "")
                            lines.append(f"    - `{pname}` ({ptype}, {req}): {pdesc}")
                else:
                    lines.append(f"- Tool: `{tool_name}` (details not available)")

            return "\n".join(lines) if lines else "No matching tools found."
        except Exception as e:
            logger.debug(f"Could not filter tools for phase: {e}")
            return "Tool details unavailable."

    def _distill_workflow_state(self) -> str:
        """
        Distill current-turn workflow state for tactical planning.

        Uses the executor's _distill_data_for_llm_context() method
        to replace large result sets with metadata summaries.
        """
        try:
            workflow_state = getattr(self._executor, "workflow_state", {})
            if not workflow_state:
                return json.dumps({}, indent=2)

            distilled = self._executor._distill_data_for_llm_context(
                copy.deepcopy(workflow_state)
            )
            return json.dumps(distilled, indent=2)
        except Exception as e:
            logger.debug(f"Could not distill workflow state: {e}")
            return json.dumps({}, indent=2)

    def _distill_turn_history(self) -> str:
        """
        Distill current-turn action history for tactical planning.

        This is the CURRENT turn's action history (what happened in
        previous phases of this turn), not the cross-turn workflow history.
        """
        try:
            history = getattr(self._executor, "turn_action_history", [])
            if not history:
                return json.dumps([], indent=2)

            distilled = self._executor._distill_data_for_llm_context(
                copy.deepcopy(history)
            )
            return json.dumps(distilled, indent=2)
        except Exception as e:
            logger.debug(f"Could not distill turn history: {e}")
            return json.dumps([], indent=2)

    # ==================================================================
    # Config / derived data helpers
    # ==================================================================

    def _get_mcp_system_name(self) -> str:
        """Get the MCP system name from global parameters."""
        try:
            from trusted_data_agent.core.config_manager import get_config_manager
            config_manager = get_config_manager()
            user_uuid = getattr(self._executor, "user_uuid", "")
            if user_uuid:
                params = config_manager.get_global_parameters(user_uuid)
                for p in params:
                    if p.get("parameter_name") == "mcp_system_name":
                        return p.get("parameter_value", "Database System")
            return "Database System"
        except Exception:
            return "Database System"

    def _get_sql_consolidation_rule(self) -> str:
        """Build SQL consolidation rule from APP_CONFIG."""
        try:
            from trusted_data_agent.core.config import APP_CONFIG
            prompts = getattr(APP_CONFIG, "SQL_OPTIMIZATION_PROMPTS", [])
            tools = getattr(APP_CONFIG, "SQL_OPTIMIZATION_TOOLS", [])
            if prompts or tools:
                return (
                    "**CRITICAL STRATEGY (SQL Consolidation):** Before creating "
                    "a multi-step plan that queries the same database multiple "
                    "times, consider if a single consolidated SQL query could "
                    "achieve the same result more efficiently."
                )
            return ""
        except Exception:
            return ""

    def _get_reporting_tool_name(self, pc: Dict[str, Any]) -> str:
        """Determine the appropriate reporting tool name."""
        source = pc.get("source") or getattr(self._executor, "source", "text")
        if source == "prompt_library":
            return "TDA_ComplexPromptReport"
        return "TDA_FinalReport"

    # ==================================================================
    # Snapshot builder
    # ==================================================================

    def _build_call_snapshot(
        self,
        call_type: str,
        content_blocks: Dict[str, str],
        total_tokens: int,
    ) -> Optional[ContextWindowSnapshot]:
        """
        Build a per-call snapshot for observability.

        Uses the cached assembly's snapshot as a template, but adjusts
        the token counts to reflect what this specific call consumed.
        """
        if self._assembled is None or self._assembled.snapshot is None:
            return None

        base = self._assembled.snapshot
        available = base.available_budget or 1

        # Build contribution metrics for this call's content
        contributions = []
        for module_id, content in content_blocks.items():
            tokens = estimate_tokens(content) if content else 0
            if tokens > 0:
                contributions.append(ContributionMetric(
                    module_id=module_id,
                    label=module_id.replace("_", " ").title(),
                    category="content",
                    tokens_allocated=tokens,
                    tokens_used=tokens,
                    utilization_pct=100.0,
                    is_active=True,
                ))

        return ContextWindowSnapshot(
            context_window_type_id=base.context_window_type_id,
            context_window_type_name=f"{base.context_window_type_name} ({call_type})",
            model_context_limit=base.model_context_limit,
            output_reserve=base.output_reserve,
            available_budget=available,
            total_used=total_tokens,
            utilization_pct=(total_tokens / available * 100) if available > 0 else 0,
            contributions=contributions,
            profile_type=base.profile_type,
            active_module_count=len(contributions),
            session_id=base.session_id,
            turn_number=base.turn_number,
        )


# ======================================================================
# Utility functions
# ======================================================================

def _extract_sql_from_text(text: str) -> List[str]:
    """Extract SQL statements from text using multiple regex patterns."""
    sql_matches = []

    # Pattern 1: ```sql ... ```
    sql_matches.extend(
        re.findall(r"```sql\n(.*?)\n```", text, re.DOTALL | re.IGNORECASE)
    )

    # Pattern 2: ``` SELECT ... ```
    if not sql_matches:
        sql_matches.extend(
            re.findall(r"```\n(SELECT.*?)\n```", text, re.DOTALL | re.IGNORECASE)
        )

    # Pattern 3: Plain SELECT statement
    if not sql_matches:
        sql_matches.extend(
            re.findall(
                r"(SELECT\s+.+?FROM\s+.+?(?:WHERE\s+.+?)?(?:GROUP\s+BY\s+.+?)?(?:ORDER\s+BY\s+.+?)?;)",
                text,
                re.DOTALL | re.IGNORECASE,
            )
        )

    return sql_matches
