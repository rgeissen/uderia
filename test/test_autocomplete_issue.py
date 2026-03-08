#!/usr/bin/env python3
"""
Test script to verify the autocomplete session primer issue.
Queries ChromaDB directly to show what results are returned for the test query.
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from trusted_data_agent.agent.rag_retriever import RAGRetriever
from trusted_data_agent.agent.rag_template_generator import RAGTemplateGenerator
from trusted_data_agent.core.config import APP_CONFIG

# Initialize RAG retriever
print("Initializing RAG retriever...")
retriever = RAGRetriever()

# Test query
test_query = "what are my top 5 products based on revenue generated?"
print(f"\nTest Query: '{test_query}'")
print("=" * 80)

# Query each collection
all_results = []
for coll_id, collection in retriever.collections.items():
    print(f"\n📦 Collection ID: {coll_id} | Name: {collection.name}")
    print("-" * 80)

    try:
        # Build where clause (same as autocomplete endpoint)
        where_clause = {"$and": [
            {"strategy_type": {"$eq": "successful"}},
            {"is_most_efficient": {"$eq": True}},
            {"user_feedback_score": {"$gte": 0}}  # Exclude downvoted cases
        ]}

        # Include template-generated cases (TEMPLATE_SESSION_ID)
        where_clause["$and"].append({
            "$or": [
                {"user_uuid": {"$eq": RAGTemplateGenerator.TEMPLATE_SESSION_ID}}
            ]
        })

        # Query with semantic search
        results = collection.query(
            query_texts=[test_query],
            n_results=10,  # Get more results for inspection
            where=where_clause,
            include=["metadatas", "distances", "documents"]
        )

        # Display results
        if results and results.get("metadatas") and results["metadatas"][0]:
            print(f"Found {len(results['metadatas'][0])} results:")

            for idx, metadata in enumerate(results["metadatas"][0]):
                distance = results["distances"][0][idx] if results.get("distances") else 0
                user_query = metadata.get("user_query", "N/A")

                # Truncate long queries for display
                display_query = user_query if len(user_query) <= 100 else user_query[:97] + "..."

                print(f"\n  Result #{idx + 1} (distance: {distance:.4f}):")
                print(f"    Query: {display_query}")
                print(f"    User UUID: {metadata.get('user_uuid', 'N/A')}")
                print(f"    Case ID: {metadata.get('case_id', 'N/A')}")
                print(f"    Strategy Type: {metadata.get('strategy_type', 'N/A')}")
                print(f"    Most Efficient: {metadata.get('is_most_efficient', 'N/A')}")
                print(f"    Feedback Score: {metadata.get('user_feedback_score', 'N/A')}")

                # Check for is_session_primer field
                if "is_session_primer" in metadata:
                    print(f"    🔍 is_session_primer: {metadata['is_session_primer']}")
                else:
                    print(f"    ⚠️  is_session_primer: MISSING (field not in metadata)")

                # Flag if this looks like a session primer
                if len(user_query) > 200 or "don't create sql" in user_query.lower() or "leave this up to" in user_query.lower():
                    print(f"    🚨 LIKELY A SESSION PRIMER (long or contains primer keywords)")

                all_results.append({
                    "collection_id": coll_id,
                    "query": user_query,
                    "distance": distance,
                    "metadata": metadata
                })
        else:
            print("  No results found in this collection")

    except Exception as e:
        print(f"  ❌ Error querying collection: {e}")

# Summary
print("\n" + "=" * 80)
print(f"📊 SUMMARY: Found {len(all_results)} total results across all collections")
print("=" * 80)

# Check if any results are missing is_session_primer field
missing_flag_count = sum(1 for r in all_results if "is_session_primer" not in r["metadata"])
print(f"\n⚠️  Results missing 'is_session_primer' field: {missing_flag_count} / {len(all_results)}")

# Check if any look like session primers
potential_primers = [
    r for r in all_results
    if len(r["query"]) > 200
    or "don't create sql" in r["query"].lower()
    or "leave this up to" in r["query"].lower()
    or "if you get a request" in r["query"].lower()
]

if potential_primers:
    print(f"\n🚨 FOUND {len(potential_primers)} POTENTIAL SESSION PRIMER(S) in results:")
    for p in potential_primers:
        truncated = p["query"] if len(p["query"]) <= 150 else p["query"][:147] + "..."
        print(f"   - Collection {p['collection_id']}: '{truncated}'")
    print("\n❌ ISSUE CONFIRMED: Session primers are appearing in autocomplete results!")
else:
    print("\n✅ No obvious session primers found (query patterns look legitimate)")

print("\n" + "=" * 80)
print("Test complete!")
