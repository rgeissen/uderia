# Test Scripts Audit - Orphaned and Obsolete Tests

**Date:** 5 December 2025  
**Branch:** Consumption-Profile-Activation

## Summary

Identified test scripts by category:
- **DEBUGGING**: One-off debugging scripts for specific issues (completed)
- **PHASE TESTS**: Multi-phase feature implementation tests (completed)
- **OBSOLETE**: Tests for features that have been refactored or superseded
- **ACTIVE**: Current integration/unit tests that should be kept

---

## 🗑️ SCRIPTS TO DELETE (28 scripts)

### Debugging/One-Off Tests (7 scripts)
1. **debug_sessions.py** - Simple session structure debugging (one-off)
2. **test_db_direct.py** - Direct database debugging (one-off)
3. **view_classification.py** - View profile classification (debugging utility)
4. **verify_profile_tags.py** - Profile tag verification (one-off validation)
5. **test_direct_session_creation.py** - Direct session creation test (one-off)
6. **test_pdf_creation.py** - Quick PDF creation test (one-off)
7. **validate_chunking_methods.py** - Chunking validation (one-off)

### Chart/MCP Server Tests (3 scripts)
8. **chart_server_test_sse.py** - SSE transport test
9. **chart_server_test_stdio.py** - STDIO transport test  
10. **chart_server_test_streamable.py** - Streamable test

### Phase-Based Tests (Completed Features) (14 scripts)
11. **test_phase1_multi_user_rag.py** - Phase 1: Multi-user RAG (completed)
12. **test_phase3_autocomplete.py** - Phase 3: Autocomplete (completed)
13. **test_phase4_integration.py** - Phase 4: Integration (completed)
14. **test_phase5_endpoint_security.py** - Phase 5: Security (completed)
15. **test_knowledge_repositories_phase1.py** - Knowledge repos phase 1 (completed)
16. **test_knowledge_repositories_phase2.py** - Knowledge repos phase 2 (completed)
17. **test_knowledge_repositories_phase3.py** - Knowledge repos phase 3 (completed)
18. **test_knowledge_repositories_phase4.py** - Knowledge repos phase 4 (completed)
19. **test_knowledge_repositories_phase5.py** - Knowledge repos phase 5 (completed)
20. **test_marketplace_phase2.py** - Marketplace phase 2 (completed)
21. **test_marketplace_phase3.py** - Marketplace phase 3 (completed)

### Document Upload Tests (Old/Superseded) (4 scripts)
22. **test_document_upload_config_db.py** - Old config test
23. **test_document_upload_e2e.py** - Old e2e test
24. **test_document_upload_integration.py** - Old integration test
25. **test_document_upload_template_integration.py** - Old template integration test

### Profile Badge Tests (Feature Stabilized) (3 scripts)
26. **test_profile_badges.py** - Profile badges test (feature stable)
27. **test_profile_badges_after_restart.py** - Restart test (feature stable)
28. **test_profile_badges_ui.py** - UI test (feature stable)

---

## ⚠️ SCRIPTS TO REVIEW (5 scripts)

### Session/Profile Tests
29. **test_session_creation_methods.py** + **.sh** - May still be useful for validation
30. **test_profile_override.py** - Profile override functionality (still relevant?)
31. **test_profile_override_per_message.py** - Per-message override (still relevant?)
32. **test_profile_storage.py** - Profile storage (may be useful)

### AWS/Provider Tests
33. **aws_bedrock_test.py** - AWS Bedrock integration test (keep if using AWS)

---

## ✅ SCRIPTS TO KEEP (Active Tests)

### Integration Tests
- **test_access_tokens.py** + **run_access_token_tests.sh** - Active JWT/token testing
- **test_rest_api_jwt.py** - REST API authentication testing
- **test_consumption_profiles.py** - Consumption profile testing (NEW feature)
- **test_collection_db.py** - Collection database tests

### Knowledge/RAG Tests
- **test_knowledge_minimal.py** - Minimal knowledge test
- **test_knowledge_repository_comprehensive.py** - Comprehensive knowledge test
- **rag_retriever_test.py** - RAG retriever unit tests

### Document Upload (Current)
- **test_document_upload_rest_api.py** - Current REST API test

### MCP Tests
- **mcp_prompt_parameter_get.py** - MCP prompt parameter testing
- **mcp_prompt_tester.py** - MCP prompt testing utility

### Helper Scripts
- **profile_setup_helper.py** - Profile setup utility (KEEP)

### Documentation
- **INDEX.md** - Test documentation
- **JWT_VS_ACCESS_TOKEN_GUIDE.md** - JWT documentation
- **TEST_SESSION_CREATION_README.md** - Session creation docs
- **DOCUMENT_UPLOAD_TEST_RESULTS.md** - Upload test results
- **test_template_workflow.md** - Template workflow docs
- **test_marketplace_phase4_ui.md** - Marketplace UI docs

### Test Data
- **test_data/** directory - Test data files
- **knowledge_test_document.md** - Test document
- **index_web.html** - Test HTML page
- **KnowledgeRepositories/** directory

---

## Recommended Actions

### Delete 28 Obsolete Test Scripts

```bash
cd /Users/livin2rave/my_private_code/uderia/test

# Debugging/one-off tests
rm debug_sessions.py test_db_direct.py view_classification.py \
   verify_profile_tags.py test_direct_session_creation.py \
   test_pdf_creation.py validate_chunking_methods.py

# Chart/MCP server tests
rm chart_server_test_sse.py chart_server_test_stdio.py \
   chart_server_test_streamable.py

# Phase-based tests (completed features)
rm test_phase1_multi_user_rag.py test_phase3_autocomplete.py \
   test_phase4_integration.py test_phase5_endpoint_security.py \
   test_knowledge_repositories_phase1.py \
   test_knowledge_repositories_phase2.py \
   test_knowledge_repositories_phase3.py \
   test_knowledge_repositories_phase4.py \
   test_knowledge_repositories_phase5.py \
   test_marketplace_phase2.py test_marketplace_phase3.py

# Old document upload tests
rm test_document_upload_config_db.py test_document_upload_e2e.py \
   test_document_upload_integration.py \
   test_document_upload_template_integration.py

# Profile badge tests (feature stable)
rm test_profile_badges.py test_profile_badges_after_restart.py \
   test_profile_badges_ui.py
```

### Review These 5 Scripts
Before deleting, verify if still needed:
- test_session_creation_methods.py/.sh
- test_profile_override.py
- test_profile_override_per_message.py  
- test_profile_storage.py
- aws_bedrock_test.py (keep if using AWS Bedrock)

---

## Summary Statistics

- **Total test files:** ~56
- **To delete:** 28 scripts (50%)
- **To review:** 5 scripts (9%)
- **To keep:** 23+ scripts (41%)

After cleanup, test directory will contain only active, relevant tests.
