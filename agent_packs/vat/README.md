# VAT Agent Pack — Import & Refresh Process

Ports the Virtual Account Team (9 SME experts) to Uderia as knowledge repositories + a Genie coordinator profile.

## Prerequisites

- Uderia server running (`python -m trusted_data_agent.main`)
- At least one LLM configuration set as active in the Uderia UI
- A default profile set (any profile type) so the server is fully initialized
- Corpus JSON files placed in `agent_packs/vat/corpus/` (9 `*_Corpus.json` files)
- Python environment with: `sentence-transformers`, `langchain-text-splitters`, `chromadb`, `requests`

## Scripts

| Script | Purpose |
|---|---|
| `import_vat_corpus.py` | Converts 9 JSON corpus files into Uderia-compatible import ZIPs with pre-computed embeddings |
| `import_vat_to_uderia.py` | Writes ZIPs directly into SQLite (`tda_auth.db`) and ChromaDB (`.chromadb_rag_cache/`) |
| `create_vat_profiles.py` | Creates 9 `rag_focused` sub-profiles + 1 `genie` coordinator (`@VAT`) via REST API |
| `cleanup_vat.py` | Removes all VAT profiles and collections (reverses the above) |

## Full Refresh (Steps 1–5)

Run from the **project root** (`uderia/`). The Uderia server must be running for steps 1, 3, and 4.

```bash
# 1. Remove previous VAT data
python agent_packs/vat/cleanup_vat.py --yes

# 2. Convert corpus to ZIPs (server not required, takes ~2 min for embeddings)
python agent_packs/vat/import_vat_corpus.py

# 3. Import collections into Uderia
python agent_packs/vat/import_vat_to_uderia.py

# 4. Create profiles
python agent_packs/vat/create_vat_profiles.py

# 5. Restart the Uderia server (required for ChromaDB to reload)
```

After restart, create a session with `@VAT` to test.

## What Gets Created

**9 Knowledge Repositories** (one per corpus):

| Collection | Tag | Docs | Chunks |
|---|---|---|---|
| VAT Product | @PRODUCT_SME | 142 | ~8,000 |
| VAT Sales | @SALES_SME | 78 | ~2,500 |
| VAT CTF | @CTF_SME | 138 | ~5,800 |
| VAT UseCases | @UCS_SME | 486 | ~4,700 |
| VAT Systems | @SYS_SME | 28 | ~1,000 |
| VAT DS | @DS_SME | 105 | ~1,600 |
| VAT Delivery | @DEL_SME | 43 | ~1,200 |
| VAT Agentic | @AGT_SME | 38 | ~1,700 |
| VAT CSA | @CSA_SME | 30 | ~800 |

**10 Profiles:**
- 9 `rag_focused` sub-profiles (one per expert, each linked to its collection)
- 1 `genie` coordinator `@VAT` that routes queries to the right expert(s)

## Output Files

All written to `agent_packs/vat/import_output/` (gitignored):

- `*_Corpus_import.zip` — 9 import ZIPs with chunks + embeddings
- `collection_mapping.json` — maps corpus names to collection IDs
- `profile_mapping.json` — maps profile tags to profile IDs
- `conversion_summary.json` — corpus conversion stats

## Options

All scripts accept `--base-url`, `--username`, and `--password`:

```bash
python agent_packs/vat/cleanup_vat.py --base-url http://localhost:5050 --username admin --password admin --yes
```

`import_vat_corpus.py` also accepts `--corpus-dir` and `--output-dir` if corpus files are elsewhere.

---

## Automated Pipeline

`pipeline.py` automates the full workflow: detect new content in CorpContent, process with corpus_tools, build agentpack, and import into Uderia.

### Setup

```bash
# 1. Copy the example config and edit paths
cp agent_packs/vat/pipeline_config.example.json agent_packs/vat/pipeline_config.json

# 2. Edit pipeline_config.json:
#    - Set corpus_python to your corpus_tools venv interpreter
#      e.g. /path/to/TheVirtualAccountTeam/venv/bin/python
#    - Verify all directory paths (no credentials in this file!)
#    - Verify all directory paths
```

