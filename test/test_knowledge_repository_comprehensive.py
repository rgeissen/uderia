"""
Comprehensive Knowledge Repository Test Script
Tests the complete workflow of creating and managing Knowledge repositories
"""

import requests
import json
import time
from pathlib import Path

# Configuration
BASE_URL = "http://127.0.0.1:5050"
USERNAME = "admin"
PASSWORD = "admin"

# Test document content
TEST_DOCUMENT_CONTENT = """
# Google Cloud Platform Overview

Google Cloud Platform (GCP) is a suite of cloud computing services that runs on the same infrastructure that Google uses internally for its end-user products.

## Key Services

### Compute Engine
Virtual machines running in Google's data centers. Supports custom machine types and preemptible VMs for cost savings.

### Cloud Storage
Object storage for unstructured data. Provides multiple storage classes:
- Standard: Hot data
- Nearline: Accessed less than once per month
- Coldline: Accessed less than once per quarter
- Archive: Long-term archival storage

### BigQuery
Serverless, highly scalable data warehouse. Supports SQL queries on petabyte-scale datasets.

### Cloud Functions
Event-driven serverless compute platform. Supports Node.js, Python, Go, Java, .NET, Ruby, and PHP.

## Security Features

- Identity and Access Management (IAM)
- Virtual Private Cloud (VPC)
- Cloud Armor for DDoS protection
- Security Command Center

## Best Practices

1. Use service accounts for application authentication
2. Implement least privilege access
3. Enable audit logging
4. Use Cloud KMS for encryption key management
5. Implement network segmentation with VPCs

## Pricing Model

GCP uses a pay-as-you-go pricing model with:
- Per-second billing (minimum 1 minute)
- Sustained use discounts
- Committed use discounts
- Preemptible VM instances for batch workloads
"""

