#!/usr/bin/env python3
"""
Maintenance utility: List all RAG cases with user ownership information.
Helps identify which user owns each case and validates user attribution.

Usage:
  python3 list_rag_cases_by_user.py [--collection_id <id>] [--user_id <uuid>]
"""

import sys
import json
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional

# Add project root to path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root / "src"))

import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def list_rag_cases_by_user(rag_cases_dir: Path, collection_id: Optional[int] = None, user_id: Optional[str] = None):
    """List all RAG cases organized by user."""
    
    if not rag_cases_dir.exists():
        logger.error(f"RAG cases directory not found: {rag_cases_dir}")
        return
    
    print("\n" + "=" * 80)
    print("RAG CASES BY USER - INVENTORY")
    print("=" * 80)
    print()
    
    # Organize cases by user and collection
    cases_by_user = defaultdict(lambda: defaultdict(list))
    cases_without_user_uuid = []
    total_cases = 0
    
    # Find all case files
    if collection_id is not None:
        collection_dirs = [rag_cases_dir / f"collection_{collection_id}"]
    else:
        collection_dirs = [d for d in rag_cases_dir.iterdir() if d.is_dir() and d.name.startswith("collection_")]
    
    for collection_dir in sorted(collection_dirs):
        if not collection_dir.exists():
            continue
        
        coll_id = int(collection_dir.name.split("_")[1])
        case_files = list(collection_dir.glob("case_*.json"))
        
        for case_file in sorted(case_files):
            try:
                with open(case_file, 'r', encoding='utf-8') as f:
                    case_data = json.load(f)
                
                total_cases += 1
                metadata = case_data.get("metadata", {})
                case_user_uuid = metadata.get("user_uuid")
                case_query = metadata.get("user_query", "")[:50]
                
                if case_user_uuid:
                    cases_by_user[case_user_uuid][coll_id].append({
                        "case_id": case_file.stem,
                        "query": case_query,
                        "strategy_type": metadata.get("strategy_type"),
                        "is_most_efficient": metadata.get("is_most_efficient", False)
                    })
                else:
                    cases_without_user_uuid.append({
                        "case_id": case_file.stem,
                        "collection_id": coll_id,
                        "query": case_query
                    })
            except Exception as e:
                logger.warning(f"Error reading {case_file}: {e}")
    
    # Filter by user_id if specified
    if user_id:
        cases_by_user = {k: v for k, v in cases_by_user.items() if k == user_id}
    
    # Print results
    if not cases_by_user and not cases_without_user_uuid:
        print("No cases found.")
        print()
        return
    
    # Cases with user_uuid
    if cases_by_user:
        print(f"Cases with User Attribution: {sum(len(colls) for colls in cases_by_user.values())}")
        print("-" * 80)
        
        for user_uuid in sorted(cases_by_user.keys()):
            collections_dict = cases_by_user[user_uuid]
            user_case_count = sum(len(cases) for cases in collections_dict.values())
            print(f"\n  User: {user_uuid}")
            print(f"  Total cases: {user_case_count}")
            
            for coll_id in sorted(collections_dict.keys()):
                cases = collections_dict[coll_id]
                print(f"    Collection {coll_id}: {len(cases)} case(s)")
                
                for case in sorted(cases, key=lambda c: c["case_id"])[:3]:  # Show first 3
                    efficient = "✓" if case["is_most_efficient"] else " "
                    print(f"      [{efficient}] {case['case_id']}: {case['query']}")
                
                if len(cases) > 3:
                    print(f"      ... and {len(cases) - 3} more")
    
    # Cases without user_uuid (need migration)
    if cases_without_user_uuid:
        print(f"\n⚠ Cases WITHOUT User Attribution: {len(cases_without_user_uuid)}")
        print("-" * 80)
        print("These cases need to be attributed to users:")
        
        for case in sorted(cases_without_user_uuid, key=lambda c: c["case_id"])[:5]:
            print(f"  {case['case_id']} (Collection {case['collection_id']}): {case['query']}")
        
        if len(cases_without_user_uuid) > 5:
            print(f"  ... and {len(cases_without_user_uuid) - 5} more")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total cases: {total_cases}")
    print(f"  With user_uuid: {total_cases - len(cases_without_user_uuid)}")
    print(f"  Without user_uuid: {len(cases_without_user_uuid)}")
    print(f"Unique users: {len(cases_by_user)}")
    print()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="List RAG cases organized by user")
    parser.add_argument("--collection_id", type=int, help="Filter by collection ID")
    parser.add_argument("--user_id", help="Filter by user UUID")
    
    args = parser.parse_args()
    
    rag_cases_dir = project_root / "rag" / "tda_rag_cases"
    list_rag_cases_by_user(rag_cases_dir, args.collection_id, args.user_id)


if __name__ == "__main__":
    main()
