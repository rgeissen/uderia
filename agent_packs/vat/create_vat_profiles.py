#!/usr/bin/env python3
"""
Create VAT (Virtual Account Team) profiles on the Uderia platform.

Creates:
  - 9 rag_focused sub-profiles (one per SME expert / knowledge collection)
  - 1 genie coordinator profile that routes to all 9 experts

Uses the collection mapping produced by import_vat_to_uderia.py to link
each sub-profile to its knowledge repository.

Usage:
    python agent_packs/vat/create_vat_profiles.py [--base-url http://localhost:5050]

Prerequisites:
    - Uderia server running
    - Collections already imported (collection_mapping.json exists)
    - At least one LLM configuration set as default
"""

import argparse
import json
import sys
from pathlib import Path

import requests


# Expert definitions: maps corpus name to profile metadata
EXPERTS = [
    {
        "corpus": "Product_Corpus",
        "tag": "PRODUCT_SME",
        "name": "Product Expert",
        "description": "Expert for the Teradata Vantage Platform capabilities, features, architecture, and technical specifications. Covers VantageCloud, deployment options, and platform evolution.",
    },
    {
        "corpus": "Sales_Corpus",
        "tag": "SALES_SME",
        "name": "Sales Advisor",
        "description": "Expert for advising Teradata Sales Representatives on strategies, positioning, account approaches, and go-to-market tactics.",
    },
    {
        "corpus": "UseCases_Corpus",
        "tag": "UCS_SME",
        "name": "Use Cases Expert",
        "description": "Expert for Teradata Use Cases, customer references, and solutions across industries including retail, finance, healthcare, and manufacturing.",
    },
    {
        "corpus": "CTF_Corpus",
        "tag": "CTF_SME",
        "name": "Competitive Expert",
        "description": "Expert for competitive differentiation and positioning against alternatives like Snowflake, Databricks, and other analytics platforms.",
    },
    {
        "corpus": "AIF_Corpus",
        "tag": "AIF_SME",
        "name": "AI Studio Expert",
        "description": "Expert for Teradata AI Factory and Teradata AI Studio platform capabilities, deployment, integration, and AI/ML workflows.",
    },
    {
        "corpus": "DS_Corpus",
        "tag": "DS_SME",
        "name": "Data Science Expert",
        "description": "Expert for Data Science use case patterns, analytical frameworks, model deployment, and advanced analytics methodologies.",
    },
    {
        "corpus": "Delivery_Corpus",
        "tag": "DEL_SME",
        "name": "Delivery Expert",
        "description": "Expert for Delivery, professional services, implementation methodologies, and customer success practices.",
    },
    {
        "corpus": "EVS_Corpus",
        "tag": "EVS_SME",
        "name": "Agentic Expert",
        "description": "Expert for Enterprise Vector Store, MCP integration, Agent Builder, and RAG capabilities within the Teradata ecosystem.",
    },
    {
        "corpus": "CSA_Corpus",
        "tag": "CSA_SME",
        "name": "Analytics Expert",
        "description": "Expert for ClearScape Analytics features, functions, and capabilities for in-database analytics.",
    },
]

# Synthesis prompt matching the original VAT application's "Principal Analyst" role
VAT_SYNTHESIS_PROMPT = """You are a Principal Analyst at Teradata, an expert in synthesizing information into high-quality, client-facing documents. Your task is to create a polished response to the user's request using the provided raw context snippets.

**CRITICAL INSTRUCTIONS:**
1.  **Analyze the User's Goal:** First, understand the core objective of the user's query.
2.  **Filter for Relevance:** You MUST ignore any snippets that do not directly relate to the user's specific request.
3.  **Extract Key Facts:** From the relevant context, extract the most important facts, figures, and talking points.
4.  **Synthesize and Structure:** Write a comprehensive, well-structured answer that directly fulfills the user's request. Use clear headings, bullet points, and bold text (Markdown).
5.  **Cite Your Sources:** Create a numbered list of the unique 'Source' documents you used. As you write, cite information using numeric footnotes corresponding to your reference list (e.g., `[1]`, `[2]`).
6.  **Final Formatting:** At the very end of your response, you MUST add a section with the exact heading `### References`. Under this heading, paste the unique, numbered list of sources."""


def get_jwt_token(base_url: str, username: str, password: str) -> str:
    """Authenticate and return JWT token."""
    resp = requests.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"ERROR: Login failed ({resp.status_code}): {resp.text}")
        sys.exit(1)
    return resp.json()["token"]


def get_default_llm_config(base_url: str, token: str) -> str:
    """Find the default LLM configuration ID."""
    resp = requests.get(
        f"{base_url}/api/v1/llm/configurations",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"ERROR: Failed to fetch LLM configurations ({resp.status_code})")
        sys.exit(1)

    data = resp.json()
    active_id = None
    configs = []

    if isinstance(data, dict):
        active_id = data.get("active_configuration_id")
        configs = data.get("configurations", data.get("data", []))
    elif isinstance(data, list):
        configs = data

    if not configs:
        print("ERROR: No LLM configurations found. Please add one in Uderia UI first.")
        sys.exit(1)

    # Use the active configuration if available
    if active_id:
        for cfg in configs:
            if cfg.get("id") == active_id:
                print(f"  Using active LLM: {cfg.get('name', cfg.get('id'))}")
                return cfg["id"]

    # Look for one marked as default, otherwise use the first
    for cfg in configs:
        if cfg.get("is_default") or cfg.get("isDefault"):
            print(f"  Using default LLM: {cfg.get('name', cfg.get('id'))}")
            return cfg["id"]

    # Fallback to first available
    cfg = configs[0]
    print(f"  No default LLM set, using first available: {cfg.get('name', cfg.get('id'))}")
    return cfg["id"]


