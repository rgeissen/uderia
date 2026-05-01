"""
Connector REST routes (Track C).

Generic routes — platform is a path parameter derived from the connector registry.
Adding a new connector requires only:
  1. Create src/trusted_data_agent/connectors/<name>_connector.py
  2. Register it in connectors/registry.py

Endpoints:
  GET  /api/v1/connectors/{platform}/auth      — initiate OAuth flow
  GET  /api/v1/connectors/{platform}/callback  — OAuth callback (redirect from provider)
  GET  /api/v1/connectors/{platform}/status    — connection status for current user
  DELETE /api/v1/connectors/{platform}/connection — disconnect and revoke tokens

The google callback is also registered at its legacy path for Google Cloud Console
redirect URI compatibility (changing that URL requires re-verifying the app).
"""

import logging
import os

from quart import Blueprint, jsonify, redirect, request

from trusted_data_agent.auth.middleware import require_auth

logger = logging.getLogger("quart.app")

connector_bp = Blueprint("connector_routes", __name__)


def _redirect_uri(platform: str) -> str:
    base = os.getenv("APP_BASE_URL", "http://localhost:5050").rstrip("/")
    return f"{base}/api/v1/connectors/{platform}/callback"


def _get_connector(platform: str):
    """Return the connector module for *platform*, or None."""
    from trusted_data_agent.connectors.registry import get as _get
    return _get(platform)


# ── Initiate OAuth ────────────────────────────────────────────────────────────

@connector_bp.route("/api/v1/connectors/<platform>/auth", methods=["GET"])
@require_auth
async def connector_auth(user, platform: str):
    """Return OAuth authorization URL for the current user."""
    mod = _get_connector(platform)
    if mod is None:
        return jsonify({"error": f"Unknown connector platform: {platform}"}), 404

    if not mod.is_configured():
        return jsonify({
            "error": f"{platform.title()} connector not configured. Ask an admin to set credentials "
                     f"under Admin Panel → Connectors → uderia-{platform}."
        }), 503

    auth_url = mod.initiate_oauth(user.id, _redirect_uri(platform))
    if not auth_url:
        return jsonify({"error": "Failed to generate authorization URL."}), 500

    return jsonify({"auth_url": auth_url})


# ── OAuth callback ────────────────────────────────────────────────────────────

@connector_bp.route("/api/v1/connectors/<platform>/callback", methods=["GET"])
async def connector_callback(platform: str):
    """
    Handle OAuth callback. Exchanges code for tokens, stores them,
    then renders a small HTML page that closes the popup and notifies the opener.
    """
    mod = _get_connector(platform)
    if mod is None:
        return _oauth_result_page(
            platform=platform, success=False,
            message=f"Unknown connector platform: {platform}"
        )

    code = request.args.get("code", "")
    state = request.args.get("state", "")
    error = request.args.get("error", "")

    if error:
        return _oauth_result_page(
            platform=platform, success=False,
            message=f"{platform.title()} authorization denied: {error}"
        )

    if not code or not state:
        return _oauth_result_page(
            platform=platform, success=False,
            message="Missing code or state parameter."
        )

    result = await mod.handle_callback(code, state, _redirect_uri(platform))
    if not result:
        return _oauth_result_page(
            platform=platform, success=False,
            message="Token exchange failed. Check server logs."
        )

    email = result.get("email", "")
    return _oauth_result_page(platform=platform, success=True, email=email)


# ── Status ────────────────────────────────────────────────────────────────────

@connector_bp.route("/api/v1/connectors/<platform>/status", methods=["GET"])
@require_auth
async def connector_status(user, platform: str):
    """Return connection status for the current user."""
    mod = _get_connector(platform)
    if mod is None:
        return jsonify({"error": f"Unknown connector platform: {platform}"}), 404

    status = mod.get_connection_status(user.id)
    return jsonify(status)


# ── Disconnect ────────────────────────────────────────────────────────────────

@connector_bp.route("/api/v1/connectors/<platform>/connection", methods=["DELETE"])
@require_auth
async def connector_disconnect(user, platform: str):
    """Revoke tokens and disconnect the account."""
    mod = _get_connector(platform)
    if mod is None:
        return jsonify({"error": f"Unknown connector platform: {platform}"}), 404

    await mod.disconnect(user.id)
    return jsonify({"disconnected": True})


# ── HTML result page ──────────────────────────────────────────────────────────

def _oauth_result_page(
    platform: str,
    success: bool,
    email: str = "",
    message: str = "",
) -> str:
    """
    Minimal HTML page shown after OAuth callback.
    Posts a message to the opener window so the Platform Components panel
    can refresh the connector card without a full page reload.
    """
    display = platform.title()

    if success:
        title = f"{display} Account Connected"
        icon = "✓"
        color = "#34d399"
        body_msg = f"Connected as <strong>{email}</strong>. You can close this window."
        js_payload = f'{{"type":"{platform}_oauth_success","email":"{email}"}}'
    else:
        title = f"{display} Authorization Failed"
        icon = "✗"
        color = "#f87171"
        body_msg = message or "Authorization failed. You can close this window."
        js_payload = f'{{"type":"{platform}_oauth_error"}}'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; margin: 0;
    }}
    .card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 12px;
      padding: 2rem 2.5rem;
      text-align: center;
      max-width: 400px;
    }}
    .icon {{ font-size: 3rem; color: {color}; }}
    h2 {{ margin: 0.5rem 0; color: {color}; }}
    p {{ color: #94a3b8; margin: 0.5rem 0; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h2>{title}</h2>
    <p>{body_msg}</p>
  </div>
  <script>
    (function() {{
      try {{
        if (window.opener) {{
          window.opener.postMessage({js_payload}, '*');
          setTimeout(function() {{ window.close(); }}, 1500);
        }}
      }} catch(e) {{}}
    }})();
  </script>
</body>
</html>"""
    from quart import Response
    return Response(html, content_type="text/html")
