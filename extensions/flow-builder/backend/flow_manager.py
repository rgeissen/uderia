"""
Flow Manager - Handles persistence of flows and executions.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4

from database import get_db_connection
from flow_graph import FlowGraph

logger = logging.getLogger(__name__)


def generate_id(prefix: str = "flow") -> str:
    """Generate a unique ID with prefix."""
    return f"{prefix}-{uuid4().hex[:12]}"


class FlowManager:
    """Manages flow CRUD operations and execution tracking."""

    # ==================== Flow CRUD ====================

    async def create_flow(
        self,
        user_uuid: str,
        name: str,
        definition: dict,
        description: str = None,
        uderia_base_url: str = "http://localhost:5050"
    ) -> dict:
        """Create a new flow."""
        flow_id = generate_id("flow")

        async with get_db_connection() as db:
            await db.execute(
                """
                INSERT INTO flows (id, user_uuid, name, description, definition, uderia_base_url)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (flow_id, user_uuid, name, description, json.dumps(definition), uderia_base_url)
            )
            await db.commit()

        logger.info(f"Created flow {flow_id} for user {user_uuid}")
        return await self.get_flow(flow_id, user_uuid)

    async def get_flow(self, flow_id: str, user_uuid: str) -> Optional[dict]:
        """Get a flow by ID."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                "SELECT * FROM flows WHERE id = ? AND user_uuid = ?",
                (flow_id, user_uuid)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return {
                "id": row["id"],
                "user_uuid": row["user_uuid"],
                "name": row["name"],
                "description": row["description"],
                "definition": json.loads(row["definition"]),
                "uderia_base_url": row["uderia_base_url"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"]
            }

    async def list_flows(self, user_uuid: str, status: str = None) -> List[dict]:
        """List all flows for a user."""
        async with get_db_connection() as db:
            if status:
                cursor = await db.execute(
                    "SELECT * FROM flows WHERE user_uuid = ? AND status = ? ORDER BY updated_at DESC",
                    (user_uuid, status)
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM flows WHERE user_uuid = ? ORDER BY updated_at DESC",
                    (user_uuid,)
                )
            rows = await cursor.fetchall()

            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "status": row["status"],
                    "node_count": len(json.loads(row["definition"]).get("nodes", [])),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"]
                }
                for row in rows
            ]

    async def update_flow(
        self,
        flow_id: str,
        user_uuid: str,
        name: str = None,
        description: str = None,
        definition: dict = None,
        status: str = None
    ) -> Optional[dict]:
        """Update a flow."""
        updates = []
        params = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if definition is not None:
            updates.append("definition = ?")
            params.append(json.dumps(definition))
        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if not updates:
            return await self.get_flow(flow_id, user_uuid)

        updates.append("updated_at = ?")
        params.append(datetime.utcnow().isoformat())

        params.extend([flow_id, user_uuid])

        async with get_db_connection() as db:
            await db.execute(
                f"UPDATE flows SET {', '.join(updates)} WHERE id = ? AND user_uuid = ?",
                tuple(params)
            )
            await db.commit()

        logger.info(f"Updated flow {flow_id}")
        return await self.get_flow(flow_id, user_uuid)

    async def delete_flow(self, flow_id: str, user_uuid: str) -> bool:
        """Delete a flow and all its executions."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                "DELETE FROM flows WHERE id = ? AND user_uuid = ?",
                (flow_id, user_uuid)
            )
            await db.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info(f"Deleted flow {flow_id}")
        return deleted

    async def duplicate_flow(self, flow_id: str, user_uuid: str, new_name: str = None) -> Optional[dict]:
        """Create a copy of a flow."""
        original = await self.get_flow(flow_id, user_uuid)
        if not original:
            return None

        name = new_name or f"{original['name']} (Copy)"
        return await self.create_flow(
            user_uuid=user_uuid,
            name=name,
            definition=original["definition"],
            description=original["description"],
            uderia_base_url=original["uderia_base_url"]
        )

    async def validate_flow(self, flow_id: str, user_uuid: str) -> dict:
        """Validate a flow definition."""
        flow = await self.get_flow(flow_id, user_uuid)
        if not flow:
            return {"valid": False, "errors": ["Flow not found"]}

        try:
            graph = FlowGraph.from_definition(flow["definition"])
            errors = graph.validate()
            return {
                "valid": len(errors) == 0,
                "errors": errors,
                "node_count": len(graph.nodes),
                "edge_count": len(graph.edges)
            }
        except Exception as e:
            return {"valid": False, "errors": [str(e)]}

    # ==================== Execution Tracking ====================

    async def create_execution(
        self,
        flow_id: str,
        user_uuid: str,
        input_data: Any = None
    ) -> dict:
        """Create a new flow execution record."""
        execution_id = generate_id("exec")

        async with get_db_connection() as db:
            await db.execute(
                """
                INSERT INTO flow_executions (id, flow_id, user_uuid, status, input_json)
                VALUES (?, ?, ?, 'running', ?)
                """,
                (execution_id, flow_id, user_uuid, json.dumps(input_data) if input_data else None)
            )
            await db.commit()

        logger.info(f"Created execution {execution_id} for flow {flow_id}")
        return await self.get_execution(execution_id)

    async def get_execution(self, execution_id: str) -> Optional[dict]:
        """Get an execution by ID."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                "SELECT * FROM flow_executions WHERE id = ?",
                (execution_id,)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return {
                "id": row["id"],
                "flow_id": row["flow_id"],
                "user_uuid": row["user_uuid"],
                "status": row["status"],
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "input": json.loads(row["input_json"]) if row["input_json"] else None,
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "token_usage": json.loads(row["token_usage_json"]) if row["token_usage_json"] else None,
                "uderia_sessions": json.loads(row["uderia_sessions_json"]) if row["uderia_sessions_json"] else None,
                "error_message": row["error_message"]
            }

    async def list_executions(self, flow_id: str, user_uuid: str, limit: int = 20) -> List[dict]:
        """List executions for a flow."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                """
                SELECT id, flow_id, status, started_at, completed_at, error_message
                FROM flow_executions
                WHERE flow_id = ? AND user_uuid = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (flow_id, user_uuid, limit)
            )
            rows = await cursor.fetchall()

            return [
                {
                    "id": row["id"],
                    "flow_id": row["flow_id"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "error_message": row["error_message"]
                }
                for row in rows
            ]

    async def update_execution(
        self,
        execution_id: str,
        status: str = None,
        result: Any = None,
        token_usage: dict = None,
        uderia_sessions: list = None,
        error_message: str = None
    ) -> Optional[dict]:
        """Update an execution record."""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status in ("completed", "failed", "cancelled"):
                updates.append("completed_at = ?")
                params.append(datetime.utcnow().isoformat())
        if result is not None:
            updates.append("result_json = ?")
            params.append(json.dumps(result))
        if token_usage is not None:
            updates.append("token_usage_json = ?")
            params.append(json.dumps(token_usage))
        if uderia_sessions is not None:
            updates.append("uderia_sessions_json = ?")
            params.append(json.dumps(uderia_sessions))
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        if not updates:
            return await self.get_execution(execution_id)

        params.append(execution_id)

        async with get_db_connection() as db:
            await db.execute(
                f"UPDATE flow_executions SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )
            await db.commit()

        return await self.get_execution(execution_id)

    # ==================== Node Execution Tracking ====================

    async def create_node_execution(
        self,
        execution_id: str,
        node_id: str,
        node_type: str,
        node_label: str = None,
        input_data: Any = None
    ) -> dict:
        """Create a node execution record."""
        node_exec_id = generate_id("node")

        async with get_db_connection() as db:
            await db.execute(
                """
                INSERT INTO flow_node_executions
                (id, execution_id, node_id, node_type, node_label, status, input_json, started_at)
                VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (node_exec_id, execution_id, node_id, node_type, node_label,
                 json.dumps(input_data) if input_data else None, datetime.utcnow().isoformat())
            )
            await db.commit()

        return {
            "id": node_exec_id,
            "execution_id": execution_id,
            "node_id": node_id,
            "node_type": node_type,
            "node_label": node_label,
            "status": "running"
        }

    async def update_node_execution(
        self,
        node_exec_id: str,
        status: str = None,
        output: Any = None,
        uderia_session_id: str = None,
        uderia_task_id: str = None,
        error_message: str = None,
        duration_ms: int = None
    ) -> None:
        """Update a node execution record."""
        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status in ("completed", "failed", "skipped"):
                updates.append("completed_at = ?")
                params.append(datetime.utcnow().isoformat())
        if output is not None:
            updates.append("output_json = ?")
            params.append(json.dumps(output))
        if uderia_session_id is not None:
            updates.append("uderia_session_id = ?")
            params.append(uderia_session_id)
        if uderia_task_id is not None:
            updates.append("uderia_task_id = ?")
            params.append(uderia_task_id)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        if duration_ms is not None:
            updates.append("duration_ms = ?")
            params.append(duration_ms)

        if not updates:
            return

        params.append(node_exec_id)

        async with get_db_connection() as db:
            await db.execute(
                f"UPDATE flow_node_executions SET {', '.join(updates)} WHERE id = ?",
                tuple(params)
            )
            await db.commit()

    async def get_node_executions(self, execution_id: str) -> List[dict]:
        """Get all node executions for a flow execution."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                """
                SELECT * FROM flow_node_executions
                WHERE execution_id = ?
                ORDER BY started_at
                """,
                (execution_id,)
            )
            rows = await cursor.fetchall()

            return [
                {
                    "id": row["id"],
                    "execution_id": row["execution_id"],
                    "node_id": row["node_id"],
                    "node_type": row["node_type"],
                    "node_label": row["node_label"],
                    "status": row["status"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                    "input": json.loads(row["input_json"]) if row["input_json"] else None,
                    "output": json.loads(row["output_json"]) if row["output_json"] else None,
                    "uderia_session_id": row["uderia_session_id"],
                    "uderia_task_id": row["uderia_task_id"],
                    "error_message": row["error_message"],
                    "duration_ms": row["duration_ms"]
                }
                for row in rows
            ]

    # ==================== Execution Events ====================

    async def add_execution_event(
        self,
        execution_id: str,
        event_type: str,
        event_data: dict
    ) -> None:
        """Add an event to the execution event log."""
        async with get_db_connection() as db:
            await db.execute(
                """
                INSERT INTO flow_execution_events (execution_id, event_type, event_data)
                VALUES (?, ?, ?)
                """,
                (execution_id, event_type, json.dumps(event_data))
            )
            await db.commit()

    async def get_execution_events(
        self,
        execution_id: str,
        since_id: int = None
    ) -> List[dict]:
        """Get execution events, optionally since a specific event ID."""
        async with get_db_connection() as db:
            if since_id:
                cursor = await db.execute(
                    """
                    SELECT * FROM flow_execution_events
                    WHERE execution_id = ? AND id > ?
                    ORDER BY id
                    """,
                    (execution_id, since_id)
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT * FROM flow_execution_events
                    WHERE execution_id = ?
                    ORDER BY id
                    """,
                    (execution_id,)
                )
            rows = await cursor.fetchall()

            return [
                {
                    "id": row["id"],
                    "execution_id": row["execution_id"],
                    "event_type": row["event_type"],
                    "event_data": json.loads(row["event_data"]),
                    "created_at": row["created_at"]
                }
                for row in rows
            ]

    # ==================== Human-in-the-Loop ====================

    async def create_human_response_request(
        self,
        execution_id: str,
        node_id: str,
        prompt: str,
        input_type: str = "text",
        choices: list = None,
        timeout_seconds: int = 3600
    ) -> dict:
        """Create a pending human response request."""
        response_id = generate_id("human")
        timeout_at = datetime.utcnow().timestamp() + timeout_seconds

        async with get_db_connection() as db:
            await db.execute(
                """
                INSERT INTO flow_human_responses
                (id, execution_id, node_id, prompt, input_type, choices_json, timeout_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime(?, 'unixepoch'))
                """,
                (response_id, execution_id, node_id, prompt, input_type,
                 json.dumps(choices) if choices else None, timeout_at)
            )
            await db.commit()

        return {
            "id": response_id,
            "execution_id": execution_id,
            "node_id": node_id,
            "prompt": prompt,
            "input_type": input_type,
            "choices": choices,
            "status": "pending"
        }

    async def submit_human_response(
        self,
        execution_id: str,
        node_id: str,
        response: str
    ) -> Optional[dict]:
        """Submit a human response."""
        async with get_db_connection() as db:
            await db.execute(
                """
                UPDATE flow_human_responses
                SET response = ?, responded_at = ?, status = 'responded'
                WHERE execution_id = ? AND node_id = ? AND status = 'pending'
                """,
                (response, datetime.utcnow().isoformat(), execution_id, node_id)
            )
            await db.commit()

            cursor = await db.execute(
                "SELECT * FROM flow_human_responses WHERE execution_id = ? AND node_id = ?",
                (execution_id, node_id)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return {
                "id": row["id"],
                "response": row["response"],
                "responded_at": row["responded_at"],
                "status": row["status"]
            }

    async def get_pending_human_response(
        self,
        execution_id: str,
        node_id: str
    ) -> Optional[dict]:
        """Get a pending human response request."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                """
                SELECT * FROM flow_human_responses
                WHERE execution_id = ? AND node_id = ? AND status = 'pending'
                """,
                (execution_id, node_id)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return {
                "id": row["id"],
                "prompt": row["prompt"],
                "input_type": row["input_type"],
                "choices": json.loads(row["choices_json"]) if row["choices_json"] else None,
                "response": row["response"],
                "status": row["status"]
            }

    # ==================== Templates ====================

    async def list_templates(self, include_system: bool = True) -> List[dict]:
        """List available flow templates."""
        async with get_db_connection() as db:
            if include_system:
                cursor = await db.execute(
                    "SELECT * FROM flow_templates ORDER BY is_system DESC, name"
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM flow_templates WHERE is_system = FALSE ORDER BY name"
                )
            rows = await cursor.fetchall()

            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "category": row["category"],
                    "definition": json.loads(row["definition"]),
                    "icon": row["icon"],
                    "is_system": bool(row["is_system"])
                }
                for row in rows
            ]

    async def get_template(self, template_id: str) -> Optional[dict]:
        """Get a template by ID."""
        async with get_db_connection() as db:
            cursor = await db.execute(
                "SELECT * FROM flow_templates WHERE id = ?",
                (template_id,)
            )
            row = await cursor.fetchone()

            if not row:
                return None

            return {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "category": row["category"],
                "definition": json.loads(row["definition"]),
                "icon": row["icon"],
                "is_system": bool(row["is_system"])
            }


# Singleton instance
flow_manager = FlowManager()
