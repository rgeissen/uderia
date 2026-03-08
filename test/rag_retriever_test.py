import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

# Adjust the path to import RAGRetriever correctly
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "trusted_data_agent" / "agent"))

from rag_retriever import RAGRetriever

# Define paths relative to the test file
TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent
RAG_CASES_TEST_DIR = PROJECT_ROOT / "rag" / "tda_rag_cases"
PERSIST_TEST_DIR = PROJECT_ROOT / ".chromadb_test_cache"

# Ensure test directories exist
RAG_CASES_TEST_DIR.mkdir(parents=True, exist_ok=True)
PERSIST_TEST_DIR.mkdir(parents=True, exist_ok=True)

# Helper function to create dummy RAG case files
def create_dummy_rag_case(case_id: str, user_query: str, strategy_type: str, phases: list = None, error_summary: str = None, is_most_efficient: bool = False):
    case_data = {
        "case_id": case_id,
        "metadata": {
            "session_id": f"session_{case_id}",
            "turn_id": 1,
            "is_success": strategy_type == "successful",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "is_most_efficient": is_most_efficient
        },
        "intent": {"user_query": user_query}
    }
    if strategy_type == "successful":
        case_data["successful_strategy"] = {"phases": phases if phases else [{"phase": 1, "goal": "dummy", "tool": "dummy_tool"}]}
    elif strategy_type == "failed":
        case_data["failed_strategy"] = {"error_summary": error_summary if error_summary else "dummy error"}
    elif strategy_type == "conversational":
        case_data["conversational_response"] = {"summary": "dummy conversation"}

    file_path = RAG_CASES_TEST_DIR / f"{case_id}.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(case_data, f, indent=2)
    return file_path

@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown_rag_cases():
    # Clear and create dummy cases before tests
    for f in RAG_CASES_TEST_DIR.glob("case_*.json"):
        os.remove(f)
    
    create_dummy_rag_case("case_1", "list all tables in database 'test_db'", "successful", phases=[{"phase": 1, "goal": "list tables", "tool": "base_tableList"}])
    create_dummy_rag_case("case_2", "show me the columns of 'users' table", "successful", phases=[{"phase": 1, "goal": "describe columns", "tool": "base_columnDescription"}])
    create_dummy_rag_case("case_3", "what is the schema of 'orders' table", "successful", phases=[{"phase": 1, "goal": "get schema", "tool": "base_tableDDL"}])
    create_dummy_rag_case("case_4", "how many rows in 'products' table", "successful", phases=[{"phase": 1, "goal": "count rows", "tool": "base_rowCount"}])
    create_dummy_rag_case("case_5", "tell me a joke", "conversational")
    create_dummy_rag_case("case_6", "list tables in 'non_existent_db'", "failed", error_summary="Database not found")
    create_dummy_rag_case("case_5d2f685f-7467-5864-b22a-82d9b4d7ffcd", "how many databases are on the system?", "successful", is_most_efficient=True)

    yield # Run tests

    # Clean up after tests (only dummy files, not persist_test_dir)
    for f in RAG_CASES_TEST_DIR.glob("case_*.json"):
        os.remove(f)

import uuid
@pytest.fixture(scope="function")
def rag_retriever_instance():
    # Use a unique persist directory for each test function to avoid conflicts
    unique_persist_dir = PERSIST_TEST_DIR / str(uuid.uuid4())
    unique_persist_dir.mkdir(parents=True, exist_ok=True)

    retriever = RAGRetriever(
        rag_cases_dir=RAG_CASES_TEST_DIR,
        persist_directory=unique_persist_dir
    )
    # Ensure the collection is empty before each test
    retriever.collection.delete(ids=retriever.collection.get()["ids"])
    retriever.refresh_vector_store() # Reload cases into the fresh collection

    yield retriever

    # Clean up the unique persist directory after the test
    if unique_persist_dir.exists():
        import shutil
        shutil.rmtree(unique_persist_dir)

def test_rag_retriever_initialization(rag_retriever_instance):
    assert rag_retriever_instance is not None
    assert rag_retriever_instance.collection.count() >= 4 # At least successful cases

def test_rag_retriever_loads_cases_correctly(rag_retriever_instance):
    # Check if documents are added to the collection
    results = rag_retriever_instance.collection.get(ids=["case_1", "case_2", "case_3", "case_4", "case_5", "case_6", "case_5d2f685f-7467-5864-b22a-82d9b4d7ffcd"])
    assert len(results["ids"]) == 7
    assert "list all tables in database 'test_db'" in results["metadatas"][0]["user_query"]
    assert "successful" in results["metadatas"][0]["strategy_type"]

def test_rag_retriever_retrieves_relevant_successful_examples(rag_retriever_instance):
    query = "show me all the tables in my database"
    examples = rag_retriever_instance.retrieve_examples(query, k=1, min_score=0.0)
    assert len(examples) == 1
    assert examples[0]["case_id"] == "case_1"
    assert "list all tables" in examples[0]["user_query"]

def test_rag_retriever_retrieves_multiple_examples(rag_retriever_instance):
    query = "show me the schema or DDL for tables"
    examples = rag_retriever_instance.retrieve_examples(query, k=2, min_score=0.0)
    assert len(examples) == 2
    # Check for presence of expected case IDs, order is not guaranteed
    case_ids = {ex["case_id"] for ex in examples}
    assert "case_2" in case_ids
    assert "case_3" in case_ids

def test_rag_retriever_filters_for_successful_cases(rag_retriever_instance):
    query = "tell me a funny story, but only if you have a successful strategy for it" # Even more distinct query
    examples = rag_retriever_instance.retrieve_examples(query, k=1)
    assert len(examples) == 0 # Should not return conversational if filtering for successful

def test_rag_retriever_filters_out_non_successful_cases(rag_retriever_instance):
    query = "tell me a joke"
    examples = rag_retriever_instance.retrieve_examples(query, k=1)
    assert len(examples) == 0 # Should not return conversational if filtering for successful

def test_rag_retriever_retrieves_most_efficient_case(rag_retriever_instance):
    query = "how many databases are on the system?"
    examples = rag_retriever_instance.retrieve_examples(query, k=1, min_score=0.0)
    assert len(examples) == 1
    assert examples[0]["case_id"] == "case_5d2f685f-7467-5864-b22a-82d9b4d7ffcd"
    assert examples[0]["full_case_data"]["metadata"]["is_most_efficient"] is True

# Removed test_rag_retriever_format_few_shot_example as it tests a private method directly.

def test_rag_retriever_handles_no_cases_found(rag_retriever_instance):
    # Ensure the collection is truly empty for this test
    rag_retriever_instance.collection.delete(ids=rag_retriever_instance.collection.get()["ids"])
    assert rag_retriever_instance.collection.count() == 0
    
    query = "any query"
    examples = rag_retriever_instance.retrieve_examples(query, k=1)
    assert len(examples) == 0
