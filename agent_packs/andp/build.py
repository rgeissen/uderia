#!/usr/bin/env python3
"""
Build script for the ANDP Agent Pack.

Assembles ai-native-data-product.md from base_content.md + 6 module design standard
documents, generates skill.json and manifest.json from embedded templates, packages
the .skill and .agentpack ZIPs, and optionally imports to a running Uderia server.

Run from the uderia project root (or any directory — script resolves paths):
    python agent_packs/andp/build.py
    python agent_packs/andp/build.py --import
    python agent_packs/andp/build.py --import --url http://192.168.0.46:5050 --password ><your-password>
"""

import argparse
import json
import os
import sys
import zipfile
from datetime import date, datetime, timezone

# ── Paths ──────────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT  = os.path.dirname(os.path.dirname(_HERE))   # uderia project root

SKILL_DIR       = os.path.join(ROOT, "skills", "user", "ai-native-data-product")
SKILL_JSON_PATH = os.path.join(SKILL_DIR, "skill.json")
SKILL_MD_PATH   = os.path.join(SKILL_DIR, "ai-native-data-product.md")

PACK_DIR        = os.path.join(ROOT, "agent_packs", "andp")
PACK_SKILLS_DIR = os.path.join(PACK_DIR, "skills")
MANIFEST_PATH   = os.path.join(PACK_DIR, "manifest.json")
SKILL_ZIP_PATH  = os.path.join(PACK_SKILLS_DIR, "ai-native-data-product.skill")
AGENTPACK_PATH  = os.path.join(PACK_DIR, "andp.agentpack")

BASE_CONTENT_PATH     = os.path.join(PACK_DIR, "base_content.md")
DESIGN_STANDARDS_DIR  = os.path.join(os.path.dirname(ROOT), "ai-native-data-products", "design-standards")

MODULE_SOURCES = [
    ("memory",        os.path.join(DESIGN_STANDARDS_DIR, "Memory_Module_Design_Standard.md")),
    ("semantic",      os.path.join(DESIGN_STANDARDS_DIR, "Semantic_Module_Design_Standard.md")),
    ("domain",        os.path.join(DESIGN_STANDARDS_DIR, "Domain_Module_Design_Standard.md")),
    ("observability", os.path.join(DESIGN_STANDARDS_DIR, "Observability_Module_Design_Standard.md")),
    ("search",        os.path.join(DESIGN_STANDARDS_DIR, "Search_Module_Design_Standard.md")),
    ("prediction",    os.path.join(DESIGN_STANDARDS_DIR, "Prediction_Module_Design_Standard.md")),
]

COMPRESSED_MODULES_DIR = os.path.join(PACK_DIR, "compressed_modules")


# ── Skill manifest template ────────────────────────────────────────────────────

def build_skill_json():
    return {
        "name": "ai-native-data-product",
        "version": "1.0.0",
        "description": (
            "Design standards for AI-native data products on Teradata. "
            "Six-module architecture with DDL patterns, agent discovery protocol, "
            "and routing intelligence for the ANDP coordinator."
        ),
        "author": "Teradata Worldwide Data Architecture Team",
        "tags": ["teradata", "data-product", "design", "architecture", "ddl"],
        "keywords": [
            "ai-native", "domain", "semantic", "search",
            "prediction", "observability", "memory", "andp"
        ],
        "use_cases": [
            "Design a new data product module with production-ready DDL",
            "Generate Semantic module registration INSERTs for agent discovery",
            "Design the Memory module Documentation Sub-Module",
            "Route design queries to the correct module specialist"
        ],
        "main_file": "ai-native-data-product.md",
        "last_updated": date.today().isoformat(),
        "uderia": {
            "injection_target": "user_context",
            "icon": "database",
            "allowed_params": [
                "domain", "semantic", "search",
                "prediction", "observability", "memory"
            ],
            "param_descriptions": {
                "domain":        "Domain module: entity tables (_H, _R), temporal patterns, surrogate key strategy, standard views",
                "semantic":      "Semantic module: metadata tables, agent discovery queries, v_relationship_paths, data_product_map registration",
                "search":        "Search module: entity_embedding table, TD_VectorDistance patterns, index strategy, RAG integration",
                "prediction":    "Prediction module: feature store tables (wide/tall), model_prediction, point-in-time feature reconstruction",
                "observability": "Observability module: change_event, data_lineage/lineage_run split, data_quality_metric, model_performance",
                "memory":        "Memory module: agent state tables + Documentation Sub-Module (Module_Registry, Design_Decision, Query_Cookbook, etc.)"
            }
        }
    }


