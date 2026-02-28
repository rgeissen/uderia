"""
Context Window Handler — the budget orchestrator.

This is the core system component that manages the most scarce resource
in the platform: the LLM context window. It reads a profile's bound
Context Window Type, resolves which modules are active, allocates budget
using the type's allocation strategy, and produces a ContextWindowSnapshot
for observability.

Four-Pass Assembly:
  Pass 1: RESOLVE ACTIVE MODULES — skip deactivated and inapplicable modules
  Pass 2: ALLOCATE AND ASSEMBLE — allocate budget and call each module
  Pass 3: APPLY DYNAMIC ADJUSTMENTS — runtime condition-based reallocation
  Pass 4: CONDENSE IF OVER BUDGET — condense lowest-priority modules first
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from trusted_data_agent.components.base import SystemHandler

from .base import AssemblyContext, ContextModule, Contribution
from .module_registry import ContextModuleRegistry, get_module_registry
from .snapshot import (
    CondensationEvent,
    ContributionMetric,
    ContextWindowSnapshot,
)
from .token_estimator import estimate_tokens

logger = logging.getLogger("quart.app")


# ---------------------------------------------------------------------------
# Active module — resolved module with its type-specific configuration
# ---------------------------------------------------------------------------

@dataclass
class ActiveModule:
    """A module resolved for a specific context window type + profile."""

    module_id: str
    handler: ContextModule
    label: str
    category: str
    priority: int
    target_pct: float
    min_pct: float
    max_pct: float
    condensable: bool

    # Computed during allocation
    allocated_tokens: int = 0
    contribution: Optional[Contribution] = None


# ---------------------------------------------------------------------------
# Assembled context — the output of a full assembly operation
# ---------------------------------------------------------------------------

@dataclass
class AssembledContext:
    """
    The fully assembled context window, ready to be sent to the LLM.

    Contains all module contributions in priority order, along with
    the snapshot for observability.
    """

    contributions: Dict[str, Contribution] = field(default_factory=dict)
    """Module contributions keyed by module_id, in assembly order."""

    snapshot: Optional[ContextWindowSnapshot] = None
    """Full metrics snapshot for SSE emission."""

    total_tokens: int = 0
    """Total tokens consumed across all contributions."""

    def get_content(self, module_id: str) -> str:
        """Get a specific module's contribution content."""
        contrib = self.contributions.get(module_id)
        return contrib.content if contrib else ""

    def get_all_content(self) -> str:
        """Get all contributions concatenated (for debugging)."""
        return "\n\n".join(
            c.content for c in self.contributions.values() if c.content
        )


# ---------------------------------------------------------------------------
# Context Window Handler — the orchestrator
# ---------------------------------------------------------------------------

