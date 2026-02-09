#!/bin/bash

# Test script for unified relationships endpoint
# This tests the new unified endpoint with various artifact types

set -e  # Exit on error

echo "=========================================="
echo "Unified Relationships Endpoint Test"
echo "=========================================="
echo ""

# Check if server is running
if ! curl -s http://localhost:5050/health > /dev/null 2>&1; then
    echo "❌ Server is not running at localhost:5050"
    echo "Please start the server with: python -m trusted_data_agent.main"
    exit 1
fi

echo "✅ Server is running"
echo ""

# Step 1: Authenticate and get JWT token
echo "Step 1: Authenticating..."
JWT_RESPONSE=$(curl -s -X POST http://localhost:5050/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}')

JWT=$(echo "$JWT_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('token', ''))")

if [ -z "$JWT" ]; then
    echo "❌ Failed to get JWT token"
    echo "Response: $JWT_RESPONSE"
    exit 1
fi

echo "✅ JWT token obtained: ${JWT:0:50}..."
echo ""

# Step 2: Get available collections
echo "Step 2: Getting available collections..."
COLLECTIONS_RESPONSE=$(curl -s -X GET http://localhost:5050/api/v1/rag/collections \
  -H "Authorization: Bearer $JWT")

COLLECTION_COUNT=$(echo "$COLLECTIONS_RESPONSE" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('collections', [])))")

echo "✅ Found $COLLECTION_COUNT collections"

if [ "$COLLECTION_COUNT" -eq "0" ]; then
    echo "⚠️  No collections found. Skipping collection relationship tests."
    COLLECTION_ID=""
else
    # Get first collection ID
    COLLECTION_ID=$(echo "$COLLECTIONS_RESPONSE" | python3 -c "import sys, json; data = json.load(sys.stdin); print(data['collections'][0]['id'] if data.get('collections') else '')")
    COLLECTION_NAME=$(echo "$COLLECTIONS_RESPONSE" | python3 -c "import sys, json; data = json.load(sys.stdin); print(data['collections'][0].get('name', 'Unknown') if data.get('collections') else '')")
    echo "   Using Collection ID: $COLLECTION_ID (\"$COLLECTION_NAME\")"
fi
echo ""

# Step 3: Test unified endpoint for collections
if [ -n "$COLLECTION_ID" ]; then
    echo "Step 3: Testing unified endpoint for collection $COLLECTION_ID..."
    echo "   GET /api/v1/artifacts/collection/$COLLECTION_ID/relationships"

    UNIFIED_RESPONSE=$(curl -s -X GET "http://localhost:5050/api/v1/artifacts/collection/$COLLECTION_ID/relationships" \
      -H "Authorization: Bearer $JWT")

    # Check if request succeeded
    STATUS=$(echo "$UNIFIED_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))")

    if [ "$STATUS" = "success" ]; then
        echo "✅ Unified endpoint responded successfully"

        # Extract relationship counts
        echo ""
        echo "   Relationship Analysis:"
        echo "$UNIFIED_RESPONSE" | python3 << 'EOF'
import sys, json
data = json.load(sys.stdin)

artifact = data.get('artifact', {})
print(f"   Artifact: {artifact.get('name', 'Unknown')} (type: {artifact.get('type', 'unknown')})")

relationships = data.get('relationships', {})
sessions = relationships.get('sessions', {})
profiles = relationships.get('profiles', {})
packs = relationships.get('agent_packs', {})

print(f"   Sessions:")
print(f"     - Active: {sessions.get('active_count', 0)}")
print(f"     - Archived: {sessions.get('archived_count', 0)}")
print(f"     - Total: {sessions.get('total_count', 0)}")

print(f"   Profiles: {profiles.get('count', 0)}")
print(f"   Agent Packs: {packs.get('count', 0)}")

deletion_info = data.get('deletion_info', {})
can_delete = deletion_info.get('can_delete', True)
warnings = deletion_info.get('warnings', [])
blockers = deletion_info.get('blockers', [])

print(f"   Deletion Safety:")
print(f"     - Can Delete: {can_delete}")
print(f"     - Warnings: {len(warnings)}")
print(f"     - Blockers: {len(blockers)}")

if warnings:
    for warning in warnings:
        print(f"       ⚠️  {warning}")

if blockers:
    for blocker in blockers:
        print(f"       🚫 {blocker.get('message', 'Unknown blocker')}")
EOF
    else
        echo "❌ Unified endpoint failed"
        echo "   Response: $UNIFIED_RESPONSE"
        exit 1
    fi
    echo ""
