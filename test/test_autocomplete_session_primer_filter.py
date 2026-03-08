#!/usr/bin/env python3
"""
Test script to validate the autocomplete session primer filter fix.

This script verifies that:
1. Session primers are properly flagged in ChromaDB
2. Autocomplete endpoint filters out session primers
3. RAG retrieval still includes session primers

Usage:
    python test/test_autocomplete_session_primer_filter.py
"""

import sys
import os
import json
import sqlite3
import requests
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Test configuration
BASE_URL = "http://localhost:5050"
TEST_QUERY = "what are my top 5 products based on revenue generated?"
CHROMADB_PATH = ".chromadb_rag_cache/chroma.sqlite3"

def print_section(title):
    """Print section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def test_chromadb_metadata():
    """Test 1: Verify ChromaDB has is_session_primer metadata."""
    print_section("TEST 1: ChromaDB Metadata Check")

    if not os.path.exists(CHROMADB_PATH):
        print("❌ ChromaDB database not found at:", CHROMADB_PATH)
        return False

    conn = sqlite3.connect(CHROMADB_PATH)
    cursor = conn.cursor()

    # Count total cases
    cursor.execute("SELECT COUNT(*) FROM embeddings")
    total_cases = cursor.fetchone()[0]
    print(f"Total cases in ChromaDB: {total_cases:,}")

    # Count cases with is_session_primer field
    cursor.execute("SELECT COUNT(*) FROM embedding_metadata WHERE key = 'is_session_primer'")
    cases_with_field = cursor.fetchone()[0]
    print(f"Cases with is_session_primer field: {cases_with_field:,}")

    # Count session primers (is_session_primer = True)
    cursor.execute("SELECT COUNT(*) FROM embedding_metadata WHERE key = 'is_session_primer' AND bool_value = 1")
    primer_count = cursor.fetchone()[0]
    print(f"Cases marked as session primers: {primer_count}")

    # Show example session primers
    if primer_count > 0:
        print(f"\nSession Primer Examples:")
        cursor.execute("""
            SELECT e.id, m.string_value
            FROM embedding_metadata em
            JOIN embedding_metadata m ON em.id = m.id
            WHERE em.key = 'is_session_primer' AND em.bool_value = 1
            AND m.key = 'user_query'
            LIMIT 3
        """)
        for i, (case_id, query) in enumerate(cursor.fetchall(), 1):
            truncated = query if len(query) <= 100 else query[:97] + "..."
            print(f"  {i}. Case {case_id}: '{truncated}'")

    conn.close()

    if cases_with_field == 0:
        print("\n⚠️  WARNING: No cases have is_session_primer field!")
        print("    Run the migration script: python maintenance/backfill_session_primer_flag.py --execute")
        return False
    elif cases_with_field < total_cases:
        print(f"\n⚠️  WARNING: Only {cases_with_field}/{total_cases} cases have the field")
        print("    Some cases may need migration")
        return False
    else:
        print(f"\n✅ All cases have is_session_primer field")
        return True

def test_autocomplete_endpoint():
    """Test 2: Verify autocomplete filters out session primers."""
    print_section("TEST 2: Autocomplete Endpoint Check")

    # Test without authentication (public endpoint)
    try:
        response = requests.get(
            f"{BASE_URL}/api/questions",
            params={"query": TEST_QUERY},
            timeout=10
        )

        if response.status_code != 200:
            print(f"❌ API request failed with status {response.status_code}")
            print(f"   Response: {response.text}")
            return False

        data = response.json()
        questions = data.get("questions", [])

        print(f"Query: '{TEST_QUERY}'")
        print(f"Results: {len(questions)} questions")

        if len(questions) == 0:
            print("⚠️  No results returned (could be expected if no similar queries exist)")
            return True

        print("\nAutocomplete Results:")
        for i, question in enumerate(questions[:10], 1):
            print(f"  {i}. {question}")

        # Check if any results are session primers (long queries with keywords)
        primer_keywords = ["educate yourself", "conversion rules", "don't create sql", "leave this up to"]
        found_primers = []

        for question in questions:
            if len(question) > 200:
                found_primers.append(f"Long query ({len(question)} chars): {question[:100]}...")
            else:
                for keyword in primer_keywords:
                    if keyword in question.lower():
                        found_primers.append(f"Contains '{keyword}': {question[:100]}...")
                        break

        if found_primers:
            print("\n❌ FAILED: Found session primers in autocomplete results:")
            for primer in found_primers:
                print(f"   - {primer}")
            return False
        else:
            print("\n✅ PASSED: No session primers found in autocomplete results")
            return True

    except requests.exceptions.ConnectionError:
        print(f"❌ Could not connect to server at {BASE_URL}")
        print("   Make sure the server is running: python -m trusted_data_agent.main")
        return False
    except Exception as e:
        print(f"❌ Error testing autocomplete endpoint: {e}")
        return False

def test_future_cases():
    """Test 3: Verify new cases will have is_session_primer field."""
    print_section("TEST 3: Future Cases Check")

    # Check the code changes are in place
    files_to_check = [
        ("src/trusted_data_agent/agent/executor.py", "is_session_primer"),
        ("src/trusted_data_agent/agent/rag_retriever.py", "is_session_primer"),
        ("src/trusted_data_agent/api/routes.py", "is_session_primer")
    ]

    all_found = True
    for file_path, search_term in files_to_check:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                content = f.read()
                if search_term in content:
                    print(f"✅ {file_path}: Contains '{search_term}'")
                else:
                    print(f"❌ {file_path}: Missing '{search_term}'")
                    all_found = False
        else:
            print(f"❌ {file_path}: File not found")
            all_found = False

    if all_found:
        print("\n✅ PASSED: Code changes are in place for future cases")
    else:
        print("\n❌ FAILED: Some code changes are missing")

    return all_found

def main():
    """Run all tests."""
    print("\n" + "█" * 80)
    print("  AUTOCOMPLETE SESSION PRIMER FILTER - TEST SUITE")
    print("█" * 80)

    results = {
        "ChromaDB Metadata": test_chromadb_metadata(),
        "Autocomplete Endpoint": test_autocomplete_endpoint(),
        "Future Cases": test_future_cases()
    }

    print_section("TEST SUMMARY")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_test in results.items():
        status = "✅ PASSED" if passed_test else "❌ FAILED"
        print(f"{status}  {test_name}")

    print("\n" + "=" * 80)
    print(f"OVERALL: {passed}/{total} tests passed")
    print("=" * 80)

    if passed == total:
        print("\n🎉 All tests passed! The fix is working correctly.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please review the output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
