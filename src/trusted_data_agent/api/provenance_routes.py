"""
Provenance REST API Routes
===========================

Endpoints for querying and verifying Execution Provenance Chains (EPC).

Endpoints:
    GET  /api/v1/sessions/{id}/provenance              - Full provenance for all turns
    GET  /api/v1/sessions/{id}/provenance/turn/{turn}   - Single turn's chain
    POST /api/v1/sessions/{id}/provenance/verify         - Verify integrity
    GET  /api/v1/sessions/{id}/provenance/export         - Download JSON for offline audit
    GET  /api/v1/provenance/public-key                   - Download public key PEM
"""

import json
import logging

from quart import Blueprint, jsonify, request

from trusted_data_agent.auth.middleware import require_auth
from trusted_data_agent.core import session_manager

app_logger = logging.getLogger("quart.app")

provenance_bp = Blueprint('provenance', __name__)


def _get_turn_provenance(turn_data: dict) -> dict:
    """Extract provenance data from a turn."""
    chain = turn_data.get("provenance_chain")
    meta = turn_data.get("provenance_meta")
    if not chain and not meta:
        return None
    return {"provenance_chain": chain or [], "provenance_meta": meta or {}}


@provenance_bp.route('/api/v1/sessions/<session_id>/provenance', methods=['GET'])
@require_auth
async def get_session_provenance(current_user, session_id):
    """Get provenance data for all turns in a session."""
    user_uuid = current_user.id if current_user else None

    session_data = await session_manager.get_session(user_uuid, session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    last_turn = session_data.get("last_turn_data", {})
    workflow_history = last_turn.get("workflow_history", [])

    turns = []
    for turn in workflow_history:
        prov = _get_turn_provenance(turn)
        turns.append({
            "turn": turn.get("turn"),
            "profile_type": turn.get("profile_type"),
            "status": turn.get("status"),
            "provenance": prov
        })

    return jsonify({
        "session_id": session_id,
        "turns": turns,
        "total_turns": len(turns),
        "turns_with_provenance": sum(1 for t in turns if t["provenance"])
    })


@provenance_bp.route('/api/v1/sessions/<session_id>/provenance/turn/<int:turn_number>', methods=['GET'])
@require_auth
async def get_turn_provenance(current_user, session_id, turn_number):
    """Get provenance data for a specific turn."""
    user_uuid = current_user.id if current_user else None

    session_data = await session_manager.get_session(user_uuid, session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    last_turn = session_data.get("last_turn_data", {})
    workflow_history = last_turn.get("workflow_history", [])

    for turn in workflow_history:
        if turn.get("turn") == turn_number:
            prov = _get_turn_provenance(turn)
            if not prov:
                return jsonify({
                    "session_id": session_id,
                    "turn": turn_number,
                    "provenance": None,
                    "message": "No provenance data for this turn"
                })
            return jsonify({
                "session_id": session_id,
                "turn": turn_number,
                "provenance": prov
            })

    return jsonify({"error": f"Turn {turn_number} not found"}), 404


@provenance_bp.route('/api/v1/sessions/<session_id>/provenance/verify', methods=['POST'])
@require_auth
async def verify_session_provenance(current_user, session_id):
    """Verify provenance integrity for a session (L1 chain + L3 cross-turn)."""
    user_uuid = current_user.id if current_user else None

    try:
        from trusted_data_agent.core.provenance import verify_chain, verify_session

        # Level 3: Full session verification (includes L1 per-turn)
        session_result = await verify_session(user_uuid, session_id)

        return jsonify({
            "session_id": session_id,
            "verification": session_result
        })
    except Exception as e:
        app_logger.error(f"Provenance verification error: {e}", exc_info=True)
        return jsonify({"error": f"Verification failed: {str(e)}"}), 500


@provenance_bp.route('/api/v1/sessions/<session_id>/provenance/export', methods=['GET'])
@require_auth
async def export_session_provenance(current_user, session_id):
    """Export provenance data as downloadable JSON for offline audit."""
    user_uuid = current_user.id if current_user else None

    session_data = await session_manager.get_session(user_uuid, session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    last_turn = session_data.get("last_turn_data", {})
    workflow_history = last_turn.get("workflow_history", [])

    try:
        from trusted_data_agent.core.provenance import get_provenance_public_key_pem, get_key_fingerprint

        export_data = {
            "export_version": 1,
            "session_id": session_id,
            "public_key_pem": get_provenance_public_key_pem().decode('utf-8') if get_provenance_public_key_pem() else None,
            "key_fingerprint": get_key_fingerprint(),
            "turns": []
        }

        for turn in workflow_history:
            prov = _get_turn_provenance(turn)
            if prov:
                export_data["turns"].append({
                    "turn": turn.get("turn"),
                    "user_query": turn.get("user_query", ""),
                    "profile_type": turn.get("profile_type"),
                    "status": turn.get("status"),
                    "provenance_chain": prov.get("provenance_chain", []),
                    "provenance_meta": prov.get("provenance_meta", {})
                })

        response = await jsonify(export_data).get_data()
        from quart import Response
        return Response(
            response,
            mimetype='application/json',
            headers={
                'Content-Disposition': f'attachment; filename=provenance_{session_id}.json'
            }
        )
    except Exception as e:
        app_logger.error(f"Provenance export error: {e}", exc_info=True)
        return jsonify({"error": f"Export failed: {str(e)}"}), 500


@provenance_bp.route('/api/v1/provenance/public-key', methods=['GET'])
@require_auth
async def get_public_key(current_user):
    """Download the provenance public key PEM for offline verification."""
    try:
        from trusted_data_agent.core.provenance import get_provenance_public_key_pem, get_key_fingerprint

        pub_pem = get_provenance_public_key_pem()
        if not pub_pem:
            return jsonify({"error": "Provenance key not available"}), 503

        return jsonify({
            "public_key_pem": pub_pem.decode('utf-8'),
            "key_fingerprint": get_key_fingerprint(),
            "algorithm": "Ed25519"
        })
    except Exception as e:
        app_logger.error(f"Public key retrieval error: {e}", exc_info=True)
        return jsonify({"error": f"Failed to retrieve public key: {str(e)}"}), 500
