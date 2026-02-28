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
    ) -> tuple:
        """
        Context enrichment for the planner — the core guardrail mechanism.

        Extracts a relevant subgraph based on keyword matching of the query
        against entity names, descriptions, and business meanings. Returns
        a tuple of (formatted_text, metadata_dict) suitable for prompt
        injection and Live Status event emission.

        Uses ONLY the active KG for this profile. At most one KG can be active
        per profile at a time (enforced by kg_profile_assignments.is_active).
        Falls back to the profile's own KG if no assignment row exists yet
        (backward compatibility for profiles created before the assignment system).

        Called by ComponentManager.get_context_enrichment() before strategic planning.

        Returns:
            (text, metadata) where metadata is a dict with entity/relationship
            counts for the Live Status event, or ("", None) if no enrichment.
        """
        # Determine which KG to use: the active one from the assignment table
        active_kg_owner = self._get_active_kg_owner(profile_id, user_uuid)

        if active_kg_owner:
            kg_pid = active_kg_owner
        else:
            # Fallback: no assignment rows yet — use the profile's own KG
            kg_pid = profile_id

        logger.debug(f"KG enrichment: resolved kg_pid={kg_pid} for profile_id={profile_id}")

        store = self._get_store_direct(kg_pid, user_uuid)
        entities = self._search_entities_for_query(store, query)

        logger.debug(f"KG enrichment: found {len(entities)} matching entities for query")

        if not entities:
            return "", None

        entity_ids = [e["id"] for e in entities]

        # Adaptive extraction: entity-type-aware, unbounded FK chains,
        # iterative joinable-table discovery, budget-aware column expansion.
        # Replaces the old all-tables-as-seeds + fixed depth=2 + max_nodes=50
        # approach which missed multi-hop JOIN chains and truncated at ~5 tables.
        subgraph = store.extract_subgraph_adaptive(
            seed_entity_ids=entity_ids,
            query_entity_ids=entity_ids,
            max_nodes=500,
        )

        if not subgraph.get("entities"):
            logger.debug("KG enrichment: subgraph extraction returned no entities")
            return "", None

        # Collect entity type names for the event
        entity_types = list({e["entity_type"] for e in subgraph["entities"]})
        relationships = subgraph.get("relationships", [])

        metadata = {
            "kg_owner_profile_id": kg_pid,
            "entity_count": len(subgraph["entities"]),
            "relationship_count": len(relationships),
            "entity_types": entity_types,
        }

        # Format as structured text for prompt injection
        return self._format_subgraph_for_prompt(subgraph), metadata

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

        # Build entity→database lookup from 'contains' relationships
        # Pattern: database --[contains]--> table --[contains]--> column
        entity_db_map: Dict[str, str] = {}
        db_entities = {e["name"] for e in subgraph["entities"] if e["entity_type"] == "database"}
        table_entities = {e["name"] for e in subgraph["entities"] if e["entity_type"] == "table"}
        column_entity_map = {e["name"]: e for e in subgraph["entities"] if e["entity_type"] == "column"}

        for rel in subgraph.get("relationships", []):
            if rel["relationship_type"] == "contains" and rel["source_name"] in db_entities:
                entity_db_map[rel["target_name"]] = rel["source_name"]
        # Propagate: if a table is in a database, its columns are too
        table_db = dict(entity_db_map)
        for rel in subgraph.get("relationships", []):
            if rel["relationship_type"] == "contains" and rel["source_name"] in table_db:
                entity_db_map[rel["target_name"]] = table_db[rel["source_name"]]

        # Build table→columns mapping from contains relationships
        # table_columns: {table_name: [(col_name, col_type), ...]}
        table_columns: Dict[str, List[tuple]] = {}
        table_col_contains = set()  # Track (table, column) pairs to filter from relationships
        for rel in subgraph.get("relationships", []):
            if (rel["relationship_type"] == "contains"
                    and rel["source_name"] in table_entities
                    and rel["target_name"] in column_entity_map):
                tbl = rel["source_name"]
                col_name = rel["target_name"]
                col_entity = column_entity_map[col_name]
                col_type = (col_entity.get("properties", {}).get("CType", "")
                            or col_entity.get("properties", {}).get("data_type", ""))
                if tbl not in table_columns:
                    table_columns[tbl] = []
                table_columns[tbl].append((col_name, col_type))
                table_col_contains.add((rel["source_name"], rel["target_name"]))

        # Emit TABLE SCHEMAS section if we have table-column data
        if table_columns:
            lines.append("\nTABLE SCHEMAS (use these to validate SQL column references):")
            for tbl in sorted(table_columns.keys()):
                db_name = entity_db_map.get(tbl, "")
                cols = table_columns[tbl]
                col_strs = [f"{c}({t})" if t else c for c, t in cols]
                db_prefix = f"{db_name}." if db_name else ""
                lines.append(f"  {db_prefix}{tbl}: {', '.join(col_strs)}")

            # Build joinable columns: columns appearing in 2+ tables
            col_tables: Dict[str, List[str]] = {}
            for tbl, cols in table_columns.items():
                for col_name, _ in cols:
                    if col_name not in col_tables:
                        col_tables[col_name] = []
                    col_tables[col_name].append(tbl)
            joinable = {c: tbls for c, tbls in col_tables.items() if len(tbls) > 1}
            if joinable:
                lines.append("\nJOINABLE COLUMNS (shared across tables — use for JOIN conditions):")
                for col, tbls in sorted(joinable.items()):
                    lines.append(f"  {col}: {', '.join(sorted(tbls))}")

        # Group entities by type — skip columns (already in TABLE SCHEMAS)
        by_type: Dict[str, List] = {}
        for entity in subgraph["entities"]:
            etype = entity["entity_type"]
            if etype == "column" and table_columns:
                continue  # Already represented in TABLE SCHEMAS
            if etype not in by_type:
                by_type[etype] = []
            by_type[etype].append(entity)

        for etype, entities in sorted(by_type.items()):
            lines.append(f"\n{etype.upper()} ENTITIES:")
            for e in entities:
                props = e.get("properties", {})
                desc = props.get("description", "")
                biz = props.get("business_meaning", "")
                dtype = props.get("data_type", "") or props.get("CType", "")
                db_name = entity_db_map.get(e["name"], "")

                line = f"  - {e['name']}"
                parts = []
                if desc:
                    parts.append(desc)
                if dtype:
                    parts.append(f"type: {dtype}")
                if db_name:
                    parts.append(f"database: {db_name}")
                if biz:
                    parts.append(f"business: {biz}")
                if parts:
                    line += f" ({'; '.join(parts)})"
                lines.append(line)

        if subgraph["relationships"]:
            # Filter out table→column contains (already in TABLE SCHEMAS)
            non_schema_rels = [
                rel for rel in subgraph["relationships"]
                if not (rel["relationship_type"] == "contains"
                        and (rel["source_name"], rel["target_name"]) in table_col_contains)
            ]
            if non_schema_rels:
                lines.append("\nKNOWN RELATIONSHIPS:")
                for rel in non_schema_rels:
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
                subgraph = store.extract_subgraph_adaptive(
                    seed_entity_ids=[entity["id"]], max_nodes=100,
                )
            else:
                # Try search
                results = store.search_entities(entity_name, limit=3)
                if results:
                    subgraph = store.extract_subgraph_adaptive(
                        seed_entity_ids=[e["id"] for e in results], max_nodes=100,
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

        return ComponentRenderPayload(
            component_id=self.component_id,
            render_target=RenderTarget.INLINE,
            spec={
                "nodes": nodes,
                "links": links,
                "title": title,
                "center_entity": entity_name,
                "depth": depth,
                "entity_type_colors": ENTITY_TYPE_COLORS,
            },
            title=title,
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
                subgraph = store.extract_subgraph_adaptive(
                    seed_entity_ids=[e["id"] for e in entities],
                    max_nodes=200,
                )
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
        """Get GraphStore scoped to the active KG owner for this profile + user."""
        from components.builtin.knowledge_graph.graph_store import GraphStore

        ctx = context or {}
        profile_id = ctx.get("profile_id", "__default__")
        user_uuid = ctx.get("user_uuid", "system")

        # Resolve through assignment table (same logic as get_context_enrichment)
        active_kg_owner = self._get_active_kg_owner(profile_id, user_uuid)
        kg_pid = active_kg_owner if active_kg_owner else profile_id

        return GraphStore(kg_pid, user_uuid)

    def _get_store_direct(self, profile_id: str, user_uuid: str) -> Any:
        """Get GraphStore with explicit profile/user (for context enrichment)."""
        from components.builtin.knowledge_graph.graph_store import GraphStore

        return GraphStore(profile_id, user_uuid)

    def _get_active_kg_owner(self, profile_id: str, user_uuid: str) -> Optional[str]:
        """
        Look up which KG is currently ACTIVE for this profile via kg_profile_assignments.

        Returns the owner profile_id of the active KG, or None if no KG is active.
        The active KG could be the profile's own (self-assignment) or another profile's KG.
        Only one KG can be active per profile at a time (enforced by partial unique index).
        """
        import sqlite3

        try:
            from trusted_data_agent.core.config import APP_CONFIG
            db_path = APP_CONFIG.AUTH_DB_PATH.replace("sqlite:///", "")
        except Exception:
            db_path = "tda_auth.db"

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT kg_owner_profile_id FROM kg_profile_assignments "
                "WHERE assigned_profile_id = ? AND user_uuid = ? AND is_active = 1",
                (profile_id, user_uuid),
            )
            row = cursor.fetchone()
            conn.close()
            return row[0] if row else None
        except Exception as e:
            logger.warning(f"Failed to query active KG assignment: {e}")
            return None
