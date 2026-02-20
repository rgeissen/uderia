#!/usr/bin/env python3
"""
External SME MCP Tool Server - Gemini Grounded Search.

Provides a single MCP tool that searches the public internet via Google's
Gemini Grounded Search API. Designed to run as a standalone MCP server
registered in Uderia as a tool_enabled profile under the @VAT Genie coordinator.

Usage (Uderia subprocess - default):
    python external_sme_mcp_server.py

Usage (standalone HTTP server):
    python external_sme_mcp_server.py --server [--port 5003]

The server exposes one tool:
    external_search(query) -> str
"""

import argparse
import logging
import os
import sys

import httpx
from fastmcp import FastMCP

logger = logging.getLogger(__name__)

GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

mcp = FastMCP(name="external_sme")


@mcp.tool()
def external_search(query: str) -> str:
    """Search the public internet for current information about Teradata,
    competitors, or general technology topics using Gemini Grounded Search.
    Returns a factual summary with source citations."""

    api_key = GEMINI_API_KEY
    if not api_key:
        return "Error: GEMINI_API_KEY environment variable is not set."

    logger.info(f"External search query: {query[:100]}...")

    system_prompt = (
        "You are a helpful research assistant. Find public, external information "
        "related to the user's query. Provide a concise, factual summary based on "
        "public knowledge, including citations from the search tool."
    )

    api_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL_NAME}:generateContent?key={api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
    }

    try:
        response = httpx.post(
            api_url, json=payload, headers={"Content-Type": "application/json"}, timeout=30
        )
        response.raise_for_status()
        result = response.json()

        text_content = (
            result.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )

        if not text_content:
            return "Gemini Grounded Search returned an empty result."

        # Extract source citations
        sources = []
        grounding_metadata = result.get("candidates", [{}])[0].get("groundingMetadata")
        if grounding_metadata:
            attributions = grounding_metadata.get("groundingAttributions", [])
            for attr in attributions:
                web = attr.get("web", {})
                if web.get("title") and web.get("uri"):
                    sources.append(f"- [{web['title']}]({web['uri']})")

        if sources:
            text_content += "\n\n**Sources:**\n" + "\n".join(sources)

        logger.info(f"External search returned {len(text_content)} chars, {len(sources)} sources")
        return text_content

    except httpx.TimeoutException:
        logger.error("External search timed out")
        return "External search timed out. Please try again."
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.error(f"External search API error: {e}")
        return f"External search failed: {e}"
    except Exception as e:
        logger.error(f"Unexpected error in external search: {e}")
        return f"External search error: {e}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="External SME MCP Tool Server (Gemini Grounded Search)")
    parser.add_argument("--server", action="store_true", help="Run as HTTP server (default: stdio for Uderia subprocess)")
    parser.add_argument("--port", type=int, default=5003, help="Server port for --server mode (default: 5003)")
    args = parser.parse_args()

    if args.server:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
        logger.info(f"Starting External SME MCP server on port {args.port}")
        logger.info(f"Gemini model: {GEMINI_MODEL_NAME}")
        logger.info(f"API key configured: {'yes' if GEMINI_API_KEY else 'NO - set GEMINI_API_KEY env var'}")
        mcp.run("streamable-http", host="0.0.0.0", port=args.port)
    else:
        # stdio mode: logging must go to stderr (stdout is reserved for MCP protocol)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stderr)
        mcp.run("stdio")
