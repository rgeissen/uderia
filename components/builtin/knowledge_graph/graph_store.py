"""
Graph Store — Dual-layer entity-relationship persistence for the Knowledge Graph.

SQLite for durable storage (tda_auth.db), NetworkX DiGraph for graph algorithms.
Scoped by (profile_id, user_uuid) for multi-user isolation.

Architecture:
    GraphStore(profile_id, user_uuid)
      ├── SQLite layer         ← CRUD, persistence, search
      └── NetworkX DiGraph     ← BFS, shortest path, centrality, cycle detection
          Lazy-loaded, cached, invalidated on writes
"""

import json
import logging
import sqlite3
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import networkx as nx

    HAS_NETWORKX = True
except ImportError:
    HAS_NETWORKX = False

logger = logging.getLogger("quart.app")

# Valid entity types
ENTITY_TYPES = {
    "database", "table", "column", "foreign_key",
    "business_concept", "taxonomy", "metric", "domain",
}

# Valid relationship types
RELATIONSHIP_TYPES = {
    "contains", "foreign_key", "is_a", "has_property",
    "measures", "derives_from", "depends_on", "relates_to",
}

# Entity type classification for adaptive subgraph extraction
_EXPANDABLE_STRUCTURAL_TYPES = frozenset({"table", "foreign_key"})
_SEMANTIC_TYPES = frozenset({"business_concept", "taxonomy", "metric", "domain"})

# Max rounds of iterative joinable-table discovery (handles N-way transitive joins)
_MAX_JOIN_DISCOVERY_ROUNDS = 3


