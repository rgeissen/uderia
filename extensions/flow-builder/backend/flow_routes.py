"""
Flow Builder REST API routes.
Runs on port 5051, authenticates via Uderia JWT tokens.
"""

import asyncio
import json
import logging
from functools import wraps
from typing import Optional

import httpx
from quart import Blueprint, request, jsonify, Response

from database import init_database
from flow_manager import flow_manager
from flow_executor import FlowExecutor

logger = logging.getLogger(__name__)

# Blueprint for flow routes
flow_bp = Blueprint("flows", __name__)

# Configuration
UDERIA_BASE_URL = "http://localhost:5050"


def get_uderia_url() -> str:
    """Get Uderia base URL from request or default."""
    return request.headers.get("X-Uderia-URL", UDERIA_BASE_URL)


def get_user_id() -> str:
    """Get user ID from request context (handles both 'id' and 'user_uuid' fields)."""
    return request.user.get("id") or request.user.get("user_uuid")


async def validate_jwt(token: str) -> Optional[dict]:
    """Validate JWT by calling Uderia's /api/v1/auth/me endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{get_uderia_url()}/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"}
            )
            if resp.status_code == 200:
                data = resp.json()
                # Uderia returns {"status": "success", "user": {...}}
                # Extract the user object
                if data.get("status") == "success" and "user" in data:
                    return data["user"]
                return data  # Fallback for unexpected format
            logger.warning(f"JWT validation failed with status {resp.status_code}")
            return None
    except Exception as e:
        logger.error(f"JWT validation error: {e}")
        return None


def require_auth(f):
    """Decorator to require JWT authentication."""
    @wraps(f)
    async def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401

        token = auth_header[7:]  # Remove "Bearer " prefix
        user_info = await validate_jwt(token)

        if not user_info:
            return jsonify({"error": "Invalid or expired token"}), 401

        # Store user info in request context
        request.user = user_info
        request.jwt_token = token
        return await f(*args, **kwargs)

    return decorated


# ==================== Flow CRUD ====================

@flow_bp.route("/flows", methods=["POST"])
@require_auth
async def create_flow():
    """Create a new flow."""
    data = await request.get_json()

    if not data:
        return jsonify({"error": "Request body required"}), 400

    name = data.get("name")
    if not name:
        return jsonify({"error": "Flow name is required"}), 400

    definition = data.get("definition", {"nodes": [], "edges": []})
    description = data.get("description")
    uderia_url = data.get("uderia_base_url", get_uderia_url())

    flow = await flow_manager.create_flow(
        user_uuid=get_user_id(),
        name=name,
        definition=definition,
        description=description,
        uderia_base_url=uderia_url
    )

    return jsonify(flow), 201


@flow_bp.route("/flows", methods=["GET"])
@require_auth
async def list_flows():
    """List all flows for the current user."""
    try:
        status = request.args.get("status")
        flows = await flow_manager.list_flows(
            user_uuid=get_user_id(),
            status=status
        )
        return jsonify({"flows": flows})
    except Exception as e:
        logger.exception(f"Error listing flows: {e}")
        return jsonify({"error": str(e)}), 500


@flow_bp.route("/flows/<flow_id>", methods=["GET"])
@require_auth
async def get_flow(flow_id: str):
    """Get a flow by ID."""
    flow = await flow_manager.get_flow(flow_id, get_user_id())
    if not flow:
        return jsonify({"error": "Flow not found"}), 404
    return jsonify(flow)


@flow_bp.route("/flows/<flow_id>", methods=["PUT"])
@require_auth
async def update_flow(flow_id: str):
    """Update a flow."""
    data = await request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    flow = await flow_manager.update_flow(
        flow_id=flow_id,
        user_uuid=get_user_id(),
        name=data.get("name"),
        description=data.get("description"),
        definition=data.get("definition"),
        status=data.get("status")
    )

    if not flow:
        return jsonify({"error": "Flow not found"}), 404

    return jsonify(flow)


@flow_bp.route("/flows/<flow_id>", methods=["DELETE"])
@require_auth
async def delete_flow(flow_id: str):
    """Delete a flow."""
    deleted = await flow_manager.delete_flow(flow_id, get_user_id())
    if not deleted:
        return jsonify({"error": "Flow not found"}), 404
    return jsonify({"success": True, "message": "Flow deleted"})


@flow_bp.route("/flows/<flow_id>/duplicate", methods=["POST"])
@require_auth
async def duplicate_flow(flow_id: str):
    """Duplicate a flow."""
    data = await request.get_json() or {}
    new_name = data.get("name")

    flow = await flow_manager.duplicate_flow(flow_id, get_user_id(), new_name)
    if not flow:
        return jsonify({"error": "Flow not found"}), 404

    return jsonify(flow), 201


@flow_bp.route("/flows/<flow_id>/validate", methods=["POST"])
@require_auth
async def validate_flow(flow_id: str):
    """Validate a flow definition."""
    result = await flow_manager.validate_flow(flow_id, get_user_id())
    return jsonify(result)


# ==================== Flow Execution ====================

@flow_bp.route("/flows/<flow_id>/execute", methods=["POST"])
@require_auth
async def execute_flow(flow_id: str):
    """Start flow execution."""
    data = await request.get_json() or {}
    input_query = data.get("input", "")

    # Get flow
    flow = await flow_manager.get_flow(flow_id, get_user_id())
    if not flow:
        return jsonify({"error": "Flow not found"}), 404

    # Create execution record
    execution = await flow_manager.create_execution(
        flow_id=flow_id,
        user_uuid=get_user_id(),
        input_data={"query": input_query}
    )

    # Return execution ID immediately
    # Actual execution happens via SSE stream
    return jsonify({
        "execution_id": execution["id"],
        "status": "running",
        "stream_url": f"/api/v1/flow-executions/{execution['id']}/stream"
    }), 202


@flow_bp.route("/flow-executions/<execution_id>", methods=["GET"])
@require_auth
async def get_execution(execution_id: str):
    """Get execution status."""
    execution = await flow_manager.get_execution(execution_id)
    if not execution:
        return jsonify({"error": "Execution not found"}), 404

    # Include node executions
    node_executions = await flow_manager.get_node_executions(execution_id)

    return jsonify({
        **execution,
        "node_executions": node_executions
    })


@flow_bp.route("/flow-executions/<execution_id>/stream", methods=["GET"])
@require_auth
async def stream_execution(execution_id: str):
    """SSE stream for real-time execution updates."""
    execution = await flow_manager.get_execution(execution_id)
    if not execution:
        return jsonify({"error": "Execution not found"}), 404

    # Get flow definition
    flow = await flow_manager.get_flow(execution["flow_id"], get_user_id())
    if not flow:
        return jsonify({"error": "Flow not found"}), 404

    async def generate():
        """Generate SSE events from flow execution."""
        executor = FlowExecutor(
            uderia_base_url=flow.get("uderia_base_url", get_uderia_url()),
            jwt_token=request.jwt_token
        )

        try:
            async for event in executor.execute_flow(
                flow_definition=flow["definition"],
                execution_id=execution_id,
                initial_input=execution.get("input", {}).get("query", "")
            ):
                # Format as SSE
                event_json = json.dumps(event)
                yield f"event: {event.get('event', 'message')}\n"
                yield f"data: {event_json}\n\n"

                # Store event in database for replay
                await flow_manager.add_execution_event(
                    execution_id=execution_id,
                    event_type=event.get("event", "unknown"),
                    event_data=event
                )

        except Exception as e:
            logger.exception(f"Error in flow execution: {e}")
            error_event = json.dumps({
                "event": "flow_execution_error",
                "error": str(e)
            })
            yield f"event: error\n"
            yield f"data: {error_event}\n\n"

        finally:
            await executor.close()
            yield "event: done\n"
            yield "data: {}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@flow_bp.route("/flow-executions/<execution_id>/cancel", methods=["POST"])
@require_auth
async def cancel_execution(execution_id: str):
    """Cancel a running execution."""
    execution = await flow_manager.get_execution(execution_id)
    if not execution:
        return jsonify({"error": "Execution not found"}), 404

    if execution["status"] not in ("running", "paused"):
        return jsonify({"error": "Execution is not running"}), 400

    await flow_manager.update_execution(
        execution_id=execution_id,
        status="cancelled"
    )

    return jsonify({"success": True, "message": "Execution cancelled"})


@flow_bp.route("/flow-executions/<execution_id>/respond", methods=["POST"])
@require_auth
async def respond_to_human_input(execution_id: str):
    """Submit response to human-in-the-loop node."""
    data = await request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    node_id = data.get("node_id")
    response_text = data.get("response")

    if not node_id or response_text is None:
        return jsonify({"error": "node_id and response are required"}), 400

    result = await flow_manager.submit_human_response(
        execution_id=execution_id,
        node_id=node_id,
        response=response_text
    )

    if not result:
        return jsonify({"error": "No pending response request found"}), 404

    return jsonify(result)


@flow_bp.route("/flows/<flow_id>/executions", methods=["GET"])
@require_auth
async def list_executions(flow_id: str):
    """List executions for a flow."""
    limit = request.args.get("limit", 20, type=int)
    executions = await flow_manager.list_executions(
        flow_id=flow_id,
        user_uuid=get_user_id(),
        limit=limit
    )
    return jsonify({"executions": executions})


@flow_bp.route("/flow-executions/<execution_id>/events", methods=["GET"])
@require_auth
async def get_execution_events(execution_id: str):
    """Get events for an execution (for replay)."""
    since_id = request.args.get("since_id", type=int)
    events = await flow_manager.get_execution_events(
        execution_id=execution_id,
        since_id=since_id
    )
    return jsonify({"events": events})


# ==================== Templates ====================

@flow_bp.route("/flow-templates", methods=["GET"])
@require_auth
async def list_templates():
    """List available flow templates."""
    templates = await flow_manager.list_templates(include_system=True)
    return jsonify({"templates": templates})


@flow_bp.route("/flow-templates/<template_id>", methods=["GET"])
@require_auth
async def get_template(template_id: str):
    """Get a template by ID."""
    template = await flow_manager.get_template(template_id)
    if not template:
        return jsonify({"error": "Template not found"}), 404
    return jsonify(template)


@flow_bp.route("/flows/from-template", methods=["POST"])
@require_auth
async def create_flow_from_template():
    """Create a flow from a template."""
    data = await request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    template_id = data.get("template_id")
    name = data.get("name")

    if not template_id or not name:
        return jsonify({"error": "template_id and name are required"}), 400

    template = await flow_manager.get_template(template_id)
    if not template:
        return jsonify({"error": "Template not found"}), 404

    flow = await flow_manager.create_flow(
        user_uuid=get_user_id(),
        name=name,
        definition=template["definition"],
        description=data.get("description", template.get("description")),
        uderia_base_url=data.get("uderia_base_url", get_uderia_url())
    )

    return jsonify(flow), 201


# ==================== Profile Discovery (Proxy to Uderia) ====================

@flow_bp.route("/profiles", methods=["GET"])
@require_auth
async def list_profiles():
    """Proxy to Uderia to list profiles."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{get_uderia_url()}/api/v1/profiles",
                headers={"Authorization": f"Bearer {request.jwt_token}"}
            )
            resp.raise_for_status()
            return jsonify(resp.json())
    except httpx.HTTPError as e:
        logger.error(f"Error fetching profiles from Uderia: {e}")
        return jsonify({"error": "Failed to fetch profiles from Uderia"}), 502


# ==================== Health Check ====================

@flow_bp.route("/health", methods=["GET"])
async def health_check():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "flow-builder",
        "version": "1.0.0"
    })


# ==================== Initialization ====================

async def init_routes():
    """Initialize routes (database, etc.)."""
    await init_database()
    logger.info("Flow Builder routes initialized")