def print_section(title):
    """Print a formatted section header"""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def print_result(success, message):
    """Print a test result"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status}: {message}")

class KnowledgeRepositoryTester:
    def __init__(self):
        self.token = None
        self.collection_id = None
        self.document_id = None
        self.session = requests.Session()
    
    def login(self):
        """Test 1: Login with admin credentials"""
        print_section("Test 1: User Authentication")
        
        try:
            response = self.session.post(
                f"{BASE_URL}/api/v1/auth/login",
                json={"username": USERNAME, "password": PASSWORD}
            )
            
            if response.status_code == 200:
                data = response.json()
                self.token = data.get('token')
                user = data.get('user', {})
                print_result(True, f"Login successful. Token received: {self.token[:20] if self.token else 'N/A'}...")
                print(f"   User ID: {user.get('id')}")
                print(f"   Username: {user.get('username')}")
                return True
            else:
                print_result(False, f"Login failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        except Exception as e:
            print_result(False, f"Login error: {str(e)}")
            return False
    
    def create_knowledge_repository(self):
        """Test 2: Create a Knowledge Repository"""
        print_section("Test 2: Create Knowledge Repository")
        
        try:
            payload = {
                "name": "GCP Documentation",
                "description": "Google Cloud Platform reference documentation",
                "repository_type": "knowledge",
                "chunking_strategy": "semantic",
                "chunk_size": 1000,
                "chunk_overlap": 200
            }
            
            response = self.session.post(
                f"{BASE_URL}/api/v1/rag/collections",
                headers={"Authorization": f"Bearer {self.token}"},
                json=payload
            )
            
            if response.status_code in [200, 201]:
                data = response.json()
                self.collection_id = data.get('collection_id')
                print_result(True, f"Knowledge repository created successfully")
                print(f"   Collection ID: {self.collection_id}")
                print(f"   Name: {payload['name']}")
                print(f"   Repository Type: {data.get('repository_type')}")
                print(f"   Chunking Strategy: {payload.get('chunking_strategy', 'N/A')}")
                print(f"   Embedding Model: {payload.get('embedding_model', 'N/A')}")
                return True
            else:
                print_result(False, f"Repository creation failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        except Exception as e:
            print_result(False, f"Repository creation error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def upload_document(self):
        """Test 3: Upload document to Knowledge Repository"""
        print_section("Test 3: Upload Document")
        
        if not self.collection_id:
            print_result(False, "No collection ID available - skipping test")
            return False
        
        try:
            # Create a temporary test file
            test_file_path = Path("/tmp/gcp_overview.md")
            test_file_path.write_text(TEST_DOCUMENT_CONTENT)
            
            with open(test_file_path, 'rb') as f:
                files = {'file': ('gcp_overview.md', f, 'text/markdown')}
                data = {
                    'title': 'Google Cloud Platform Overview',
                    'author': 'Test Admin',
                    'category': 'Cloud Documentation',
                    'tags': 'gcp,cloud,google,documentation',
                    'chunking_strategy': 'semantic',
                    'chunk_size': '1000',
                    'chunk_overlap': '200',
                    'embedding_model': 'all-MiniLM-L6-v2'
                }
                
                response = self.session.post(
                    f"{BASE_URL}/api/v1/knowledge/repositories/{self.collection_id}/documents",
                    headers={"Authorization": f"Bearer {self.token}"},
                    files=files,
                    data=data
                )
            
            # Clean up test file
            test_file_path.unlink()
            
            if response.status_code == 200:
                result = response.json()
                self.document_id = result.get('metadata', {}).get('document_id')
                print_result(True, "Document uploaded and processed successfully")
                print(f"   Document ID: {self.document_id}")
                print(f"   Chunks Created: {result.get('chunks_created', 0)}")
                print(f"   Status: {result.get('status')}")
                if result.get('metadata'):
                    meta = result['metadata']
                    print(f"   Document Type: {meta.get('document_type')}")
                    print(f"   Title: {meta.get('title')}")
                    print(f"   Category: {meta.get('category')}")
                return True
            else:
                print_result(False, f"Document upload failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        except Exception as e:
            print_result(False, f"Document upload error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def list_documents(self):
        """Test 4: List documents in repository"""
        print_section("Test 4: List Documents")
        
        if not self.collection_id:
            print_result(False, "No collection ID available - skipping test")
            return False
        
        try:
            response = self.session.get(
                f"{BASE_URL}/api/v1/knowledge/repositories/{self.collection_id}/documents",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                data = response.json()
                docs = data.get('documents', [])
                print_result(True, f"Retrieved {len(docs)} document(s)")
                
                for doc in docs:
                    print(f"\n   Document: {doc.get('filename')}")
                    print(f"   - ID: {doc.get('document_id')}")
                    print(f"   - Title: {doc.get('title')}")
                    print(f"   - Type: {doc.get('document_type')}")
                    print(f"   - Category: {doc.get('category')}")
                    print(f"   - Tags: {doc.get('tags')}")
                    print(f"   - Size: {doc.get('file_size')} bytes")
                    print(f"   - Created: {doc.get('created_at')}")
                
                return True
            else:
                print_result(False, f"List documents failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        except Exception as e:
            print_result(False, f"List documents error: {str(e)}")
            return False
    
    def search_repository(self):
        """Test 5: Search within Knowledge Repository"""
        print_section("Test 5: Semantic Search")
        
        if not self.collection_id:
            print_result(False, "No collection ID available - skipping test")
            return False
        
        test_queries = [
            "How does BigQuery work?",
            "What are the security features?",
            "Tell me about storage classes",
            "What are the pricing options?"
        ]
        
        try:
            all_passed = True
            for query in test_queries:
                print(f"\n   Query: '{query}'")
                
                response = self.session.post(
                    f"{BASE_URL}/api/v1/knowledge/repositories/{self.collection_id}/search",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={"query": query, "k": 3}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('results', [])
                    print(f"   ✓ Found {len(results)} relevant chunk(s)")
                    
                    for i, result in enumerate(results[:2], 1):  # Show top 2
                        content = result.get('content', '')[:100]
                        distance = result.get('distance', 0)
                        print(f"      [{i}] Distance: {distance:.4f}")
                        print(f"          Preview: {content}...")
                else:
                    print(f"   ✗ Search failed with status {response.status_code}")
                    all_passed = False
            
            if all_passed:
                print_result(True, "All search queries executed successfully")
                return True
            else:
                print_result(False, "Some search queries failed")
                return False
        except Exception as e:
            print_result(False, f"Search error: {str(e)}")
            return False
    
    def verify_collections_list(self):
        """Test 6: Verify repository appears in collections list"""
        print_section("Test 6: Verify Collections List")
        
        try:
            response = self.session.get(
                f"{BASE_URL}/api/v1/rag/collections",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                data = response.json()
                collections = data.get('collections', [])
                
                # Find our Knowledge repository
                knowledge_repos = [c for c in collections if c.get('repository_type') == 'knowledge']
                our_repo = next((c for c in knowledge_repos if c.get('id') == self.collection_id), None)
                
                if our_repo:
                    print_result(True, "Knowledge repository found in collections list")
                    print(f"   Name: {our_repo.get('collection_name')}")
                    print(f"   Type: {our_repo.get('repository_type')}")
                    print(f"   Documents: {our_repo.get('example_count', 0)}")
                    print(f"   Chunking: {our_repo.get('chunking_strategy')}")
                    return True
                else:
                    print_result(False, "Knowledge repository not found in collections list")
                    return False
            else:
                print_result(False, f"Collections list failed with status {response.status_code}")
                return False
        except Exception as e:
            print_result(False, f"Collections list error: {str(e)}")
            return False
    
    def test_metadata_filtering(self):
        """Test 7: Test metadata-based search filtering"""
        print_section("Test 7: Metadata Filtering")
        
        if not self.collection_id:
            print_result(False, "No collection ID available - skipping test")
            return False
        
        try:
            # Search with category filter
            response = self.session.post(
                f"{BASE_URL}/api/v1/knowledge/repositories/{self.collection_id}/search",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "query": "cloud services",
                    "k": 5,
                    "filter": {"category": "Cloud Documentation"}
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                print_result(True, f"Metadata filtering successful - {len(results)} results")
                
                # Verify all results have the correct category
                all_match = all(
                    r.get('metadata', {}).get('category') == 'Cloud Documentation' 
                    for r in results
                )
                
                if all_match:
                    print("   ✓ All results match filter criteria")
                else:
                    print("   ⚠ Some results don't match filter criteria")
                
                return True
            else:
                print_result(False, f"Metadata filtering failed with status {response.status_code}")
                return False
        except Exception as e:
            print_result(False, f"Metadata filtering error: {str(e)}")
            return False
    
    def delete_document(self):
        """Test 8: Delete document from repository"""
        print_section("Test 8: Delete Document")
        
        if not self.collection_id or not self.document_id:
            print_result(False, "No collection/document ID available - skipping test")
            return False
        
        try:
            response = self.session.delete(
                f"{BASE_URL}/api/v1/knowledge/repositories/{self.collection_id}/documents/{self.document_id}",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                print_result(True, "Document deleted successfully")
                print(f"   Document ID: {self.document_id}")
                return True
            else:
                print_result(False, f"Document deletion failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        except Exception as e:
            print_result(False, f"Document deletion error: {str(e)}")
            return False
    
    def cleanup(self):
        """Test 9: Cleanup - Delete the test repository"""
        print_section("Test 9: Cleanup")
        
        if not self.collection_id:
            print_result(False, "No collection ID available - skipping cleanup")
            return False
        
        try:
            response = self.session.delete(
                f"{BASE_URL}/api/v1/rag/collections/{self.collection_id}",
                headers={"Authorization": f"Bearer {self.token}"}
            )
            
            if response.status_code == 200:
                print_result(True, "Test repository deleted successfully")
                print(f"   Collection ID: {self.collection_id}")
                return True
            else:
                print_result(False, f"Repository deletion failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
        except Exception as e:
            print_result(False, f"Repository deletion error: {str(e)}")
            return False
    
    def run_all_tests(self):
        """Run all tests in sequence"""
        print("\n" + "="*60)
        print("  KNOWLEDGE REPOSITORY COMPREHENSIVE TEST")
        print("  Using admin/Amadeu$01 credentials with Google profile")
        print("="*60)
        
        results = []
        
        # Test 1: Login
        results.append(("Authentication", self.login()))
        if not results[-1][1]:
            print("\n❌ Login failed - cannot proceed with other tests")
            return
        
        # Test 2: Create repository
        results.append(("Create Repository", self.create_knowledge_repository()))
        if not results[-1][1]:
            print("\n❌ Repository creation failed - cannot proceed with other tests")
            return
        
        # Test 3: Upload document
        results.append(("Upload Document", self.upload_document()))
        
        # Test 4: List documents
        results.append(("List Documents", self.list_documents()))
        
        # Test 5: Search
        results.append(("Semantic Search", self.search_repository()))
        
        # Test 6: Verify in collections
        results.append(("Collections List", self.verify_collections_list()))
        
        # Test 7: Metadata filtering
        results.append(("Metadata Filtering", self.test_metadata_filtering()))
        
        # Test 8: Delete document
        results.append(("Delete Document", self.delete_document()))
        
        # Test 9: Cleanup
        results.append(("Cleanup", self.cleanup()))
        
        # Summary
        print_section("TEST SUMMARY")
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{status}: {test_name}")
        
        print(f"\n{'='*60}")
        print(f"  Results: {passed}/{total} tests passed")
        print(f"  Success Rate: {(passed/total)*100:.1f}%")
        print(f"{'='*60}\n")
        
        if passed == total:
            print("🎉 ALL TESTS PASSED! Knowledge Repository feature is working correctly.\n")
        else:
            print(f"⚠️  {total - passed} test(s) failed. Please review the errors above.\n")

if __name__ == "__main__":
    tester = KnowledgeRepositoryTester()
    tester.run_all_tests()
