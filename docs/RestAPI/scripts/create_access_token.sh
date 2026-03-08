#!/bin/bash
# create_access_token.sh
#
# This script helps you create an access token for REST API authentication.
#
# Usage: ./create_access_token.sh <username> <password> [token_name] [expires_in_days]

# --- 1. Argument Parsing ---
USERNAME=""
PASSWORD=""
TOKEN_NAME="API Token"
EXPIRES_IN_DAYS=90
BASE_URL="http://127.0.0.1:5050"

if [ -z "$1" ] || [ -z "$2" ]; then
  echo "Usage: ./create_access_token.sh <username> <password> [token_name] [expires_in_days]" >&2
  echo "Example: ./create_access_token.sh myuser mypass 'Production Token' 90" >&2
  echo "" >&2
  echo "Default token name: 'API Token'" >&2
  echo "Default expiration: 90 days" >&2
  exit 1
fi

USERNAME=$1
PASSWORD=$2

if [ -n "$3" ]; then
  TOKEN_NAME=$3
fi

if [ -n "$4" ]; then
  EXPIRES_IN_DAYS=$4
fi

# --- 2. Check Dependencies ---
if ! command -v jq &> /dev/null; then
    echo "Error: 'jq' is not installed. Please install it to continue." >&2
    echo "On macOS: brew install jq" >&2
    echo "On Debian/Ubuntu: sudo apt-get install jq" >&2
    exit 1
fi

# --- 3. Login to Get JWT Token ---
echo "Step 1: Logging in as '$USERNAME'..."
JWT_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")

JWT_TOKEN=$(echo "$JWT_RESPONSE" | jq -r '.token')

if [ -z "$JWT_TOKEN" ] || [ "$JWT_TOKEN" = "null" ]; then
  echo "Error: Login failed. Check your username and password." >&2
  echo "Server response: $JWT_RESPONSE" >&2
  exit 1
fi

echo "✓ Login successful"
echo ""

# --- 4. Create Access Token ---
echo "Step 2: Creating access token..."
echo "  Name: $TOKEN_NAME"
echo "  Expires in: $EXPIRES_IN_DAYS days"
echo ""

TOKEN_RESPONSE=$(curl -s -X POST "$BASE_URL/api/v1/auth/tokens" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$TOKEN_NAME\",\"expires_in_days\":$EXPIRES_IN_DAYS}")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.token')

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
  echo "Error: Failed to create access token." >&2
  echo "Server response: $TOKEN_RESPONSE" >&2
  exit 1
fi

# --- 5. Display Results ---
echo "=========================================="
echo "✓ Access Token Created Successfully!"
echo "=========================================="
echo ""
echo "Your access token:"
echo "  $ACCESS_TOKEN"
echo ""
echo "⚠️  IMPORTANT: Save this token securely!"
echo "   It will NOT be shown again."
echo ""
echo "Token details:"
echo "$TOKEN_RESPONSE" | jq '{
  token_id: .token_id,
  name: .name,
  created_at: .created_at,
  expires_at: .expires_at
}'
echo ""
echo "To use this token:"
echo "  export TDA_ACCESS_TOKEN='$ACCESS_TOKEN'"
echo ""
echo "Example API call:"
echo "  curl -X POST $BASE_URL/api/v1/sessions \\"
echo "    -H 'Authorization: Bearer $ACCESS_TOKEN'"
echo ""
echo "Or use with the query script:"
echo "  ./rest_run_query.sh '$ACCESS_TOKEN' 'What databases are available?'"
