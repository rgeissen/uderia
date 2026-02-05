"""
Flow Builder Backend - Standalone Quart Application
Runs on port 5051, communicates with Uderia via REST API.
"""

import asyncio
import logging
import os
import sys

# Add backend directory to path for imports when running directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from quart import Quart
from quart_cors import cors

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create Quart app
app = Quart(__name__)

# Enable CORS for Uderia UI
app = cors(
    app,
    allow_origin=["http://localhost:5050", "http://127.0.0.1:5050"],
    allow_headers=["Authorization", "Content-Type", "X-Uderia-URL"],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_credentials=True
)

# Configuration
app.config["UDERIA_BASE_URL"] = os.environ.get("UDERIA_BASE_URL", "http://localhost:5050")
app.config["PORT"] = int(os.environ.get("FLOW_BUILDER_PORT", 5051))
app.config["HOST"] = os.environ.get("FLOW_BUILDER_HOST", "0.0.0.0")


@app.before_serving
async def startup():
    """Initialize on startup."""
    from flow_routes import init_routes
    await init_routes()
    logger.info(f"Flow Builder started on port {app.config['PORT']}")
    logger.info(f"Uderia URL: {app.config['UDERIA_BASE_URL']}")


@app.after_serving
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Flow Builder shutting down")


# Register blueprints
from flow_routes import flow_bp
app.register_blueprint(flow_bp, url_prefix="/api/v1")


# Root endpoint
@app.route("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "Flow Builder",
        "version": "1.0.0",
        "description": "Visual agent flow development for Uderia",
        "api_base": "/api/v1",
        "health": "/api/v1/health",
        "docs": {
            "flows": "/api/v1/flows",
            "templates": "/api/v1/flow-templates",
            "profiles": "/api/v1/profiles"
        }
    }


def main():
    """Run the Flow Builder server."""
    import hypercorn.asyncio
    from hypercorn.config import Config

    config = Config()
    config.bind = [f"{app.config['HOST']}:{app.config['PORT']}"]
    config.accesslog = "-"

    logger.info(f"Starting Flow Builder on {config.bind[0]}")

    asyncio.run(hypercorn.asyncio.serve(app, config))


if __name__ == "__main__":
    # Allow running directly
    main()