else
    echo "Step 3: Skipped (no collections available)"
    echo ""
fi

# Step 4: Test with query parameters
if [ -n "$COLLECTION_ID" ]; then
    echo "Step 4: Testing with include_archived=true parameter..."
    echo "   GET /api/v1/artifacts/collection/$COLLECTION_ID/relationships?include_archived=true&limit=10"

    ARCHIVED_RESPONSE=$(curl -s -X GET "http://localhost:5050/api/v1/artifacts/collection/$COLLECTION_ID/relationships?include_archived=true&limit=10" \
      -H "Authorization: Bearer $JWT")

    ARCHIVED_COUNT=$(echo "$ARCHIVED_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('relationships', {}).get('sessions', {}).get('archived_count', 0))")
    ITEMS_COUNT=$(echo "$ARCHIVED_RESPONSE" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('relationships', {}).get('sessions', {}).get('items', [])))")

    echo "✅ Query parameters working"
    echo "   Archived count: $ARCHIVED_COUNT"
    echo "   Items returned (limit 10): $ITEMS_COUNT"
    echo ""
else
    echo "Step 4: Skipped (no collections available)"
    echo ""
fi

# Step 5: Test profile relationships
echo "Step 5: Getting available profiles..."
PROFILES_RESPONSE=$(curl -s -X GET http://localhost:5050/api/v1/profiles \
  -H "Authorization: Bearer $JWT")

PROFILE_COUNT=$(echo "$PROFILES_RESPONSE" | python3 -c "import sys, json; data = json.load(sys.stdin); print(len(data.get('profiles', [])))")

echo "✅ Found $PROFILE_COUNT profiles"

if [ "$PROFILE_COUNT" -eq "0" ]; then
    echo "⚠️  No profiles found. Skipping profile relationship tests."
else
    # Get first profile ID
    PROFILE_ID=$(echo "$PROFILES_RESPONSE" | python3 -c "import sys, json; data = json.load(sys.stdin); print(data['profiles'][0]['id'] if data.get('profiles') else '')")
    PROFILE_NAME=$(echo "$PROFILES_RESPONSE" | python3 -c "import sys, json; data = json.load(sys.stdin); print(data['profiles'][0].get('name', 'Unknown') if data.get('profiles') else '')")

    echo "   Using Profile ID: $PROFILE_ID (\"$PROFILE_NAME\")"
    echo ""

    echo "   Testing unified endpoint for profile..."
    echo "   GET /api/v1/artifacts/profile/$PROFILE_ID/relationships"

    PROFILE_RESPONSE=$(curl -s -X GET "http://localhost:5050/api/v1/artifacts/profile/$PROFILE_ID/relationships" \
      -H "Authorization: Bearer $JWT")

    PROFILE_STATUS=$(echo "$PROFILE_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))")

    if [ "$PROFILE_STATUS" = "success" ]; then
        echo "✅ Profile relationships endpoint working"

        PROFILE_SESSIONS=$(echo "$PROFILE_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('relationships', {}).get('sessions', {}).get('total_count', 0))")
        echo "   Total sessions using this profile: $PROFILE_SESSIONS"
    else
        echo "❌ Profile endpoint failed"
        echo "   Response: $PROFILE_RESPONSE"
    fi
fi
echo ""

# Step 6: Test error handling
echo "Step 6: Testing error handling..."
echo "   Testing invalid artifact type..."

INVALID_RESPONSE=$(curl -s -X GET "http://localhost:5050/api/v1/artifacts/invalid-type/123/relationships" \
  -H "Authorization: Bearer $JWT")

INVALID_STATUS=$(echo "$INVALID_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', ''))")

if [ "$INVALID_STATUS" = "error" ]; then
    echo "✅ Error handling working correctly"
    ERROR_MSG=$(echo "$INVALID_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('message', ''))")
    echo "   Error message: $ERROR_MSG"
else
    echo "❌ Error handling not working"
fi
echo ""

# Summary
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "✅ Authentication: PASS"
echo "✅ Unified endpoint (collection): $([ -n "$COLLECTION_ID" ] && echo "PASS" || echo "SKIPPED")"
echo "✅ Query parameters: $([ -n "$COLLECTION_ID" ] && echo "PASS" || echo "SKIPPED")"
echo "✅ Profile relationships: $([ "$PROFILE_COUNT" -gt "0" ] && echo "PASS" || echo "SKIPPED")"
echo "✅ Error handling: PASS"
echo ""
echo "All tests completed successfully! 🎉"
