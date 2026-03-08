#!/usr/bin/env python3
"""
Example script demonstrating how to populate a RAG collection using the SQL template.

This script shows how to:
1. Prepare SQL examples with user queries
2. Populate an existing collection via the API
3. Verify population results

Note: For LLM-assisted question generation, use the web UI workflow:
  RAG Collections → Add Collection → Auto-Generate (LLM)

Usage:
    python example_template_population.py --collection-id 1 --database mydb
    python example_template_population.py --server http://localhost:5050 --collection-id 1
"""

import requests
import json
import sys
import argparse
from typing import List, Tuple


def populate_collection_with_sql_examples(
    base_url: str,
    collection_id: int,
    examples: List[Tuple[str, str]],
    database_name: str = None,
    mcp_tool_name: str = "base_readQuery"
):
    """
    Populate a RAG collection with SQL template examples.
    
    Args:
        base_url: Base URL of the TDA server (e.g., http://localhost:5050)
        collection_id: ID of the collection to populate
        examples: List of (user_query, sql_statement) tuples
        database_name: Optional database name for context
        mcp_tool_name: MCP tool name for SQL execution
    """
    url = f"{base_url}/api/v1/rag/collections/{collection_id}/populate"
    
    # Format examples for API
    examples_data = [
        {
            "user_query": query,
            "sql_statement": sql
        }
        for query, sql in examples
    ]
    
    payload = {
        "template_type": "sql_query",
        "examples": examples_data
    }
    
    if database_name:
        payload["database_name"] = database_name
    
    if mcp_tool_name:
        payload["mcp_tool_name"] = mcp_tool_name
    
    print(f"\n📤 Sending {len(examples)} examples to collection {collection_id}...")
    print(f"   URL: {url}")
    
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        if result.get("status") == "success":
            print(f"\n✅ Success! {result['results']['successful']} cases created")
            print(f"\n📊 Results:")
            print(f"   Total Examples: {result['results']['total_examples']}")
            print(f"   Successful: {result['results']['successful']}")
            print(f"   Failed: {result['results']['failed']}")
            
            if result['results']['case_ids']:
                print(f"\n🆔 Generated Case IDs:")
                for case_id in result['results']['case_ids']:
                    print(f"   - {case_id}")
            
            if result['results']['errors']:
                print(f"\n❌ Errors:")
                for error in result['results']['errors']:
                    print(f"   - Example {error['example_index']}: {error['error']}")
        else:
            print(f"\n❌ Error: {result.get('message', 'Unknown error')}")
            if 'validation_issues' in result:
                print(f"\n⚠️  Validation Issues:")
                for issue in result['validation_issues']:
                    print(f"   - Example {issue['example_index']} ({issue['field']}): {issue['issue']}")
        
        return result
        
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Request failed: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Populate RAG collection with SQL examples")
    parser.add_argument(
        "--server",
        default="http://localhost:5050",
        help="TDA server URL (default: http://localhost:5050)"
    )
    parser.add_argument(
        "--collection-id",
        type=int,
        required=True,
        help="Collection ID to populate"
    )
    parser.add_argument(
        "--database",
        help="Database name for context (optional)"
    )
    parser.add_argument(
        "--tool",
        default="base_readQuery",
        help="MCP tool name for SQL execution"
    )
    
    args = parser.parse_args()
    
    # Example SQL queries for a typical e-commerce database
    examples = [
        (
            "Show me all customers",
            "SELECT * FROM customers ORDER BY created_at DESC"
        ),
        (
            "Find customers by email address",
            "SELECT customer_id, name, email, phone FROM customers WHERE email LIKE '%@%.%'"
        ),
        (
            "Count total number of orders",
            "SELECT COUNT(*) as total_orders FROM orders"
        ),
        (
            "List orders by status",
            "SELECT order_id, customer_id, status, total_amount, created_at FROM orders ORDER BY created_at DESC"
        ),
        (
            "Show pending orders",
            "SELECT o.order_id, c.name as customer_name, o.total_amount, o.created_at FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE o.status = 'pending'"
        ),
        (
            "Get customer order history",
            "SELECT o.order_id, o.status, o.total_amount, o.created_at FROM orders o WHERE o.customer_id = ? ORDER BY o.created_at DESC"
        ),
        (
            "Find high-value orders over $1000",
            "SELECT order_id, customer_id, total_amount, status FROM orders WHERE total_amount > 1000 ORDER BY total_amount DESC"
        ),
        (
            "Show products with low inventory",
            "SELECT product_id, name, quantity, reorder_level FROM inventory WHERE quantity < reorder_level"
        ),
        (
            "List all product categories",
            "SELECT DISTINCT category FROM products ORDER BY category"
        ),
        (
            "Get monthly revenue",
            "SELECT DATE_FORMAT(created_at, '%Y-%m') as month, SUM(total_amount) as revenue FROM orders WHERE status = 'completed' GROUP BY month ORDER BY month DESC"
        )
    ]
    
    print("=" * 70)
    print("🚀 RAG Collection Population Example")
    print("=" * 70)
    print(f"\nServer: {args.server}")
    print(f"Collection ID: {args.collection_id}")
    print(f"Database: {args.database or 'Not specified'}")
    print(f"MCP Tool: {args.tool}")
    print(f"\nExamples to populate: {len(examples)}")
    
    # Populate the collection
    result = populate_collection_with_sql_examples(
        base_url=args.server,
        collection_id=args.collection_id,
        examples=examples,
        database_name=args.database,
        mcp_tool_name=args.tool
    )
    
    if result and result.get("status") == "success":
        print("\n" + "=" * 70)
        print("✅ Collection populated successfully!")
        print("=" * 70)
        print("\nNext steps:")
        print("1. View your collection in the TDA web UI (RAG Collections tab)")
        print("2. Enable/disable the collection as needed")
        print("3. Start querying - the agent will automatically use these examples!")
        print("\nTip: For generating many examples automatically, use the UI:")
        print("     RAG Collections → Add Collection → Auto-Generate (LLM)")
        return 0
    else:
        print("\n" + "=" * 70)
        print("❌ Population failed")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
