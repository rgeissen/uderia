"""
Knowledge Graph Component Handler.

Processes TDA_KnowledgeGraph tool calls for graph queries, visualization,
and entity management. Also provides context enrichment for the planner
by extracting relevant subgraph context based on the user's query.

This is the guardrail mechanism: by injecting known relationships into the
planner prompt, the LLM makes better decisions about which tools to use
and how to construct queries.
"""

import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from trusted_data_agent.components.base import (
    BaseComponentHandler,
    ComponentRenderPayload,
    RenderTarget,
)

logger = logging.getLogger("quart.app")

# Entity type → color mapping for D3 visualization
ENTITY_TYPE_COLORS = {
    "database": "#3b82f6",         # blue
    "table": "#22c55e",            # green
    "column": "#a3e635",           # lime
    "foreign_key": "#f59e0b",      # amber
    "business_concept": "#8b5cf6", # violet
    "taxonomy": "#ec4899",         # pink
    "metric": "#06b6d4",           # cyan
    "domain": "#f97316",           # orange
}


class KnowledgeGraphHandler(BaseComponentHandler):
    """
    Knowledge Graph component handler.

    Dual purpose:
    1. Tool handler: processes TDA_KnowledgeGraph calls (query, visualize, add_entity, etc.)
    2. Context enrichment: provides get_context_enrichment() for planner guardrail injection
    """

    @property
    def component_id(self) -> str:
        return "knowledge_graph"

    @property
    def tool_name(self) -> str:
        return "TDA_KnowledgeGraph"

    @property
    def is_deterministic(self) -> bool:
        return True

    def validate_arguments(self, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate that required arguments are present for the given action."""
        action = arguments.get("action")
        if not action:
            return False, "Missing required argument: 'action'"

        valid_actions = {"query", "visualize", "add_entity", "add_relationship", "get_context"}
        if action not in valid_actions:
            return False, f"Invalid action '{action}'. Must be one of: {valid_actions}"

        if action == "add_entity":
            if not arguments.get("entity_name"):
                return False, "add_entity requires 'entity_name'"
            if not arguments.get("entity_type"):
                return False, "add_entity requires 'entity_type'"

        if action == "add_relationship":
            if not arguments.get("entity_name"):
                return False, "add_relationship requires 'entity_name' (source)"
            if not arguments.get("target_entity"):
                return False, "add_relationship requires 'target_entity'"
            if not arguments.get("relationship_type"):
                return False, "add_relationship requires 'relationship_type'"

        return True, ""

    async def process(
        self,
        arguments: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> ComponentRenderPayload:
        """Route to action-specific handlers."""
        action = arguments.get("action", "query")

        if action == "query":
            return await self._handle_query(arguments, context)
        elif action == "visualize":
            return await self._handle_visualize(arguments, context)
        elif action == "add_entity":
            return await self._handle_add_entity(arguments, context)
        elif action == "add_relationship":
            return await self._handle_add_relationship(arguments, context)
        elif action == "get_context":
            return await self._handle_get_context(arguments, context)
        else:
            return ComponentRenderPayload(
                component_id=self.component_id,
                render_target=RenderTarget.INLINE,
                html=f"<p class='text-red-400'>Unknown action: {action}</p>",
                metadata={"tool_name": self.tool_name, "action": action, "error": True},
            )

    # -------------------------------------------------------------------
    # Context Enrichment (guardrail)
    # -------------------------------------------------------------------

    async def get_context_enrichment(
        self,
        query: str,
        profile_id: str,
        user_uuid: str,
    ) -> str:
        """
        Context enrichment for the planner — the core guardrail mechanism.

        Extracts a relevant subgraph based on keyword matching of the query
        against entity names, descriptions, and business meanings. Returns
        formatted text suitable for prompt injection.

        Called by ComponentManager.get_context_enrichment() before strategic planning.
        """
        store = self._get_store_direct(profile_id, user_uuid)

        # 1. Extract candidate entity names from query via keyword matching
        entities = self._search_entities_for_query(store, query)
        if not entities:
            return ""

        # 2. Expand to connected subgraph (depth=2, max_nodes=30)
        entity_ids = [e["id"] for e in entities]
        subgraph = store.extract_subgraph(entity_ids, depth=2, max_nodes=30)

        if not subgraph["entities"]:
            return ""

        # 3. Format as structured text for prompt injection
        return self._format_subgraph_for_prompt(subgraph)

    def _search_entities_for_query(self, store: Any, query: str) -> List[Dict]:
        """
        Search for entities relevant to the user's query.
        Uses both direct substring search and tokenized keyword matching.
        """
        # Direct search on the full query
        results = store.search_entities(query, limit=10)

        # Also search individual words (for multi-word queries like "show orders by product")
        words = re.findall(r'\b[a-zA-Z_]{3,}\b', query.lower())
        seen_ids = {e["id"] for e in results}

        for word in words:
            # Skip common stop words
            if word in {"the", "show", "get", "list", "find", "all", "from", "with",
                        "for", "and", "that", "this", "what", "how", "many", "much",
                        "are", "was", "were", "has", "have", "been", "can", "will",
                        "please", "help", "give", "tell", "about", "into", "each"}:
                continue

            word_results = store.search_entities(word, limit=5)
            for ent in word_results:
                if ent["id"] not in seen_ids:
                    results.append(ent)
                    seen_ids.add(ent["id"])

            if len(results) >= 15:
                break

        return results[:15]

    def _format_subgraph_for_prompt(self, subgraph: Dict[str, List]) -> str:
        """Format subgraph as structured text for LLM context injection."""
        if not subgraph["entities"]:
            return ""

        lines = [
            "--- KNOWLEDGE GRAPH CONTEXT ---",
            "The following known entities and relationships may inform your planning:",
        ]

        # Group entities by type
        by_type: Dict[str, List] = {}
        for entity in subgraph["entities"]:
            etype = entity["entity_type"]
            if etype not in by_type:
                by_type[etype] = []
            by_type[etype].append(entity)

        for etype, entities in sorted(by_type.items()):
            lines.append(f"\n{etype.upper()} ENTITIES:")
            for e in entities:
                props = e.get("properties", {})
                desc = props.get("description", "")
                biz = props.get("business_meaning", "")
                dtype = props.get("data_type", "")

                line = f"  - {e['name']}"
                parts = []
                if desc:
                    parts.append(desc)
                if dtype:
                    parts.append(f"type: {dtype}")
                if biz:
                    parts.append(f"business: {biz}")
                if parts:
                    line += f" ({'; '.join(parts)})"
                lines.append(line)

        if subgraph["relationships"]:
            lines.append("\nKNOWN RELATIONSHIPS:")
            for rel in subgraph["relationships"]:
                meta_desc = rel.get("metadata", {}).get("description", "")
                card = f" [{rel['cardinality']}]" if rel.get("cardinality") else ""
                desc_part = f" — {meta_desc}" if meta_desc else ""
                lines.append(
                    f"  - {rel['source_name']} --[{rel['relationship_type']}{card}]--> {rel['target_name']}{desc_part}"
                )

        lines.append("--- END KNOWLEDGE GRAPH CONTEXT ---")
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # Action handlers
    # -------------------------------------------------------------------

    async def _handle_query(self, arguments: Dict, context: Optional[Dict]) -> ComponentRenderPayload:
        """Search entities and return text results."""
        store = self._get_store(context)
        query_text = arguments.get("query_text") or arguments.get("entity_name", "")
        entity_type = arguments.get("entity_type")

        if not query_text:
            # Return graph stats
            stats = store.get_stats()
            html = self._format_stats_html(stats)
            return ComponentRenderPayload(
                component_id=self.component_id,
                render_target=RenderTarget.INLINE,
                html=html,
                metadata={"tool_name": self.tool_name, "action": "query", "stats": stats},
            )

        results = store.search_entities(query_text, limit=20, entity_type=entity_type)
        if not results:
            html = f"<p class='text-gray-400'>No entities found matching '{query_text}'.</p>"
        else:
            html = self._format_query_results_html(results, query_text)

        return ComponentRenderPayload(
            component_id=self.component_id,
            render_target=RenderTarget.INLINE,
            html=html,
            metadata={"tool_name": self.tool_name, "action": "query", "result_count": len(results)},
        )

    async def _handle_visualize(self, arguments: Dict, context: Optional[Dict]) -> ComponentRenderPayload:
        """Build D3 force-graph spec for frontend rendering."""
        store = self._get_store(context)
        entity_name = arguments.get("entity_name")
        depth = arguments.get("depth", 2)
        title = arguments.get("title", f"Knowledge Graph{': ' + entity_name if entity_name else ''}")

        if entity_name:
            entity = store.get_entity_by_name(entity_name)
            if entity:
                subgraph = store.extract_subgraph([entity["id"]], depth=depth, max_nodes=50)
            else:
                # Try search
                results = store.search_entities(entity_name, limit=3)
                if results:
                    subgraph = store.extract_subgraph(
                        [e["id"] for e in results], depth=depth, max_nodes=50
                    )
                else:
                    subgraph = {"entities": [], "relationships": []}
        else:
            subgraph = store.get_full_graph(max_nodes=100)

        if not subgraph["entities"]:
            return ComponentRenderPayload(
                component_id=self.component_id,
                render_target=RenderTarget.INLINE,
                html="<p class='text-gray-400'>Knowledge graph is empty. Use 'add_entity' to populate it, or import entities via the REST API.</p>",
                metadata={"tool_name": self.tool_name, "action": "visualize", "node_count": 0},
            )

        # Get importance scores for node sizing
        importance = store.get_entity_importance()

        # Build D3 spec
        nodes = []
        links = []
        node_id_map = {}

        for i, entity in enumerate(subgraph["entities"]):
            node_id_map[entity["id"]] = i
            nodes.append({
                "id": i,
                "entity_id": entity["id"],
                "name": entity["name"],
                "type": entity["entity_type"],
                "properties": entity.get("properties", {}),
                "importance": round(importance.get(entity["id"], 0), 3),
                "is_center": entity["name"].lower() == (entity_name or "").lower(),
            })

        for rel in subgraph["relationships"]:
            source_idx = node_id_map.get(rel["source_id"])
            target_idx = node_id_map.get(rel["target_id"])
            if source_idx is not None and target_idx is not None:
                links.append({
                    "source": source_idx,
                    "target": target_idx,
                    "type": rel["relationship_type"],
                    "cardinality": rel.get("cardinality"),
                    "metadata": rel.get("metadata", {}),
                })

        window_id = f"kg-{uuid.uuid4().hex[:8]}"

        return ComponentRenderPayload(
            component_id=self.component_id,
            render_target=RenderTarget.SUB_WINDOW,
            spec={
                "nodes": nodes,
                "links": links,
                "title": title,
                "center_entity": entity_name,
                "depth": depth,
                "entity_type_colors": ENTITY_TYPE_COLORS,
            },
            title=title,
            window_id=window_id,
            window_action="create",
            interactive=True,
            metadata={
                "tool_name": self.tool_name,
                "node_count": len(nodes),
                "link_count": len(links),
                "action": "visualize",
            },
        )

    async def _handle_add_entity(self, arguments: Dict, context: Optional[Dict]) -> ComponentRenderPayload:
        """Add an entity to the graph."""
        store = self._get_store(context)
        name = arguments["entity_name"]
        entity_type = arguments["entity_type"]
        properties = arguments.get("properties", {})

        entity_id = store.add_entity(
            name=name,
            entity_type=entity_type,
            properties=properties,
            source="llm_inferred",
        )

        color = ENTITY_TYPE_COLORS.get(entity_type, "#6b7280")
        props_html = f'<br><small class="text-gray-400">{properties}</small>' if properties else ""
        html = (
            f"<div class='glass-panel p-3 rounded-lg border' style='border-color: {color}40'>"
            f"<span style='color: {color}'>&#9679;</span> "
            f"Added <strong>{entity_type}</strong> entity: <strong>{name}</strong>"
            f"{props_html}"
            f"</div>"
        )

        return ComponentRenderPayload(
            component_id=self.component_id,
            render_target=RenderTarget.INLINE,
            html=html,
            metadata={
                "tool_name": self.tool_name, "action": "add_entity",
                "entity_id": entity_id, "name": name, "entity_type": entity_type,
            },
        )

    async def _handle_add_relationship(self, arguments: Dict, context: Optional[Dict]) -> ComponentRenderPayload:
        """Add a relationship between two entities."""
        store = self._get_store(context)

        source_name = arguments["entity_name"]
        target_name = arguments["target_entity"]
        rel_type = arguments["relationship_type"]
        source_type = arguments.get("entity_type")
        target_type = arguments.get("target_entity_type")

        # Resolve source and target entities
        source_ent = store.get_entity_by_name(source_name, source_type)
        target_ent = store.get_entity_by_name(target_name, target_type)

        if not source_ent:
            return ComponentRenderPayload(
                component_id=self.component_id,
                render_target=RenderTarget.INLINE,
                html=f"<p class='text-red-400'>Source entity '{source_name}' not found in the knowledge graph.</p>",
                metadata={"tool_name": self.tool_name, "action": "add_relationship", "error": True},
            )

        if not target_ent:
            return ComponentRenderPayload(
                component_id=self.component_id,
                render_target=RenderTarget.INLINE,
                html=f"<p class='text-red-400'>Target entity '{target_name}' not found in the knowledge graph.</p>",
                metadata={"tool_name": self.tool_name, "action": "add_relationship", "error": True},
            )

        rel_id = store.add_relationship(
            source_entity_id=source_ent["id"],
            target_entity_id=target_ent["id"],
            relationship_type=rel_type,
            cardinality=arguments.get("cardinality"),
            metadata=arguments.get("properties", {}),
            source="llm_inferred",
        )

        src_color = ENTITY_TYPE_COLORS.get(source_ent["entity_type"], "#6b7280")
        tgt_color = ENTITY_TYPE_COLORS.get(target_ent["entity_type"], "#6b7280")
        html = (
            f"<div class='glass-panel p-3 rounded-lg border' style='border-color: var(--border-primary)'>"
            f"<span style='color: {src_color}'>&#9679;</span> {source_name} "
            f"<span class='text-gray-400'>--[{rel_type}]--&gt;</span> "
            f"<span style='color: {tgt_color}'>&#9679;</span> {target_name}"
            f"</div>"
        )

        return ComponentRenderPayload(
            component_id=self.component_id,
            render_target=RenderTarget.INLINE,
            html=html,
            metadata={
                "tool_name": self.tool_name, "action": "add_relationship",
                "relationship_id": rel_id, "source": source_name, "target": target_name,
                "type": rel_type,
            },
        )

    async def _handle_get_context(self, arguments: Dict, context: Optional[Dict]) -> ComponentRenderPayload:
        """Get enrichment context text (for debugging/testing)."""
        store = self._get_store(context)
        query_text = arguments.get("query_text", "")

        if query_text:
            entities = self._search_entities_for_query(store, query_text)
            if entities:
                subgraph = store.extract_subgraph([e["id"] for e in entities], depth=2, max_nodes=30)
                context_text = self._format_subgraph_for_prompt(subgraph)
            else:
                context_text = "(No relevant entities found)"
        else:
            stats = store.get_stats()
            context_text = f"Graph has {stats.get('total_entities', 0)} entities and {stats.get('total_relationships', 0)} relationships."

        html = f"<pre class='text-sm text-gray-300 bg-gray-900 p-3 rounded-lg overflow-auto'>{context_text}</pre>"

        return ComponentRenderPayload(
            component_id=self.component_id,
            render_target=RenderTarget.INLINE,
            html=html,
            metadata={"tool_name": self.tool_name, "action": "get_context"},
        )

    # -------------------------------------------------------------------
    # HTML formatting helpers
    # -------------------------------------------------------------------

    def _format_stats_html(self, stats: Dict[str, Any]) -> str:
        """Format graph statistics as HTML."""
        total_ent = stats.get("total_entities", 0)
        total_rel = stats.get("total_relationships", 0)

        if total_ent == 0:
            return "<p class='text-gray-400'>Knowledge graph is empty. Use 'add_entity' to populate it.</p>"

        lines = [
            f"<div class='glass-panel p-4 rounded-lg'>",
            f"<h4 class='text-white font-semibold mb-2'>Knowledge Graph Statistics</h4>",
            f"<p class='text-gray-300'>Entities: <strong>{total_ent}</strong> | Relationships: <strong>{total_rel}</strong></p>",
        ]

        entity_types = stats.get("entity_types", {})
        if entity_types:
            lines.append("<div class='mt-2 flex flex-wrap gap-2'>")
            for etype, count in sorted(entity_types.items()):
                color = ENTITY_TYPE_COLORS.get(etype, "#6b7280")
                lines.append(
                    f"<span class='px-2 py-1 rounded text-xs' style='background:{color}20;color:{color}'>"
                    f"{etype}: {count}</span>"
                )
            lines.append("</div>")

        components = stats.get("connected_components", 0)
        density = stats.get("density", 0)
        if components:
            lines.append(
                f"<p class='text-gray-400 text-sm mt-2'>Components: {components} | "
                f"Density: {density}</p>"
            )

        lines.append("</div>")
        return "\n".join(lines)

    def _format_query_results_html(self, results: List[Dict], query: str) -> str:
        """Format search results as HTML cards."""
        lines = [
            f"<div class='space-y-2'>",
            f"<p class='text-gray-400 text-sm'>{len(results)} entities matching '{query}':</p>",
        ]

        for ent in results:
            color = ENTITY_TYPE_COLORS.get(ent["entity_type"], "#6b7280")
            props = ent.get("properties", {})
            desc = props.get("description", "")

            desc_html = f'<span class="text-gray-400 text-sm ml-2">{desc}</span>' if desc else ""
            lines.append(
                f"<div class='flex items-center gap-2 p-2 rounded' style='background:rgba(255,255,255,0.03)'>"
                f"<span style='color:{color}'>&#9679;</span>"
                f"<span class='text-white'>{ent['name']}</span>"
                f"<span class='text-gray-500 text-xs'>{ent['entity_type']}</span>"
                f"{desc_html}"
                f"</div>"
            )

        lines.append("</div>")
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # Store access helpers
    # -------------------------------------------------------------------

    def _get_store(self, context: Optional[Dict]) -> Any:
        """Get GraphStore scoped to the active profile + user."""
        from components.builtin.knowledge_graph.graph_store import GraphStore

        ctx = context or {}
        profile_id = ctx.get("profile_id", "__default__")
        user_uuid = ctx.get("user_uuid", "system")
        return GraphStore(profile_id, user_uuid)

    def _get_store_direct(self, profile_id: str, user_uuid: str) -> Any:
        """Get GraphStore with explicit profile/user (for context enrichment)."""
        from components.builtin.knowledge_graph.graph_store import GraphStore

        return GraphStore(profile_id, user_uuid)
