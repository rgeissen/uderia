#!/bin/bash
# Clear classification cache for @OPTIM profile

BASE_URL="http://localhost:5050"

echo "🔄 Clearing @OPTIM profile classification cache..."

# Authenticate
JWT=$(curl -s -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}' | jq -r '.token')

if [ "$JWT" == "null" ] || [ -z "$JWT" ]; then
    echo "❌ Authentication failed"
    exit 1
fi

echo "✅ Authenticated"

# Get @OPTIM profile ID
PROFILE_ID=$(curl -s -X GET "$BASE_URL/api/v1/profiles" \
  -H "Authorization: Bearer $JWT" | jq -r '.profiles[] | select(.tag == "OPTIM") | .id')

if [ "$PROFILE_ID" == "null" ] || [ -z "$PROFILE_ID" ]; then
    echo "❌ @OPTIM profile not found"
    exit 1
fi

echo "📋 @OPTIM profile ID: $PROFILE_ID"

# Clear classification cache and force reclassification
RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/profiles/$PROFILE_ID/reclassify" \
  -H "Authorization: Bearer $JWT")

echo "📤 Response: $RESPONSE"

# Check if reclassification succeeded
STATUS=$(echo "$RESPONSE" | jq -r '.status // "unknown"')

if [ "$STATUS" = "success" ]; then
    echo ""
    echo "✅ Classification cache cleared and reclassified successfully!"
    echo ""
    echo "🔄 The @OPTIM profile has been reclassified with tool_scopes"
    echo "   and the column iterator orchestrator will now work correctly."
    echo ""
    echo "You can now run: python test_mcp_prompt_fix.py"
else
    echo ""
    echo "❌ Reclassification failed (status: $STATUS)"
    MESSAGE=$(echo "$RESPONSE" | jq -r '.message // "No message"')
    echo "Message: $MESSAGE"
    echo ""
    echo "Full response:"
    echo "$RESPONSE" | jq '.'
fi