class ContextWindowHandler(SystemHandler):
    """
    Orchestrates context budget allocation across pluggable modules.

    Reads a Context Window Type configuration, resolves active modules
    from the registry, allocates budget using the type's strategy, and
    produces an AssembledContext with full observability metrics.
    """

    @property
    def component_id(self) -> str:
        return "context_window"

    async def get_metrics(self) -> Dict[str, Any]:
        """Return metrics from the last assembly operation."""
        if self._last_snapshot:
            return self._last_snapshot.to_sse_event()
        return {"status": "no_assembly_yet"}

    def __init__(self):
        self._last_snapshot: Optional[ContextWindowSnapshot] = None
        self._registry: Optional[ContextModuleRegistry] = None

    @property
    def registry(self) -> ContextModuleRegistry:
        """Lazy-load the module registry."""
        if self._registry is None:
            self._registry = get_module_registry()
        return self._registry

    # -------------------------------------------------------------------
    # Main assembly entry point
    # -------------------------------------------------------------------

    async def assemble(
        self,
        context_window_type: Dict[str, Any],
        ctx: AssemblyContext,
    ) -> AssembledContext:
        """
        Assemble the full context window using the four-pass algorithm.

        Args:
            context_window_type: The context window type config dict
                (from tda_config.json context_window_types).
            ctx: Assembly context with session state and dependencies.

        Returns:
            AssembledContext with all contributions and a snapshot.
        """
        type_id = context_window_type.get("id", "unknown")
        type_name = context_window_type.get("name", "Unknown")
        output_reserve_pct = context_window_type.get("output_reserve_pct", 12)

        # Calculate output reserve
        output_reserve = int(ctx.model_context_limit * output_reserve_pct / 100)
        available_budget = ctx.model_context_limit - output_reserve

        logger.info(
            f"Context window assembly: type={type_name}, "
            f"budget={available_budget:,} tokens "
            f"(limit={ctx.model_context_limit:,}, reserve={output_reserve:,})"
        )

        # --- Pass 1: Resolve active modules ---
        active_modules, skipped_modules = self._resolve_active_modules(
            context_window_type, ctx
        )

        if not active_modules:
            logger.warning("No active modules resolved — returning empty context")
            snapshot = self._build_snapshot(
                type_id, type_name, ctx, available_budget,
                output_reserve, [], [], [], skipped_modules,
            )
            self._last_snapshot = snapshot
            return AssembledContext(snapshot=snapshot)

        # Redistribute budget from skipped modules
        self._redistribute_budget(active_modules)

        # --- Pass 2: Allocate and assemble ---
        contributions = await self._allocate_and_assemble(
            active_modules, available_budget, ctx
        )

        # --- Pass 3: Apply dynamic adjustments ---
        adjustments_fired = self._apply_dynamic_adjustments(
            context_window_type, active_modules, ctx
        )

        # --- Pass 4: Condense if over budget ---
        total_used = sum(c.tokens_used for c in contributions.values())
        condensations = []

        if total_used > available_budget:
            condensation_order = context_window_type.get("condensation_order", [])
            contributions, condensations = await self._condense(
                active_modules, contributions, condensation_order,
                total_used, available_budget, ctx,
            )
            total_used = sum(c.tokens_used for c in contributions.values())

        # Build result
        utilization_pct = (total_used / available_budget * 100) if available_budget > 0 else 0

        # Build contribution metrics
        contribution_metrics = []
        for am in active_modules:
            contrib = contributions.get(am.module_id)
            if contrib:
                alloc = am.allocated_tokens
                used = contrib.tokens_used
                contribution_metrics.append(ContributionMetric(
                    module_id=am.module_id,
                    label=am.label,
                    category=am.category,
                    tokens_allocated=alloc,
                    tokens_used=used,
                    utilization_pct=(used / alloc * 100) if alloc > 0 else 0,
                    was_condensed=any(
                        e.module_id == am.module_id for e in condensations
                    ),
                    is_active=True,
                    metadata=contrib.metadata,
                ))

        snapshot = self._build_snapshot(
            type_id, type_name, ctx, available_budget, output_reserve,
            contribution_metrics, condensations, adjustments_fired,
            skipped_modules,
        )
        self._last_snapshot = snapshot

        logger.info(snapshot.to_summary_text())

        return AssembledContext(
            contributions=contributions,
            snapshot=snapshot,
            total_tokens=total_used,
        )

    # -------------------------------------------------------------------
    # Pass 1: Resolve active modules
    # -------------------------------------------------------------------

    def _resolve_active_modules(
        self,
        context_window_type: Dict[str, Any],
        ctx: AssemblyContext,
    ) -> Tuple[List[ActiveModule], List[str]]:
        """
        Determine which modules participate in this assembly.

        A module is skipped if:
        1. It's set to active=false in the context window type
        2. It doesn't apply to the current profile type
        3. It's not found in the registry

        Returns:
            (active_modules sorted by priority desc, skipped_module_ids)
        """
        type_modules = context_window_type.get("modules", {})
        active = []
        skipped = []

        for module_id, config in type_modules.items():
            # Check activation
            if not config.get("active", True):
                skipped.append(module_id)
                logger.debug(f"Module '{module_id}' deactivated in type config")
                continue

            # Check registry
            defn = self.registry.get_module(module_id)
            if defn is None or defn.handler is None:
                skipped.append(module_id)
                logger.debug(f"Module '{module_id}' not found in registry")
                continue

            # Check profile applicability
            if not defn.handler.applies_to(ctx.profile_type):
                skipped.append(module_id)
                logger.debug(
                    f"Module '{module_id}' not applicable to "
                    f"profile_type={ctx.profile_type}"
                )
                continue

            active.append(ActiveModule(
                module_id=module_id,
                handler=defn.handler,
                label=defn.display_name,
                category=defn.category,
                priority=config.get("priority", defn.default_priority),
                target_pct=config.get("target_pct", defn.default_target_pct),
                min_pct=config.get("min_pct", defn.default_min_pct),
                max_pct=config.get("max_pct", defn.default_max_pct),
                condensable=defn.condensable,
            ))

        # Sort by priority (highest first)
        active.sort(key=lambda m: m.priority, reverse=True)

        logger.debug(
            f"Resolved {len(active)} active modules, "
            f"{len(skipped)} skipped: {skipped}"
        )
        return active, skipped

    # -------------------------------------------------------------------
    # Budget redistribution
    # -------------------------------------------------------------------

    def _redistribute_budget(self, active_modules: List[ActiveModule]) -> None:
        """
        Redistribute budget from skipped modules proportionally to active ones.

        The total target_pct of active modules is normalized to sum to
        (100 - output_reserve_pct). This ensures all available budget
        is distributed regardless of how many modules are active.
        """
        total_target = sum(m.target_pct for m in active_modules)
        if total_target <= 0:
            return

        # Normalize: each module's share = its target / total_target
        # This redistributes skipped budget proportionally
        for m in active_modules:
            m.target_pct = (m.target_pct / total_target) * 100

    # -------------------------------------------------------------------
    # Pass 2: Allocate and assemble
    # -------------------------------------------------------------------

    async def _allocate_and_assemble(
        self,
        active_modules: List[ActiveModule],
        available_budget: int,
        ctx: AssemblyContext,
    ) -> Dict[str, Contribution]:
        """
        Allocate budget to each module and call contribute().

        Modules are processed in priority order (highest first).
        Each module receives its allocated budget as a hard cap.
        """
        contributions: Dict[str, Contribution] = {}

        for am in active_modules:
            # Calculate token allocation
            allocation = int(available_budget * am.target_pct / 100)
            min_tokens = int(available_budget * am.min_pct / 100)
            max_tokens = int(available_budget * am.max_pct / 100)

            # Clamp to min/max
            allocation = max(min_tokens, min(allocation, max_tokens))
            am.allocated_tokens = allocation

            # Provide previous contributions for cross-module awareness
            ctx.previous_contributions = {
                mid: c for mid, c in contributions.items()
            }

            try:
                contribution = await am.handler.contribute(allocation, ctx)
                contributions[am.module_id] = contribution
                am.contribution = contribution

                logger.debug(
                    f"Module '{am.module_id}': allocated={allocation}, "
                    f"used={contribution.tokens_used}"
                )
            except Exception as e:
                logger.error(
                    f"Module '{am.module_id}' failed to contribute: {e}",
                    exc_info=True,
                )
                # Insert empty contribution so assembly can continue
                contributions[am.module_id] = Contribution(
                    content="",
                    tokens_used=0,
                    metadata={"error": str(e)},
                )

        return contributions

    # -------------------------------------------------------------------
    # Pass 3: Dynamic adjustments
    # -------------------------------------------------------------------

    def _apply_dynamic_adjustments(
        self,
        context_window_type: Dict[str, Any],
        active_modules: List[ActiveModule],
        ctx: AssemblyContext,
    ) -> List[str]:
        """
        Evaluate and apply dynamic adjustment rules.

        Rules are defined in the context window type's dynamic_adjustments
        array. Each rule has a condition and an action.

        Returns list of adjustment names that fired.
        """
        adjustments = context_window_type.get("dynamic_adjustments", [])
        fired = []

        for rule in adjustments:
            condition = rule.get("condition", "")
            action = rule.get("action", {})

            if self._evaluate_condition(condition, ctx, active_modules):
                self._apply_action(action, active_modules)
                fired.append(condition)
                logger.debug(f"Dynamic adjustment fired: {condition}")

        return fired

    def _evaluate_condition(
        self,
        condition: str,
        ctx: AssemblyContext,
        active_modules: List[ActiveModule],
    ) -> bool:
        """Evaluate a dynamic adjustment condition."""
        if condition == "first_turn":
            return ctx.is_first_turn

        if condition == "no_documents_attached":
            # Check if any documents are attached to the session
            attachments = ctx.session_data.get("attachments", [])
            return len(attachments) == 0

        if condition == "long_conversation":
            return ctx.turn_number > 10

        if condition == "high_confidence_rag":
            # Check if RAG module produced high-confidence results
            rag_contrib = ctx.previous_contributions.get("rag_context")
            if rag_contrib and rag_contrib.metadata.get("confidence", 0) > 0.85:
                return True
            return False

        return False

    def _apply_action(
        self,
        action: Dict[str, Any],
        active_modules: List[ActiveModule],
    ) -> None:
        """Apply a dynamic adjustment action to active modules."""
        modules_by_id = {m.module_id: m for m in active_modules}

        if "reduce" in action:
            target_id = action["reduce"]
            by_pct = action.get("by_pct", 50)
            if target_id in modules_by_id:
                m = modules_by_id[target_id]
                m.target_pct *= (1 - by_pct / 100)

        elif "transfer" in action:
            from_id = action["transfer"]
            to_id = action.get("to")
            if from_id in modules_by_id and to_id in modules_by_id:
                from_m = modules_by_id[from_id]
                to_m = modules_by_id[to_id]
                to_m.target_pct += from_m.target_pct
                from_m.target_pct = 0

        elif "force_full" in action:
            target_id = action["force_full"]
            if target_id in modules_by_id:
                m = modules_by_id[target_id]
                m.target_pct = m.max_pct

    # -------------------------------------------------------------------
    # Pass 4: Condensation
    # -------------------------------------------------------------------

    async def _condense(
        self,
        active_modules: List[ActiveModule],
        contributions: Dict[str, Contribution],
        condensation_order: List[str],
        total_used: int,
        available_budget: int,
        ctx: AssemblyContext,
    ) -> Tuple[Dict[str, Contribution], List[CondensationEvent]]:
        """
        Condense contributions to fit within budget.

        Processes modules in condensation_order (lowest priority first).
        Stops as soon as total usage is within budget.
        """
        events = []
        modules_by_id = {m.module_id: m for m in active_modules}

        for module_id in condensation_order:
            if total_used <= available_budget:
                break

            am = modules_by_id.get(module_id)
            if am is None or not am.condensable:
                continue

            contrib = contributions.get(module_id)
            if contrib is None or contrib.tokens_used == 0:
                continue

            overage = total_used - available_budget
            target_tokens = max(0, contrib.tokens_used - overage)

            try:
                condensed = await am.handler.condense(
                    contrib.content, target_tokens, ctx
                )

                tokens_before = contrib.tokens_used
                tokens_after = condensed.tokens_used

                if tokens_after < tokens_before:
                    contributions[module_id] = condensed
                    total_used -= (tokens_before - tokens_after)

                    reduction_pct = (
                        (tokens_before - tokens_after) / tokens_before * 100
                        if tokens_before > 0 else 0
                    )
                    events.append(CondensationEvent(
                        module_id=module_id,
                        tokens_before=tokens_before,
                        tokens_after=tokens_after,
                        reduction_pct=reduction_pct,
                        strategy=condensed.metadata.get("strategy", "unknown"),
                    ))
                    logger.debug(
                        f"Condensed '{module_id}': {tokens_before} → {tokens_after} "
                        f"({reduction_pct:.0f}% reduction)"
                    )

            except Exception as e:
                logger.error(
                    f"Condensation failed for '{module_id}': {e}",
                    exc_info=True,
                )

        return contributions, events

    # -------------------------------------------------------------------
    # Snapshot builder
    # -------------------------------------------------------------------

    def _build_snapshot(
        self,
        type_id: str,
        type_name: str,
        ctx: AssemblyContext,
        available_budget: int,
        output_reserve: int,
        contributions: List[ContributionMetric],
        condensations: List[CondensationEvent],
        adjustments_fired: List[str],
        skipped_modules: List[str],
    ) -> ContextWindowSnapshot:
        """Build a complete snapshot for observability."""
        total_used = sum(c.tokens_used for c in contributions)
        utilization_pct = (total_used / available_budget * 100) if available_budget > 0 else 0

        return ContextWindowSnapshot(
            context_window_type_id=type_id,
            context_window_type_name=type_name,
            model_context_limit=ctx.model_context_limit,
            output_reserve=output_reserve,
            available_budget=available_budget,
            total_used=total_used,
            utilization_pct=utilization_pct,
            contributions=contributions,
            condensations=condensations,
            dynamic_adjustments_fired=adjustments_fired,
            profile_type=ctx.profile_type,
            skipped_modules=skipped_modules,
            active_module_count=len(contributions),
            session_id=ctx.session_id,
            turn_number=ctx.turn_number,
        )