# ── Agent pack manifest template ───────────────────────────────────────────────

def _skill_cfg(param=None):
    """Return a skillsConfig entry. param=None means coordinator (base only)."""
    return {
        "skills": [
            {"id": "ai-native-data-product", "enabled": True, "active": True, "param": param}
        ]
    }


def build_manifest():
    profiles = [
        {
            "tag": "ANDP",
            "name": "AI-Native Data Product Designer",
            "description": (
                "Coordinates data product design across all 6 modules. "
                "Routes to the right specialist based on query topic."
            ),
            "profile_type": "genie",
            "role": "coordinator",
            "child_tags": [
                "ANDP-DOMAIN", "ANDP-SEMANTIC", "ANDP-SEARCH",
                "ANDP-PREDICTION", "ANDP-OBSERVABILITY", "ANDP-MEMORY"
            ],
            "genieConfig": {
                "temperature": 0.3,
                "queryTimeout": 600,
                "maxIterations": 12
            },
            "skillsConfig": _skill_cfg()          # no param → base content only
        },
        {
            "tag": "ANDP-DOMAIN",
            "name": "Domain Module Designer",
            "description": (
                "Designs Domain module DDL: entity history tables (_H), reference tables (_R), "
                "surrogate key strategy via Keymap pattern, bi-temporal tracking, standard views."
            ),
            "profile_type": "llm_only",
            "role": "expert",
            "skillsConfig": _skill_cfg("domain")
        },
        {
            "tag": "ANDP-SEMANTIC",
            "name": "Semantic Module Designer",
            "description": (
                "Designs Semantic module: entity_metadata, column_metadata, table_relationship, "
                "v_relationship_paths recursive CTE, data_product_map, agent discovery protocol."
            ),
            "profile_type": "llm_only",
            "role": "expert",
            "skillsConfig": _skill_cfg("semantic")
        },
        {
            "tag": "ANDP-SEARCH",
            "name": "Search Module Designer",
            "description": (
                "Designs Search module: entity_embedding with VECTOR datatype, "
                "TD_VectorDistance patterns, KMEANS/HNSW index strategy, RAG integration."
            ),
            "profile_type": "llm_only",
            "role": "expert",
            "skillsConfig": _skill_cfg("search")
        },
        {
            "tag": "ANDP-PREDICTION",
            "name": "Prediction Module Designer",
            "description": (
                "Designs Prediction module: feature store (wide/tall formats), model_prediction, "
                "point-in-time feature reconstruction for ML training datasets."
            ),
            "profile_type": "llm_only",
            "role": "expert",
            "skillsConfig": _skill_cfg("prediction")
        },
        {
            "tag": "ANDP-OBSERVABILITY",
            "name": "Observability Module Designer",
            "description": (
                "Designs Observability module: change_event (table-level), "
                "data_lineage/lineage_run split, data_quality_metric, model_performance, "
                "OpenLineage alignment."
            ),
            "profile_type": "llm_only",
            "role": "expert",
            "skillsConfig": _skill_cfg("observability")
        },
        {
            "tag": "ANDP-MEMORY",
            "name": "Memory Module Designer",
            "description": (
                "Designs Memory module: runtime agent state tables + full Documentation "
                "Sub-Module (Module_Registry, Design_Decision, Business_Glossary, "
                "Query_Cookbook, Implementation_Note, Change_Log)."
            ),
            "profile_type": "llm_only",
            "role": "expert",
            "skillsConfig": _skill_cfg("memory")
        }
    ]

    return {
        "format_version": "1.3",
        "name": "AI-Native Data Product Designer",
        "description": (
            "Genie coordinator + 6 module specialist slaves for designing AI-native data "
            "products on Teradata. Each slave has deep expertise in one module; the "
            "coordinator routes queries based on topic."
        ),
        "author": "Teradata Worldwide Data Architecture Team",
        "version": "1.0.0",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tags": ["teradata", "data-product", "design", "architecture", "andp"],
        "profiles": profiles,
        "collections": [],
        "skills": [
            {
                "id": "ai-native-data-product",
                "file": "skills/ai-native-data-product.skill",
                "name": "AI-Native Data Product Design Standards",
                "description": (
                    "Full design standards for all 6 modules with routing "
                    "intelligence for the ANDP coordinator."
                )
            }
        ]
    }


