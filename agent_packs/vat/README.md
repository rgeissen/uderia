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
| VAT Product | @PRODUCT_SME | 152 | ~8,600 |
| VAT Sales | @SALES_SME | 78 | ~2,500 |
| VAT CTF | @CTF_SME | 142 | ~6,000 |
| VAT UseCases | @UCS_SME | 493 | ~4,800 |
| VAT AIF | @AIF_SME | 30 | ~1,100 |
| VAT DS | @DS_SME | 89 | ~1,400 |
| VAT Delivery | @DEL_SME | 44 | ~1,200 |
| VAT EVS | @EVS_SME | 33 | ~1,500 |
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