class GraphStore:
    """
    Dual-layer graph store scoped to a single (profile_id, user_uuid) pair.

    SQLite handles durable CRUD. NetworkX provides graph algorithms
    (BFS, shortest path, centrality, cycle detection). The NetworkX graph
    is lazily loaded from SQLite on first graph operation and cached.
    Any write operation invalidates the cache.
    """

    def __init__(self, profile_id: str, user_uuid: str, db_path: Optional[str] = None):
        self.profile_id = profile_id
        self.user_uuid = user_uuid

        if db_path:
            self._db_path = db_path
        else:
            try:
                from trusted_data_agent.core.config import APP_CONFIG
                self._db_path = APP_CONFIG.AUTH_DB_PATH.replace("sqlite:///", "")
            except Exception:
                self._db_path = "tda_auth.db"

        # NetworkX cache — lazy-loaded, invalidated on writes
        self._graph: Optional[Any] = None

    # -----------------------------------------------------------------------
    # SQLite connection helper
    # -----------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _invalidate_cache(self) -> None:
        """Invalidate the in-memory NetworkX graph cache."""
        self._graph = None

    # -----------------------------------------------------------------------
    # Entity CRUD
    # -----------------------------------------------------------------------

    def add_entity(
        self,
        name: str,
        entity_type: str,
        properties: Optional[Dict[str, Any]] = None,
        source: str = "manual",
        source_detail: Optional[str] = None,
    ) -> int:
        """
        Add an entity (node) to the graph. Upserts on (profile_id, user_uuid, name, entity_type).

        Returns:
            The entity ID (new or existing).
        """
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"Invalid entity_type '{entity_type}'. Must be one of: {ENTITY_TYPES}")

        props_json = json.dumps(properties or {})
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                INSERT INTO kg_entities (profile_id, user_uuid, name, entity_type, properties_json, source, source_detail, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, user_uuid, name, entity_type)
                DO UPDATE SET
                    properties_json = excluded.properties_json,
                    source = excluded.source,
                    source_detail = excluded.source_detail,
                    updated_at = excluded.updated_at
                """,
                (self.profile_id, self.user_uuid, name, entity_type, props_json, source, source_detail, now, now),
            )
            conn.commit()
            entity_id = cursor.lastrowid

            # If upsert updated an existing row, lastrowid may be 0 — fetch the real ID
            if not entity_id:
                row = conn.execute(
                    "SELECT id FROM kg_entities WHERE profile_id=? AND user_uuid=? AND name=? AND entity_type=?",
                    (self.profile_id, self.user_uuid, name, entity_type),
                ).fetchone()
                entity_id = row["id"] if row else 0

            self._invalidate_cache()
            return entity_id
        finally:
            conn.close()

    def get_entity(self, entity_id: int) -> Optional[Dict[str, Any]]:
        """Get a single entity by ID (within profile scope)."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM kg_entities WHERE id=? AND profile_id=? AND user_uuid=?",
                (entity_id, self.profile_id, self.user_uuid),
            ).fetchone()
            return self._row_to_entity(row) if row else None
        finally:
            conn.close()

    def get_entity_by_name(self, name: str, entity_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Lookup entity by name (case-insensitive) within profile scope."""
        conn = self._get_conn()
        try:
            if entity_type:
                row = conn.execute(
                    "SELECT * FROM kg_entities WHERE profile_id=? AND user_uuid=? AND name=? COLLATE NOCASE AND entity_type=?",
                    (self.profile_id, self.user_uuid, name, entity_type),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM kg_entities WHERE profile_id=? AND user_uuid=? AND name=? COLLATE NOCASE",
                    (self.profile_id, self.user_uuid, name),
                ).fetchone()
            return self._row_to_entity(row) if row else None
        finally:
            conn.close()

    def search_entities(self, query_text: str, limit: int = 10, entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search entities by name/description substring matching.
        V2: Replace with embedding-based semantic search.
        """
        conn = self._get_conn()
        try:
            pattern = f"%{query_text}%"
            if entity_type:
                rows = conn.execute(
                    """
                    SELECT * FROM kg_entities
                    WHERE profile_id=? AND user_uuid=? AND entity_type=?
                      AND (name LIKE ? COLLATE NOCASE OR properties_json LIKE ? COLLATE NOCASE)
                    ORDER BY name LIMIT ?
                    """,
                    (self.profile_id, self.user_uuid, entity_type, pattern, pattern, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM kg_entities
                    WHERE profile_id=? AND user_uuid=?
                      AND (name LIKE ? COLLATE NOCASE OR properties_json LIKE ? COLLATE NOCASE)
                    ORDER BY name LIMIT ?
                    """,
                    (self.profile_id, self.user_uuid, pattern, pattern, limit),
                ).fetchall()
            return [self._row_to_entity(r) for r in rows]
        finally:
            conn.close()

    def list_entities(self, entity_type: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """List all entities, optionally filtered by type."""
        conn = self._get_conn()
        try:
            if entity_type:
                rows = conn.execute(
                    "SELECT * FROM kg_entities WHERE profile_id=? AND user_uuid=? AND entity_type=? ORDER BY name LIMIT ?",
                    (self.profile_id, self.user_uuid, entity_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM kg_entities WHERE profile_id=? AND user_uuid=? ORDER BY entity_type, name LIMIT ?",
                    (self.profile_id, self.user_uuid, limit),
                ).fetchall()
            return [self._row_to_entity(r) for r in rows]
        finally:
            conn.close()

    def update_entity(self, entity_id: int, properties: Dict[str, Any]) -> bool:
        """Merge new properties into an existing entity."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT properties_json FROM kg_entities WHERE id=? AND profile_id=? AND user_uuid=?",
                (entity_id, self.profile_id, self.user_uuid),
            ).fetchone()
            if not row:
                return False

            existing = json.loads(row["properties_json"] or "{}")
            existing.update(properties)
            now = datetime.now(timezone.utc).isoformat()

            conn.execute(
                "UPDATE kg_entities SET properties_json=?, updated_at=? WHERE id=? AND profile_id=? AND user_uuid=?",
                (json.dumps(existing), now, entity_id, self.profile_id, self.user_uuid),
            )
            conn.commit()
            self._invalidate_cache()
            return True
        finally:
            conn.close()

    def delete_entity(self, entity_id: int) -> bool:
        """Delete an entity and all its relationships (CASCADE)."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM kg_entities WHERE id=? AND profile_id=? AND user_uuid=?",
                (entity_id, self.profile_id, self.user_uuid),
            )
            conn.commit()
            self._invalidate_cache()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Relationship CRUD
    # -----------------------------------------------------------------------

    def add_relationship(
        self,
        source_entity_id: int,
        target_entity_id: int,
        relationship_type: str,
        cardinality: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        source: str = "manual",
    ) -> int:
        """Add a typed edge between two entities. Upserts on (profile, source, target, type)."""
        if relationship_type not in RELATIONSHIP_TYPES:
            raise ValueError(f"Invalid relationship_type '{relationship_type}'. Must be one of: {RELATIONSHIP_TYPES}")

        metadata_json = json.dumps(metadata or {})
        now = datetime.now(timezone.utc).isoformat()

        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                INSERT INTO kg_relationships (profile_id, user_uuid, source_entity_id, target_entity_id,
                                              relationship_type, cardinality, metadata_json, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, user_uuid, source_entity_id, target_entity_id, relationship_type)
                DO UPDATE SET
                    cardinality = excluded.cardinality,
                    metadata_json = excluded.metadata_json,
                    source = excluded.source
                """,
                (self.profile_id, self.user_uuid, source_entity_id, target_entity_id,
                 relationship_type, cardinality, metadata_json, source, now),
            )
            conn.commit()
            rel_id = cursor.lastrowid

            if not rel_id:
                row = conn.execute(
                    """SELECT id FROM kg_relationships
                       WHERE profile_id=? AND user_uuid=? AND source_entity_id=?
                         AND target_entity_id=? AND relationship_type=?""",
                    (self.profile_id, self.user_uuid, source_entity_id, target_entity_id, relationship_type),
                ).fetchone()
                rel_id = row["id"] if row else 0

            self._invalidate_cache()
            return rel_id
        finally:
            conn.close()

    def get_relationships(self, entity_id: int, direction: str = "both") -> List[Dict[str, Any]]:
        """Get all edges from/to an entity. direction: 'outgoing', 'incoming', or 'both'."""
        conn = self._get_conn()
        try:
            results = []
            if direction in ("outgoing", "both"):
                rows = conn.execute(
                    """
                    SELECT r.*, e1.name AS source_name, e1.entity_type AS source_type,
                           e2.name AS target_name, e2.entity_type AS target_type
                    FROM kg_relationships r
                    JOIN kg_entities e1 ON r.source_entity_id = e1.id
                    JOIN kg_entities e2 ON r.target_entity_id = e2.id
                    WHERE r.source_entity_id=? AND r.profile_id=? AND r.user_uuid=?
                    """,
                    (entity_id, self.profile_id, self.user_uuid),
                ).fetchall()
                results.extend(self._row_to_relationship(r) for r in rows)

            if direction in ("incoming", "both"):
                rows = conn.execute(
                    """
                    SELECT r.*, e1.name AS source_name, e1.entity_type AS source_type,
                           e2.name AS target_name, e2.entity_type AS target_type
                    FROM kg_relationships r
                    JOIN kg_entities e1 ON r.source_entity_id = e1.id
                    JOIN kg_entities e2 ON r.target_entity_id = e2.id
                    WHERE r.target_entity_id=? AND r.profile_id=? AND r.user_uuid=?
                    """,
                    (entity_id, self.profile_id, self.user_uuid),
                ).fetchall()
                results.extend(self._row_to_relationship(r) for r in rows)

            # Deduplicate (both direction may overlap for self-referential)
            seen = set()
            unique = []
            for rel in results:
                if rel["id"] not in seen:
                    seen.add(rel["id"])
                    unique.append(rel)
            return unique
        finally:
            conn.close()

    def list_relationships(self, entity_id: Optional[int] = None, relationship_type: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        """List relationships with optional filters."""
        conn = self._get_conn()
        try:
            query = """
                SELECT r.*, e1.name AS source_name, e1.entity_type AS source_type,
                       e2.name AS target_name, e2.entity_type AS target_type
                FROM kg_relationships r
                JOIN kg_entities e1 ON r.source_entity_id = e1.id
                JOIN kg_entities e2 ON r.target_entity_id = e2.id
                WHERE r.profile_id=? AND r.user_uuid=?
            """
            params: list = [self.profile_id, self.user_uuid]

            if entity_id is not None:
                query += " AND (r.source_entity_id=? OR r.target_entity_id=?)"
                params.extend([entity_id, entity_id])
            if relationship_type:
                query += " AND r.relationship_type=?"
                params.append(relationship_type)

            query += " ORDER BY r.created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._row_to_relationship(r) for r in rows]
        finally:
            conn.close()

    def delete_relationship(self, relationship_id: int) -> bool:
        """Delete a single relationship."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM kg_relationships WHERE id=? AND profile_id=? AND user_uuid=?",
                (relationship_id, self.profile_id, self.user_uuid),
            )
            conn.commit()
            self._invalidate_cache()
            return cursor.rowcount > 0
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Bulk operations
    # -----------------------------------------------------------------------

    def import_bulk(self, entities: List[Dict], relationships: List[Dict]) -> Dict[str, int]:
        """
        Bulk import entities and relationships.

        entities: list of {name, entity_type, properties?, source?}
        relationships: list of {source_name, source_type, target_name, target_type, relationship_type, cardinality?, metadata?}

        Returns: {entities_added, relationships_added}
        """
        entities_added = 0
        rels_added = 0

        for ent in entities:
            try:
                self.add_entity(
                    name=ent["name"],
                    entity_type=ent["entity_type"],
                    properties=ent.get("properties"),
                    source=ent.get("source", "manual"),
                )
                entities_added += 1
            except Exception as e:
                logger.warning(f"Bulk import: failed to add entity '{ent.get('name')}': {e}")

        for rel in relationships:
            try:
                source_ent = self.get_entity_by_name(rel["source_name"], rel.get("source_type"))
                target_ent = self.get_entity_by_name(rel["target_name"], rel.get("target_type"))
                if source_ent and target_ent:
                    self.add_relationship(
                        source_entity_id=source_ent["id"],
                        target_entity_id=target_ent["id"],
                        relationship_type=rel["relationship_type"],
                        cardinality=rel.get("cardinality"),
                        metadata=rel.get("metadata"),
                        source=rel.get("source", "manual"),
                    )
                    rels_added += 1
                else:
                    missing = []
                    if not source_ent:
                        missing.append(f"source '{rel['source_name']}' (type: {rel.get('source_type', 'any')})")
                    if not target_ent:
                        missing.append(f"target '{rel['target_name']}' (type: {rel.get('target_type', 'any')})")
                    logger.warning(
                        f"Bulk import: could not resolve {', '.join(missing)} for relationship "
                        f"{rel.get('source_name')} --[{rel.get('relationship_type')}]--> {rel.get('target_name')}"
                    )
            except Exception as e:
                logger.warning(f"Bulk import: failed to add relationship: {e}")

        return {"entities_added": entities_added, "relationships_added": rels_added}

    def clear_graph(self) -> Dict[str, int]:
        """Delete all entities and relationships for this profile/user."""
        conn = self._get_conn()
        try:
            rels_deleted = conn.execute(
                "DELETE FROM kg_relationships WHERE profile_id=? AND user_uuid=?",
                (self.profile_id, self.user_uuid),
            ).rowcount
            entities_deleted = conn.execute(
                "DELETE FROM kg_entities WHERE profile_id=? AND user_uuid=?",
                (self.profile_id, self.user_uuid),
            ).rowcount
            conn.commit()
            self._invalidate_cache()
            return {"entities_deleted": entities_deleted, "relationships_deleted": rels_deleted}
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # NetworkX graph algorithms
    # -----------------------------------------------------------------------

    def _get_graph(self) -> Any:
        """
        Lazy-load the full graph from SQLite into a NetworkX DiGraph.
        Cached until invalidated by a write operation.
        """
        if self._graph is not None:
            return self._graph

        if not HAS_NETWORKX:
            logger.warning("NetworkX not installed — graph algorithms unavailable")
            return None

        G = nx.DiGraph()
        conn = self._get_conn()
        try:
            # Load nodes
            entities = conn.execute(
                "SELECT * FROM kg_entities WHERE profile_id=? AND user_uuid=?",
                (self.profile_id, self.user_uuid),
            ).fetchall()
            for e in entities:
                G.add_node(
                    e["id"],
                    name=e["name"],
                    entity_type=e["entity_type"],
                    properties=json.loads(e["properties_json"] or "{}"),
                    source=e["source"],
                )

            # Load edges
            rels = conn.execute(
                "SELECT * FROM kg_relationships WHERE profile_id=? AND user_uuid=?",
                (self.profile_id, self.user_uuid),
            ).fetchall()
            for r in rels:
                G.add_edge(
                    r["source_entity_id"],
                    r["target_entity_id"],
                    rel_id=r["id"],
                    relationship_type=r["relationship_type"],
                    cardinality=r["cardinality"],
                    metadata=json.loads(r["metadata_json"] or "{}"),
                )

            self._graph = G
            return G
        finally:
            conn.close()

    def extract_subgraph(
        self,
        entity_ids: List[int],
        depth: int = 2,
        max_nodes: int = 50,
    ) -> Dict[str, List]:
        """
        BFS traversal from seed entities up to given depth.
        Returns {entities: [...], relationships: [...]}.
        """
        G = self._get_graph()
        if G is None:
            return {"entities": [], "relationships": []}

        visited = set()
        queue: List[Tuple[int, int]] = []  # (node_id, current_depth)

        for eid in entity_ids:
            if eid in G:
                queue.append((eid, 0))
                visited.add(eid)

        while queue and len(visited) <= max_nodes:
            node_id, d = queue.pop(0)
            if d >= depth:
                continue

            # Explore both directions (successors and predecessors)
            neighbors = set(G.successors(node_id)) | set(G.predecessors(node_id))
            for neighbor in neighbors:
                if neighbor not in visited and len(visited) < max_nodes:
                    visited.add(neighbor)
                    queue.append((neighbor, d + 1))

        return self._subgraph_to_dict(G, visited)

    # -------------------------------------------------------------------
    # Adaptive subgraph extraction (entity-type-aware, scalable)
    # -------------------------------------------------------------------

    def extract_subgraph_adaptive(
        self,
        seed_entity_ids: List[int],
        query_entity_ids: Optional[List[int]] = None,
        max_nodes: int = 500,
    ) -> Dict[str, List]:
        """
        Entity-type-aware subgraph extraction for schemas with 1000s of entities.

        Instead of uniform BFS with a fixed depth that misses multi-hop join
        chains and silently truncates large graphs, this uses a three-phase
        approach that separates structural discovery from detail expansion.

        Phase 1 — Structural Discovery (unbounded):
            1a. FK-Chain Traversal: BFS through table/foreign_key nodes with
                NO depth limit.  Handles 3, 4, 5, N-way JOIN chains.
            1b. Joinable Table Discovery: Iteratively finds tables that share
                column names with already-discovered tables (up to 3 rounds
                for transitive join paths).
            1c. Database Context: Adds parent database entities for discovered
                tables (context only, not expanded).

        Phase 2 — Column Expansion (budget-aware):
            Adds column children for each discovered table.  Query-matched
            tables are prioritised; remaining budget allocated to other
            tables sorted by structural distance from the seeds.

        Phase 3 — Semantic Enrichment (capped at 50):
            Adds business_concept, metric, taxonomy, domain entities that
            have direct relationships to discovered structural entities.

        Args:
            seed_entity_ids: Starting entities (from query matching / search).
            query_entity_ids: Subset of seeds that directly matched the user
                query — these get priority for column expansion.
                If *None*, all seeds are treated as query-matched.
            max_nodes: Upper bound on total returned entities.

        Returns:
            {"entities": [...], "relationships": [...]}
        """
        G = self._get_graph()
        if G is None:
            return {"entities": [], "relationships": []}
        if not seed_entity_ids:
            return {"entities": [], "relationships": []}

        if query_entity_ids is None:
            query_entity_ids = list(seed_entity_ids)
        query_id_set = set(query_entity_ids)

        # ── Phase 1a: FK-Chain Traversal ───────────────────────────────
        # Unbounded BFS through expandable structural nodes (table,
        # foreign_key).  Skips database (hub), column (detail), and
        # semantic nodes.

        discovered_tables: Set[int] = set()
        discovered_fk_nodes: Set[int] = set()
        distance_from_seed: Dict[int, int] = {}
        bfs_queue: deque = deque()

        for sid in seed_entity_ids:
            if sid not in G:
                continue
            etype = G.nodes[sid].get("entity_type", "")

            if etype in _EXPANDABLE_STRUCTURAL_TYPES:
                target = discovered_tables if etype == "table" else discovered_fk_nodes
                target.add(sid)
                distance_from_seed[sid] = 0
                bfs_queue.append((sid, 0))
            else:
                # Non-expandable seed (column, business_concept, …).
                # Promote to neighbouring structural nodes.
                for nbr in set(G.predecessors(sid)) | set(G.successors(sid)):
                    ntype = G.nodes[nbr].get("entity_type", "")
                    if ntype in _EXPANDABLE_STRUCTURAL_TYPES:
                        target = discovered_tables if ntype == "table" else discovered_fk_nodes
                        if nbr not in target:
                            target.add(nbr)
                            distance_from_seed[nbr] = 0
                            bfs_queue.append((nbr, 0))

        visited_expandable = discovered_tables | discovered_fk_nodes

        while bfs_queue:
            node_id, d = bfs_queue.popleft()
            for nbr in set(G.successors(node_id)) | set(G.predecessors(node_id)):
                if nbr in visited_expandable:
                    continue
                ntype = G.nodes[nbr].get("entity_type", "")
                if ntype not in _EXPANDABLE_STRUCTURAL_TYPES:
                    continue
                target = discovered_tables if ntype == "table" else discovered_fk_nodes
                target.add(nbr)
                visited_expandable.add(nbr)
                distance_from_seed[nbr] = d + 1
                bfs_queue.append((nbr, d + 1))

        fk_depth = max(distance_from_seed.values()) if distance_from_seed else 0
        logger.info(
            f"KG adaptive Phase 1a: {len(discovered_tables)} tables, "
            f"{len(discovered_fk_nodes)} FK nodes, max FK-chain depth={fk_depth} "
            f"(from {len(seed_entity_ids)} seeds)"
        )

        # ── Phase 1b: Joinable Table Discovery ────────────────────────
        # Iteratively find tables sharing column names with already-
        # discovered tables.  Handles transitive joins (A→B→C→D) even
        # when no FK edges exist in the graph.

        # Build full table-ID index once
        all_table_ids: Dict[int, str] = {}
        for nid, ndata in G.nodes(data=True):
            if ndata.get("entity_type") == "table":
                all_table_ids[nid] = ndata.get("name", "")

        def _column_names_for_tables(table_ids: Set[int]) -> Set[str]:
            """Collect column names owned by a set of table nodes."""
            names: Set[str] = set()
            for tid in table_ids:
                for succ in G.successors(tid):
                    if G.nodes[succ].get("entity_type") == "column":
                        cname = G.nodes[succ].get("name", "").lower()
                        if cname:
                            names.add(cname)
            return names

        for round_num in range(_MAX_JOIN_DISCOVERY_ROUNDS):
            seed_col_names = _column_names_for_tables(discovered_tables)
            if not seed_col_names:
                break

            new_tables: Set[int] = set()
            for tid in all_table_ids:
                if tid in discovered_tables:
                    continue
                # Check if this table has any column name matching the seed set
                for succ in G.successors(tid):
                    if G.nodes[succ].get("entity_type") == "column":
                        cname = G.nodes[succ].get("name", "").lower()
                        if cname and cname in seed_col_names:
                            new_tables.add(tid)
                            break

            if not new_tables:
                break

            for tid in new_tables:
                discovered_tables.add(tid)
                # Distance: one "logical hop" further than the deepest FK node
                distance_from_seed.setdefault(tid, fk_depth + round_num + 1)

            logger.info(
                f"KG adaptive Phase 1b round {round_num + 1}: "
                f"+{len(new_tables)} joinable tables"
            )

        # ── Phase 1c: Database Context ─────────────────────────────────
        discovered_databases: Set[int] = set()
        for tid in discovered_tables:
            for pred in G.predecessors(tid):
                if G.nodes[pred].get("entity_type") == "database":
                    discovered_databases.add(pred)

        # ── Assemble structural visited set ────────────────────────────
        visited: Set[int] = set()
        visited |= discovered_tables
        visited |= discovered_fk_nodes
        visited |= discovered_databases

        # Include original non-structural seed entities themselves
        for sid in seed_entity_ids:
            if sid in G:
                visited.add(sid)

        # ── Phase 2: Column Expansion (budget-aware) ───────────────────
        column_budget = max(0, max_nodes - len(visited))

        sorted_tables = sorted(
            discovered_tables,
            key=lambda tid: (
                0 if tid in query_id_set else 1,
                distance_from_seed.get(tid, 999),
            ),
        )

        columns_added = 0
        tables_with_columns = 0
        for tid in sorted_tables:
            if column_budget <= 0:
                break
            table_cols = [
                succ for succ in G.successors(tid)
                if succ not in visited
                and G.nodes[succ].get("entity_type") == "column"
            ]
            if table_cols:
                to_add = table_cols[:column_budget]
                visited.update(to_add)
                column_budget -= len(to_add)
                columns_added += len(to_add)
                tables_with_columns += 1

        logger.info(
            f"KG adaptive Phase 2: {columns_added} columns "
            f"for {tables_with_columns}/{len(discovered_tables)} tables, "
            f"{column_budget} budget remaining"
        )

        # ── Phase 3: Semantic Enrichment ───────────────────────────────
        semantic_budget = min(max(0, max_nodes - len(visited)), 50)
        semantic_added = 0

        if semantic_budget > 0:
            structural_visited = discovered_tables | discovered_fk_nodes | discovered_databases
            for nid in structural_visited:
                if semantic_budget <= 0:
                    break
                for nbr in set(G.successors(nid)) | set(G.predecessors(nid)):
                    if nbr in visited:
                        continue
                    if G.nodes[nbr].get("entity_type") in _SEMANTIC_TYPES:
                        visited.add(nbr)
                        semantic_budget -= 1
                        semantic_added += 1
                        if semantic_budget <= 0:
                            break

        logger.info(
            f"KG adaptive extraction complete: "
            f"{len(visited)} total nodes "
            f"({len(discovered_tables)} tables, "
            f"{columns_added} columns, "
            f"{semantic_added} semantic)"
        )

        return self._subgraph_to_dict(G, visited)

    def get_full_graph(self, max_nodes: int = 100) -> Dict[str, List]:
        """Return entire graph (capped by max_nodes)."""
        G = self._get_graph()
        if G is None:
            return {"entities": [], "relationships": []}

        nodes = set(list(G.nodes())[:max_nodes])
        return self._subgraph_to_dict(G, nodes)

    def find_shortest_path(self, source_id: int, target_id: int) -> Optional[List[int]]:
        """Find shortest path between two entities. Returns list of entity IDs or None."""
        G = self._get_graph()
        if G is None:
            return None

        try:
            # Use undirected view for path finding
            return nx.shortest_path(G.to_undirected(), source_id, target_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    def get_connected_entities(self, entity_id: int) -> Dict[str, List[int]]:
        """Get all entities reachable from this entity."""
        G = self._get_graph()
        if G is None:
            return {"descendants": [], "ancestors": []}

        try:
            descendants = list(nx.descendants(G, entity_id))
        except nx.NetworkXError:
            descendants = []

        try:
            ancestors = list(nx.ancestors(G, entity_id))
        except nx.NetworkXError:
            ancestors = []

        return {"descendants": descendants, "ancestors": ancestors}

    def get_entity_importance(self) -> Dict[int, float]:
        """Rank entities by connectivity (degree centrality)."""
        G = self._get_graph()
        if G is None or len(G) == 0:
            return {}
        return nx.degree_centrality(G)

    def detect_cycles(self) -> List[List[int]]:
        """Detect cycles in the graph (useful for taxonomy validation)."""
        G = self._get_graph()
        if G is None:
            return []
        try:
            cycles = list(nx.simple_cycles(G))
            return cycles[:20]  # Cap at 20 cycles for safety
        except Exception:
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Return graph statistics."""
        G = self._get_graph()
        if G is None:
            # Fallback to SQL counts
            conn = self._get_conn()
            try:
                ent_count = conn.execute(
                    "SELECT COUNT(*) FROM kg_entities WHERE profile_id=? AND user_uuid=?",
                    (self.profile_id, self.user_uuid),
                ).fetchone()[0]
                rel_count = conn.execute(
                    "SELECT COUNT(*) FROM kg_relationships WHERE profile_id=? AND user_uuid=?",
                    (self.profile_id, self.user_uuid),
                ).fetchone()[0]
                return {
                    "total_entities": ent_count,
                    "total_relationships": rel_count,
                    "networkx_available": False,
                }
            finally:
                conn.close()

        # Rich stats via NetworkX
        entity_types: Dict[str, int] = {}
        for _, data in G.nodes(data=True):
            etype = data.get("entity_type", "unknown")
            entity_types[etype] = entity_types.get(etype, 0) + 1

        rel_types: Dict[str, int] = {}
        for _, _, data in G.edges(data=True):
            rtype = data.get("relationship_type", "unknown")
            rel_types[rtype] = rel_types.get(rtype, 0) + 1

        undirected = G.to_undirected()
        components = list(nx.connected_components(undirected))

        return {
            "total_entities": G.number_of_nodes(),
            "total_relationships": G.number_of_edges(),
            "entity_types": entity_types,
            "relationship_types": rel_types,
            "connected_components": len(components),
            "density": round(nx.density(G), 4) if G.number_of_nodes() > 1 else 0,
            "has_cycles": len(list(nx.simple_cycles(G))[:1]) > 0 if G.number_of_nodes() > 0 else False,
            "networkx_available": True,
        }

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _subgraph_to_dict(self, G: Any, node_ids: set) -> Dict[str, List]:
        """Convert a set of node IDs from the NetworkX graph to an entity/relationship dict."""
        entities = []
        for nid in node_ids:
            if nid in G:
                data = G.nodes[nid]
                entities.append({
                    "id": nid,
                    "name": data.get("name", ""),
                    "entity_type": data.get("entity_type", ""),
                    "properties": data.get("properties", {}),
                    "source": data.get("source", ""),
                })

        relationships = []
        for src, tgt, data in G.edges(data=True):
            if src in node_ids and tgt in node_ids:
                src_data = G.nodes[src]
                tgt_data = G.nodes[tgt]
                relationships.append({
                    "id": data.get("rel_id", 0),
                    "source_id": src,
                    "target_id": tgt,
                    "source_name": src_data.get("name", ""),
                    "target_name": tgt_data.get("name", ""),
                    "relationship_type": data.get("relationship_type", ""),
                    "cardinality": data.get("cardinality"),
                    "metadata": data.get("metadata", {}),
                })

        return {"entities": entities, "relationships": relationships}

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a sqlite3.Row to an entity dict."""
        return {
            "id": row["id"],
            "name": row["name"],
            "entity_type": row["entity_type"],
            "properties": json.loads(row["properties_json"] or "{}"),
            "source": row["source"],
            "source_detail": row["source_detail"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_relationship(row: sqlite3.Row) -> Dict[str, Any]:
        """Convert a sqlite3.Row to a relationship dict."""
        return {
            "id": row["id"],
            "source_entity_id": row["source_entity_id"],
            "target_entity_id": row["target_entity_id"],
            "source_name": row["source_name"],
            "source_type": row["source_type"],
            "target_name": row["target_name"],
            "target_type": row["target_type"],
            "relationship_type": row["relationship_type"],
            "cardinality": row["cardinality"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "source": row["source"],
            "created_at": row["created_at"],
        }

    # -------------------------------------------------------------------
    # Cross-profile enumeration (static — no instance needed)
    # -------------------------------------------------------------------

    @staticmethod
    def list_all_graphs(user_uuid: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all knowledge graphs for a user across all profiles.

        Returns one entry per profile_id that has at least one entity,
        with summary statistics (entity/relationship counts, type breakdowns).
        Ordered by most recently updated first.
        """
        if not db_path:
            try:
                from trusted_data_agent.core.config import APP_CONFIG
                db_path = APP_CONFIG.AUTH_DB_PATH.replace("sqlite:///", "")
            except Exception:
                db_path = "tda_auth.db"

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Profiles with KG data — aggregated stats
            rows = conn.execute(
                """
                SELECT profile_id,
                       COUNT(*) AS entity_count,
                       MIN(created_at) AS first_created,
                       MAX(updated_at) AS last_updated
                FROM kg_entities
                WHERE user_uuid = ?
                GROUP BY profile_id
                ORDER BY MAX(updated_at) DESC
                """,
                (user_uuid,),
            ).fetchall()

            results: List[Dict[str, Any]] = []
            for row in rows:
                pid = row["profile_id"]

                # Relationship count
                rel_count = conn.execute(
                    "SELECT COUNT(*) FROM kg_relationships WHERE profile_id = ? AND user_uuid = ?",
                    (pid, user_uuid),
                ).fetchone()[0]

                # Entity type breakdown
                type_rows = conn.execute(
                    """
                    SELECT entity_type, COUNT(*) AS cnt
                    FROM kg_entities
                    WHERE profile_id = ? AND user_uuid = ?
                    GROUP BY entity_type
                    """,
                    (pid, user_uuid),
                ).fetchall()
                entity_types = {r["entity_type"]: r["cnt"] for r in type_rows}

                # Relationship type breakdown
                rel_type_rows = conn.execute(
                    """
                    SELECT relationship_type, COUNT(*) AS cnt
                    FROM kg_relationships
                    WHERE profile_id = ? AND user_uuid = ?
                    GROUP BY relationship_type
                    """,
                    (pid, user_uuid),
                ).fetchall()
                relationship_types = {r["relationship_type"]: r["cnt"] for r in rel_type_rows}

                results.append({
                    "profile_id": pid,
                    "total_entities": row["entity_count"],
                    "total_relationships": rel_count,
                    "entity_types": entity_types,
                    "relationship_types": relationship_types,
                    "first_created": row["first_created"],
                    "last_updated": row["last_updated"],
                })

            return results
        finally:
            conn.close()