# ── Build steps ────────────────────────────────────────────────────────────────

def _ok(msg):    print(f"  ✓ {msg}")
def _step(msg):  print(f"  {msg}")
def _err(msg):   print(f"  ✗ {msg}", file=sys.stderr)
def _head(msg):  print(f"\n[{msg}]")


def preflight(compressed=False):
    _head("1/6  Preflight")

    if not os.path.exists(BASE_CONTENT_PATH):
        _err(f"Base content file not found: {BASE_CONTENT_PATH}")
        sys.exit(1)
    _ok(f"base_content.md")

    missing_sources = []
    for module_name, source_path in MODULE_SOURCES:
        if compressed:
            check_path = os.path.join(COMPRESSED_MODULES_DIR, f"{module_name}.md")
            label = f"compressed_modules/{module_name}.md"
        else:
            check_path = source_path
            label = os.path.basename(source_path)

        if not os.path.exists(check_path):
            missing_sources.append(f"{module_name}: {check_path}")
        else:
            lines = open(check_path).read().count("\n")
            _ok(f"{label}  ({lines:,} lines)")

    if missing_sources:
        for m in missing_sources:
            _err(f"Source document not found: {m}")
        sys.exit(1)


def build_skill_md(compressed=False):
    if compressed:
        _head("2/6  Assemble skill .md from compressed module files")
    else:
        _head("2/6  Assemble skill .md from source documents")

    with open(BASE_CONTENT_PATH, encoding="utf-8") as f:
        base = f.read().rstrip()

    parts = [base, ""]

    for module_name, source_path in MODULE_SOURCES:
        read_path = (
            os.path.join(COMPRESSED_MODULES_DIR, f"{module_name}.md")
            if compressed else source_path
        )
        with open(read_path, encoding="utf-8") as f:
            content = f.read().rstrip()
        parts.append(f"<!-- param:{module_name} -->")
        parts.append(content)
        parts.append(f"<!-- /param:{module_name} -->")
        parts.append("")

    skill_md = "\n".join(parts)

    os.makedirs(SKILL_DIR, exist_ok=True)
    with open(SKILL_MD_PATH, "w", encoding="utf-8") as f:
        f.write(skill_md)

    total_lines = skill_md.count("\n")
    _ok(f"ai-native-data-product.md  ({total_lines:,} lines total)")
    for module_name, source_path in MODULE_SOURCES:
        read_path = (
            os.path.join(COMPRESSED_MODULES_DIR, f"{module_name}.md")
            if compressed else source_path
        )
        with open(read_path, encoding="utf-8") as f:
            lines = f.read().count("\n")
        _step(f"  <!-- param:{module_name} -->  ({lines:,} lines)")


def generate_skill_files():
    _head("3/6  Generate skill.json + manifest.json")

    os.makedirs(SKILL_DIR, exist_ok=True)
    skill_data = build_skill_json()
    with open(SKILL_JSON_PATH, "w") as f:
        json.dump(skill_data, f, indent=2)
    _ok(f"skill.json  (last_updated: {skill_data['last_updated']})")

    os.makedirs(PACK_DIR, exist_ok=True)
    manifest_data = build_manifest()
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest_data, f, indent=2)
    _ok(f"manifest.json  ({len(manifest_data['profiles'])} profiles)")


