#!/usr/bin/env python3
"""
Identifies orphan RAG case studies that don't have associated sessions.
An orphan case is one where the session_id in the case's metadata doesn't exist in tda_sessions.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict

# Add parent directory to path to import from src
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.trusted_data_agent.agent.rag_template_generator import RAGTemplateGenerator

def find_all_sessions(sessions_dir):
    """Find all session IDs (including archived ones)."""
    session_ids = set()
    
    if not sessions_dir.exists():
        print(f"Sessions directory not found: {sessions_dir}")
        return session_ids
    
    for user_dir in sessions_dir.iterdir():
        if not user_dir.is_dir():
            continue
        
        for session_file in user_dir.glob("*.json"):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                session_ids.add(data.get('id', session_file.stem))
            except Exception as e:
                print(f"Error reading session {session_file}: {e}")
    
    return session_ids

def find_all_cases(rag_cases_dir):
    """Find all RAG cases and extract their session_id."""
    cases = []
    
    if not rag_cases_dir.exists():
        print(f"RAG cases directory not found: {rag_cases_dir}")
        return cases
    
    # Scan all collection directories
    for collection_dir in rag_cases_dir.glob("collection_*"):
        if not collection_dir.is_dir():
            continue
        
        collection_id = collection_dir.name.replace('collection_', '')
        
        for case_file in collection_dir.glob("case_*.json"):
            try:
                with open(case_file, 'r', encoding='utf-8') as f:
                    case_data = json.load(f)
                
                session_id = case_data.get('metadata', {}).get('session_id')
                if session_id:
                    cases.append({
                        'case_id': case_data.get('case_id'),
                        'session_id': session_id,
                        'collection_id': collection_id,
                        'file_path': str(case_file),
                        'turn_id': case_data.get('metadata', {}).get('turn_id'),
                        'timestamp': case_data.get('metadata', {}).get('timestamp')
                    })
            except Exception as e:
                print(f"Error reading case {case_file}: {e}")
    
    return cases

def identify_orphans(sessions_dir, rag_cases_dir):
    """Identify orphan cases."""
    print("=" * 80)
    print("ORPHAN RAG CASE STUDY IDENTIFICATION")
    print("=" * 80)
    print()
    
    # Find all sessions
    print(f"Scanning sessions in: {sessions_dir}")
    session_ids = find_all_sessions(sessions_dir)
    print(f"Found {len(session_ids)} sessions (including archived)")
    print()
    
    # Find all cases
    print(f"Scanning RAG cases in: {rag_cases_dir}")
    all_cases = find_all_cases(rag_cases_dir)
    print(f"Found {len(all_cases)} RAG cases across all collections")
    print()
    
    # Identify orphans - distinguish between deletable and preserved cases
    orphan_cases = []
    preserved_cases = []
    orphans_by_collection = defaultdict(list)
    preserved_by_collection = defaultdict(list)
    
    # Special session IDs that indicate intentional orphans (should be preserved)
    PRESERVED_SESSION_IDS = {
        RAGTemplateGenerator.TEMPLATE_SESSION_ID,  # Template-generated cases
    }
    
    for case in all_cases:
        session_id = case['session_id']
        
        # Check if session exists
        if session_id in session_ids:
            continue  # Not an orphan
        
        # Check if this is a preserved orphan (intentionally created without session)
        if session_id in PRESERVED_SESSION_IDS:
            preserved_cases.append(case)
            preserved_by_collection[case['collection_id']].append(case)
        else:
            # Real orphan - session was deleted
            orphan_cases.append(case)
            orphans_by_collection[case['collection_id']].append(case)
    
    # Report results
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    print()
    print(f"Total cases: {len(all_cases)}")
    print(f"Cases with valid sessions: {len(all_cases) - len(orphan_cases) - len(preserved_cases)}")
    print(f"Preserved cases (intentional orphans): {len(preserved_cases)}")
    print(f"Deletable orphan cases: {len(orphan_cases)}")
    print()
    
    # Report preserved cases
    if preserved_cases:
        print("PRESERVED CASES (WILL NOT BE DELETED):")
        print("-" * 80)
        for collection_id in sorted(preserved_by_collection.keys()):
            preserved = preserved_by_collection[collection_id]
            print(f"\nCollection {collection_id}: {len(preserved)} preserved cases")
            print(f"  These are intentionally created without sessions (batch population, examples, etc.)")
        print()
    
    # Report deletable orphans
    if orphan_cases:
        print("DELETABLE ORPHANS BY COLLECTION:")
        print("-" * 80)
        for collection_id in sorted(orphans_by_collection.keys()):
            orphans = orphans_by_collection[collection_id]
            print(f"\nCollection {collection_id}: {len(orphans)} deletable orphans")
            print()
            for case in orphans[:5]:  # Show first 5
                print(f"  Case ID: {case['case_id']}")
                print(f"  Session ID: {case['session_id']}")
                print(f"  Turn ID: {case['turn_id']}")
                print(f"  File: {case['file_path']}")
                print(f"  Timestamp: {case['timestamp']}")
                print()
            
            if len(orphans) > 5:
                print(f"  ... and {len(orphans) - 5} more orphans in this collection")
                print()
        
        # Provide summary
        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total deletable orphan cases: {len(orphan_cases)}")
        print(f"Total preserved cases: {len(preserved_cases)}")
        print()
        print("Reasons for deletable orphans:")
        print("  1. Session was permanently deleted (before archive feature)")
        print("  2. Session file was manually removed")
        print("  3. Session was moved to a different location")
        print("  4. Case was created but session creation failed")
        print()
        print("PRESERVED cases will NOT be deleted:")
        print(f"  - Cases with session_id='{RAGTemplateGenerator.TEMPLATE_SESSION_ID}'")
        print("  - These are template-generated examples and should remain")
        print()
        print("You can:")
        print("  - Delete only the deletable orphans to clean up")
        print("  - Keep all cases for general RAG knowledge")
    else:
        print("✓ No deletable orphan cases found!")
        if preserved_cases:
            print(f"✓ {len(preserved_cases)} preserved cases remain (intentional orphans)")
    
    print()
    return orphan_cases

if __name__ == "__main__":
    # Set up paths
    project_root = Path(__file__).resolve().parents[1]
    sessions_dir = project_root / "tda_sessions"
    rag_cases_dir = project_root / "rag" / "tda_rag_cases"
    
    # Run analysis
    orphans = identify_orphans(sessions_dir, rag_cases_dir)
    
    # Optionally export to JSON
    if orphans:
        output_file = project_root / "maintenance" / "orphan_cases.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(orphans, f, indent=2)
        print(f"Orphan details saved to: {output_file}")