### Usage

```bash
# Manual run — credentials via CLI args
python agent_packs/vat/pipeline.py --username admin --password secret

# Or via environment variables
export UDERIA_USERNAME=admin UDERIA_PASSWORD=secret
python agent_packs/vat/pipeline.py

# Force full rebuild (ignore change detection)
python agent_packs/vat/pipeline.py --force

# Dry run — detect changes only, don't process
python agent_packs/vat/pipeline.py --dry-run

# Skip corpus processing — rebuild agentpack from existing corpus JSONs
python agent_packs/vat/pipeline.py --skip-content

# Cron mode — exit silently if no changes, run pipeline if changes found
python agent_packs/vat/pipeline.py --if-changed

# Watch mode — poll for changes every hour (or custom interval)
python agent_packs/vat/pipeline.py --watch --interval 3600
```

### How It Works

1. **Detect** — compares file mtimes in CorpContent/{Category}/ against {Category}_Corpus.json
2. **Process** — runs CreateContent.py (via corpus_tools venv) for changed categories only
3. **FAISS Cache** — invalidates stale FAISS indexes in TheVirtualAccountTeam/Corpus/cache/ and rebuilds only changed categories via MCP_Tool_Server
4. **Deploy** — git commits updated corpus + cache, pushes to origin, pulls on remote production server, restarts MCP_Tool_Server Docker container
5. **Build** — runs build_agentpack.py to create vat.agentpack with embeddings
6. **Import** — POSTs to Uderia's `/api/v1/agent-packs/import` with `conflict_strategy=replace`
7. **Verify** — checks all 10 VAT profiles and 9 collections exist

### Configuration

All settings live in `pipeline_config.json`. Copy from `pipeline_config.example.json` and edit.

| Config Key | Required | Description |
|---|---|---|
| `corpcontent_dir` | Yes | Path to CorpContent directory with category subdirectories |
| `corpus_tools_dir` | Yes | Path to corpus_tools scripts (CreateContent.py etc.) |
| `corpus_output_dir` | Yes | Path to output directory for `{Category}_Corpus.json` files |
| `categories` | Yes | List of category names to process |
| `vat_project_dir` | Yes | Path to TheVirtualAccountTeam root (for FAISS cache + git) |
| `corpus_python` | Yes | Python interpreter for corpus_tools venv (e.g. conda env) |
| `deploy_ssh_host` | No | SSH host for remote deploy (e.g. `user@server`). Empty = skip deploy |
| `deploy_ssh_path` | No | Remote directory path for `git pull` |
| `deploy_docker_container` | No | Docker Compose service name to restart on remote. Empty = skip restart |
| `uderia_base_url` | No | Uderia server URL (default: `http://localhost:5050`) |
| `poll_interval_seconds` | No | Default polling interval for `--watch` mode (default: 3600) |

#### Credentials

Credentials are **never stored in config files**. Provide them at runtime via CLI or environment variables:

| Method | Example |
|---|---|
| CLI args | `--username admin --password secret --base-url http://host:5050` |
| Env vars | `UDERIA_USERNAME`, `UDERIA_PASSWORD`, `UDERIA_BASE_URL` |

Resolution order: CLI args > environment variables > config file.

#### Deploy Phase Prerequisites

The deploy phase (Phase 4) requires:
- SSH key-based access to `deploy_ssh_host` (no password prompts)
- Git remote `origin` configured in TheVirtualAccountTeam
- The remote user must be in the `docker` group for container restart

### Cron Example

```cron
# Check for new content every 2 hours (credentials via env vars)
0 */2 * * * UDERIA_USERNAME=admin UDERIA_PASSWORD=secret cd /path/to/uderia && /path/to/venv/bin/python agent_packs/vat/pipeline.py --if-changed >> /tmp/vat_pipeline_cron.log 2>&1
```

Run history is logged to `agent_packs/vat/pipeline_runs.log` (JSON lines format).