def package_skill():
    _head("4/6  Package .skill zip (flat — no subdirectories)")

    os.makedirs(PACK_SKILLS_DIR, exist_ok=True)
    with zipfile.ZipFile(SKILL_ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(SKILL_JSON_PATH, "skill.json")
        zf.write(SKILL_MD_PATH,   "ai-native-data-product.md")

    size_kb = os.path.getsize(SKILL_ZIP_PATH) / 1024
    _ok(f"ai-native-data-product.skill  ({size_kb:.1f} KB)")


def package_agentpack():
    _head("5/6  Package .agentpack zip")

    with zipfile.ZipFile(AGENTPACK_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(MANIFEST_PATH,   "manifest.json")
        zf.write(SKILL_ZIP_PATH,  "skills/ai-native-data-product.skill")

    size_kb = os.path.getsize(AGENTPACK_PATH) / 1024
    _ok(f"andp.agentpack  ({size_kb:.1f} KB)")


def import_pack(uderia_url, username, password):
    _head("6/6  Import to Uderia")

    try:
        import requests
    except ImportError:
        _err("requests library not available — run: pip install requests")
        sys.exit(1)

    _step(f"Authenticating → {uderia_url}")
    try:
        r = requests.post(
            f"{uderia_url}/api/v1/auth/login",
            json={"username": username, "password": password},
            timeout=10
        )
        r.raise_for_status()
    except Exception as exc:
        _err(f"Connection failed: {exc}")
        sys.exit(1)

    token = r.json().get("token")
    if not token:
        _err(f"Login failed: {r.text}")
        sys.exit(1)
    _ok("Authenticated")

    _step("Importing andp.agentpack (conflict_strategy=replace) ...")
    with open(AGENTPACK_PATH, "rb") as f:
        r = requests.post(
            f"{uderia_url}/api/v1/agent-packs/import",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("andp.agentpack", f, "application/octet-stream")},
            data={"conflict_strategy": "replace"},
            timeout=30
        )

    try:
        result = r.json()
    except Exception:
        result = {"raw": r.text}

    if r.status_code == 200:
        profiles_n = result.get("profiles_created", result.get("profiles_imported", "?"))
        _ok(f"Import successful  (profiles: {profiles_n})")
        print(f"\n  Full response:\n{json.dumps(result, indent=4)}")
    else:
        _err(f"Import failed (HTTP {r.status_code}):\n{r.text}")
        sys.exit(1)


def skip_import(uderia_url, username, password):
    _head("6/6  Import to Uderia")
    _step("Skipped (pass --import to enable)")
    print(f"""
  To import manually:

    JWT=$(curl -s -X POST {uderia_url}/api/v1/auth/login \\
      -H 'Content-Type: application/json' \\
      -d '{{"username":"{username}","password":"<password>"}}' | jq -r '.token')

    curl -s -X POST {uderia_url}/api/v1/agent-packs/import \\
      -H "Authorization: Bearer $JWT" \\
      -F "file=@{AGENTPACK_PATH}" \\
      -F "conflict_strategy=replace" | jq '.'
""")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Build and optionally import the ANDP Agent Pack"
    )
    parser.add_argument(
        "--import", dest="do_import", action="store_true",
        help="Import the .agentpack to Uderia after building"
    )
    parser.add_argument(
        "--url", default="http://localhost:5050",
        help="Uderia server URL (default: http://localhost:5050)"
    )
    parser.add_argument("--username", default="admin", help="Uderia username (default: admin)")
    parser.add_argument("--password", default="admin", help="Uderia password (default: admin)")
    parser.add_argument(
        "--compressed", action="store_true",
        help=(
            "Use compressed module files from agent_packs/andp/compressed_modules/ "
            "instead of verbatim source documents"
        )
    )
    args = parser.parse_args()

    mode = "compressed" if args.compressed else "verbatim"
    print(f"\n══ ANDP Agent Pack Build ({mode}) ══════════════════════════════")

    preflight(compressed=args.compressed)
    build_skill_md(compressed=args.compressed)
    generate_skill_files()
    package_skill()
    package_agentpack()

    if args.do_import:
        import_pack(args.url, args.username, args.password)
    else:
        skip_import(args.url, args.username, args.password)

    print("\n══ Done ═══════════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