def create_profile(base_url: str, token: str, profile_data: dict) -> dict:
    """Create a profile via REST API."""
    resp = requests.post(
        f"{base_url}/api/v1/profiles",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=profile_data,
        timeout=30,
    )
    if resp.status_code in (200, 201):
        return resp.json()
    else:
        return {"status": "error", "message": f"HTTP {resp.status_code}: {resp.text[:300]}"}


def main():
    parser = argparse.ArgumentParser(description="Create VAT profiles on Uderia")
    parser.add_argument("--base-url", type=str, default="http://localhost:5050")
    parser.add_argument("--username", type=str, default="admin")
    parser.add_argument("--password", type=str, default="admin")
    parser.add_argument(
        "--mapping-file",
        type=str,
        default=str(Path(__file__).parent / "import_output" / "collection_mapping.json"),
        help="Path to collection_mapping.json from import step",
    )
    args = parser.parse_args()

    # Load collection mapping
    mapping_path = Path(args.mapping_file)
    if not mapping_path.exists():
        print(f"ERROR: Collection mapping not found: {mapping_path}")
        print("Run import_vat_to_uderia.py first.")
        sys.exit(1)

    with open(mapping_path) as f:
        collection_mapping = json.load(f)

    print(f"Loaded collection mapping: {len(collection_mapping)} collections")

    # Authenticate
    print(f"Authenticating as '{args.username}'...")
    token = get_jwt_token(args.base_url, args.username, args.password)

    # Get default LLM configuration
    print("Finding default LLM configuration...")
    llm_config_id = get_default_llm_config(args.base_url, token)

    # Create sub-profiles
    print(f"\n{'='*60}")
    print("Creating RAG-focused sub-profiles")
    print(f"{'='*60}")

    created_profiles = {}

    for expert in EXPERTS:
        corpus = expert["corpus"]
        tag = expert["tag"]

        coll_info = collection_mapping.get(corpus)
        if not coll_info or "error" in coll_info:
            print(f"\n  SKIP @{tag}: collection for {corpus} not found or failed import")
            continue

        collection_id = coll_info["collection_id"]
        collection_name = coll_info.get("collection_name", corpus)

        profile_data = {
            "tag": tag,
            "name": expert["name"],
            "description": expert["description"],
            "profile_type": "rag_focused",
            "llmConfigurationId": llm_config_id,
            "knowledgeConfig": {
                "collections": [
                    {
                        "id": collection_id,
                        "name": collection_name,
                    }
                ],
                "maxDocs": 10,
                "maxTokens": 8000,
                "minRelevanceScore": 0.25,
                "maxChunksPerDocument": 2,
                "freshnessWeight": 0.3,
                "freshnessDecayRate": 0.005,
                "synthesisPromptOverride": VAT_SYNTHESIS_PROMPT,
            },
            "classification_mode": "light",
        }

        print(f"\n  Creating @{tag} ({expert['name']})...")
        result = create_profile(args.base_url, token, profile_data)

        if result.get("status") == "success" or result.get("profile"):
            profile = result.get("profile", result)
            profile_id = profile.get("id", "unknown")
            print(f"    OK: id={profile_id}")
            created_profiles[tag] = profile_id
        else:
            print(f"    FAILED: {result.get('message', result)}")

    if not created_profiles:
        print("\nERROR: No sub-profiles created. Cannot create Genie coordinator.")
        sys.exit(1)

    # Create Genie coordinator
    print(f"\n{'='*60}")
    print("Creating Genie coordinator profile")
    print(f"{'='*60}")

    genie_data = {
        "tag": "VAT",
        "name": "Virtual Account Team",
        "description": "Coordinates specialized Teradata experts to answer complex queries. Routes questions to the right subject matter expert(s) and synthesizes comprehensive answers.",
        "profile_type": "genie",
        "llmConfigurationId": llm_config_id,
        "genieConfig": {
            "slaveProfiles": list(created_profiles.values()),
            "temperature": 0.5,
            "queryTimeout": 600,
            "maxIterations": 15,
        },
        "classification_mode": "light",
    }

    print(f"\n  Creating @VAT (Virtual Account Team) with {len(created_profiles)} sub-profiles...")
    result = create_profile(args.base_url, token, genie_data)

    if result.get("status") == "success" or result.get("profile"):
        profile = result.get("profile", result)
        genie_id = profile.get("id", "unknown")
        print(f"    OK: id={genie_id}")
    else:
        print(f"    FAILED: {result.get('message', result)}")
        sys.exit(1)

    # Summary
    print(f"\n{'='*60}")
    print("PROFILE CREATION SUMMARY")
    print(f"{'='*60}")
    print(f"\n  Sub-profiles created: {len(created_profiles)}/{len(EXPERTS)}")
    for tag, pid in created_profiles.items():
        print(f"    @{tag:15s} -> {pid}")
    print(f"\n  Genie coordinator:")
    print(f"    @VAT             -> {genie_id}")
    print(f"\n  LLM configuration: {llm_config_id}")

    # Save profile mapping
    profile_mapping = {
        "sub_profiles": created_profiles,
        "genie_profile_id": genie_id,
        "llm_config_id": llm_config_id,
    }
    mapping_output = Path(args.mapping_file).parent / "profile_mapping.json"
    with open(mapping_output, 'w') as f:
        json.dump(profile_mapping, f, indent=2)
    print(f"\n  Profile mapping saved to: {mapping_output}")

    print(f"\nDone! Open Uderia and create a session with @VAT to test.")


if __name__ == "__main__":
    main()
