#!/bin/bash

#############################################################################
# Test Session Creation with Both Authentication Methods
#
# This script demonstrates and tests session creation using:
# 1. JWT Token (login-based, short-lived, 24 hours)
# 2. Access Token (long-lived, configurable expiration)
#
# Usage:
#     bash test/test_session_creation_methods.sh
#
# Requirements:
#     - curl
#     - jq
#     - Server running at http://localhost:5050
#     - User must have a configured default profile (LLM + MCP Server)
#############################################################################

set -euo pipefail

# Configuration
BASE_URL="${BASE_URL:-http://localhost:5050}"
API_V1="${BASE_URL}/api/v1"
AUTH_BASE="${BASE_URL}/api/v1/auth"

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_header() {
    echo -e "\n${BLUE}================================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================================================${NC}\n"
}

log_section() {
    echo -e "\n${YELLOW}>>> $1${NC}"
}

log_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

log_error() {
    echo -e "${RED}✗ $1${NC}"
}

log_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

log_step() {
    echo -e "\n${YELLOW}[Step $1]${NC} $2"
}

# Check dependencies
check_dependencies() {
    log_section "Checking dependencies"
    
    if ! command -v curl &> /dev/null; then
        log_error "curl is not installed"
        exit 1
    fi
    log_success "curl is installed"
    
    if ! command -v jq &> /dev/null; then
        log_error "jq is not installed"
        echo "Install with: brew install jq (macOS) or sudo apt-get install jq (Linux)"
        exit 1
    fi
    log_success "jq is installed"
}

# Test server connectivity
test_server() {
    log_section "Testing server connectivity"
    
    if ! curl -s "$BASE_URL/health" > /dev/null 2>&1; then
        log_error "Cannot connect to server at $BASE_URL"
        log_info "Make sure the server is running: python -m trusted_data_agent.main"
        exit 1
    fi
    log_success "Server is running at $BASE_URL"
}

# Get credentials
get_credentials() {
    log_section "Enter credentials"
    
    read -p "${YELLOW}Username: ${NC}" USERNAME
    read -sp "${YELLOW}Password: ${NC}" PASSWORD
    echo ""
    
    if [ -z "$USERNAME" ] || [ -z "$PASSWORD" ]; then
        log_error "Username and password are required"
        exit 1
    fi
}

# ============================================================================
# Profile Setup Functions
# ============================================================================

check_default_profile() {
    local JWT_TOKEN=$1
    
    PROFILE_RESPONSE=$(curl -s -X GET "$API_V1/profiles" \
        -H "Authorization: Bearer $JWT_TOKEN")
    
    DEFAULT_PROFILE_ID=$(echo "$PROFILE_RESPONSE" | jq -r '.default_profile_id // empty')
    
    if [ -n "$DEFAULT_PROFILE_ID" ]; then
        return 0  # Profile exists
    else
        return 1  # No profile
    fi
}

show_profile_setup_requirement() {
    echo -e "\n${RED}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║                   PROFILE SETUP REQUIRED                        ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo -e ""
    echo -e "The REST API requires a configured profile (LLM + MCP Server)."
    echo -e ""
    echo -e "${YELLOW}To configure a profile:${NC}"
    echo -e "  1. Open the web UI at http://localhost:5050"
    echo -e "  2. Click 'Configuration' panel"
    echo -e "  3. Add an LLM Provider (if not already added)"
    echo -e "  4. Add an MCP Server (if not already added)"
    echo -e "  5. Create a profile combining LLM + MCP"
    echo -e "  6. Mark it as default"
    echo -e ""
}

# ============================================================================
# METHOD 1: JWT Token Approach
# ============================================================================

test_jwt_approach() {
    log_section "METHOD 1: JWT Token (Short-lived, 24 hours)"
    
    # Step 1: Login to get JWT
    log_step "1" "Login to get JWT token"
    log_info "POST $AUTH_BASE/login"
    
    LOGIN_RESPONSE=$(curl -s -X POST "$AUTH_BASE/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")
    
    JWT_TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.token // empty')
    
    if [ -z "$JWT_TOKEN" ]; then
        log_error "Login failed or no token in response"
        echo "$LOGIN_RESPONSE" | jq '.' 2>/dev/null || echo "$LOGIN_RESPONSE"
        return 1
    fi
    
    USER_ID=$(echo "$LOGIN_RESPONSE" | jq -r '.user.id')
    USER_NAME=$(echo "$LOGIN_RESPONSE" | jq -r '.user.username')
    
    log_success "Login successful"
    echo "  Token (first 50 chars): ${JWT_TOKEN:0:50}..."
    echo "  User: $USER_NAME"
    echo "  User ID: $USER_ID"
    
    # Step 2: Check if user has a default profile
    log_step "2" "Check for default profile"
    
    if ! check_default_profile "$JWT_TOKEN"; then
        log_error "No default profile found"
        show_profile_setup_requirement
        return 1
    fi
    
    log_success "Default profile is configured"
    
    # Step 3: Create session with JWT
    log_step "3" "Create session using JWT token"
    log_info "POST $API_V1/sessions"
    
    SESSION_RESPONSE=$(curl -s -X POST "$API_V1/sessions" \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H "Content-Type: application/json")
    
    JWT_SESSION_ID=$(echo "$SESSION_RESPONSE" | jq -r '.session_id // empty')
    
    if [ -z "$JWT_SESSION_ID" ]; then
        log_error "Session creation failed"
        ERROR_MSG=$(echo "$SESSION_RESPONSE" | jq -r '.error // empty')
        if [ -n "$ERROR_MSG" ]; then
            echo "  Error: $ERROR_MSG"
        else
            echo "$SESSION_RESPONSE" | jq '.' 2>/dev/null || echo "$SESSION_RESPONSE"
        fi
        return 1
    fi
    
    log_success "Session created successfully"
    echo "  Session ID: $JWT_SESSION_ID"
    
    # Step 4: Submit a test query
    log_step "4" "Submit test query to session"
    log_info "POST $API_V1/sessions/$JWT_SESSION_ID/query"
    
    QUERY_RESPONSE=$(curl -s -X POST "$API_V1/sessions/$JWT_SESSION_ID/query" \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"prompt":"What is available?"}')
    
    TASK_ID=$(echo "$QUERY_RESPONSE" | jq -r '.task_id // empty')
    
    if [ -z "$TASK_ID" ]; then
        log_error "Query submission failed"
        echo "$QUERY_RESPONSE" | jq '.' 2>/dev/null || echo "$QUERY_RESPONSE"
        return 1
    fi
    
    log_success "Query submitted successfully"
    echo "  Task ID: $TASK_ID"
    
    # Step 5: Check task status
    log_step "5" "Check task status"
    log_info "GET $API_V1/tasks/$TASK_ID"
    
    sleep 2  # Give the task time to process
    
    STATUS_RESPONSE=$(curl -s -X GET "$API_V1/tasks/$TASK_ID" \
        -H "Authorization: Bearer $JWT_TOKEN")
    
    STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status // empty')
    
    if [ -z "$STATUS" ]; then
        log_error "Could not retrieve task status"
    else
        log_success "Task status retrieved"
        echo "  Status: $STATUS"
        echo "  Last updated: $(echo "$STATUS_RESPONSE" | jq -r '.last_updated // "N/A"')"
    fi
}

# ============================================================================
# METHOD 2: Access Token Approach
# ============================================================================

test_access_token_approach() {
    log_section "METHOD 2: Access Token (Long-lived, configurable)"
    
    # Step 1: Login to get JWT (temporary)
    log_step "1" "Login to get JWT token (temporary)"
    log_info "POST $AUTH_BASE/login"
    
    LOGIN_RESPONSE=$(curl -s -X POST "$AUTH_BASE/login" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")
    
    JWT_TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.token // empty')
    
    if [ -z "$JWT_TOKEN" ]; then
        log_error "Login failed"
        return 1
    fi
    
    log_success "Login successful (got temporary JWT)"
    echo "  Token (first 50 chars): ${JWT_TOKEN:0:50}..."
    
    # Step 2: Create access token
    log_step "2" "Create long-lived access token using JWT"
    log_info "POST $API_V1/auth/tokens"
    
    TOKEN_NAME="Test-Token-$(date +%s)"
    
    TOKEN_RESPONSE=$(curl -s -X POST "$API_V1/auth/tokens" \
        -H "Authorization: Bearer $JWT_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"name\":\"$TOKEN_NAME\",\"expires_in_days\":90}")
    
    ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.token // empty')
    
    if [ -z "$ACCESS_TOKEN" ]; then
        log_error "Access token creation failed"
        echo "$TOKEN_RESPONSE" | jq '.' 2>/dev/null || echo "$TOKEN_RESPONSE"
        return 1
    fi
    
    TOKEN_ID=$(echo "$TOKEN_RESPONSE" | jq -r '.token_id')
    EXPIRES_AT=$(echo "$TOKEN_RESPONSE" | jq -r '.expires_at')
    
    log_success "Access token created successfully"
    echo "  Token: $ACCESS_TOKEN"
    echo "  Token ID: $TOKEN_ID"
    echo "  Expires at: $EXPIRES_AT"
    echo "  ${RED}⚠️  SAVE THIS TOKEN! It cannot be retrieved later!${NC}"
    
    # Step 3: Check if user has a default profile
    log_step "3" "Check for default profile"
    
    if ! check_default_profile "$ACCESS_TOKEN"; then
        log_error "No default profile found"
        show_profile_setup_requirement
        return 1
    fi
    
    log_success "Default profile is configured"
    
    # Step 4: Create session with access token
    log_step "4" "Create session using access token"
    log_info "POST $API_V1/sessions"
    
    SESSION_RESPONSE=$(curl -s -X POST "$API_V1/sessions" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json")
    
    ACCESS_SESSION_ID=$(echo "$SESSION_RESPONSE" | jq -r '.session_id // empty')
    
    if [ -z "$ACCESS_SESSION_ID" ]; then
        log_error "Session creation failed"
        ERROR_MSG=$(echo "$SESSION_RESPONSE" | jq -r '.error // empty')
        if [ -n "$ERROR_MSG" ]; then
            echo "  Error: $ERROR_MSG"
        else
            echo "$SESSION_RESPONSE" | jq '.' 2>/dev/null || echo "$SESSION_RESPONSE"
        fi
        return 1
    fi
    
    log_success "Session created successfully"
    echo "  Session ID: $ACCESS_SESSION_ID"
    
    # Step 5: Submit a test query
    log_step "5" "Submit test query to session"
    log_info "POST $API_V1/sessions/$ACCESS_SESSION_ID/query"
    
    QUERY_RESPONSE=$(curl -s -X POST "$API_V1/sessions/$ACCESS_SESSION_ID/query" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"prompt":"What is available?"}')
    
    TASK_ID=$(echo "$QUERY_RESPONSE" | jq -r '.task_id // empty')
    
    if [ -z "$TASK_ID" ]; then
        log_error "Query submission failed"
        echo "$QUERY_RESPONSE" | jq '.' 2>/dev/null || echo "$QUERY_RESPONSE"
        return 1
    fi
    
    log_success "Query submitted successfully"
    echo "  Task ID: $TASK_ID"
    
    # Step 6: Check task status
    log_step "6" "Check task status"
    log_info "GET $API_V1/tasks/$TASK_ID"
    
    sleep 2  # Give the task time to process
    
    STATUS_RESPONSE=$(curl -s -X GET "$API_V1/tasks/$TASK_ID" \
        -H "Authorization: Bearer $ACCESS_TOKEN")
    
    STATUS=$(echo "$STATUS_RESPONSE" | jq -r '.status // empty')
    
    if [ -z "$STATUS" ]; then
        log_error "Could not retrieve task status"
    else
        log_success "Task status retrieved"
        echo "  Status: $STATUS"
        echo "  Last updated: $(echo "$STATUS_RESPONSE" | jq -r '.last_updated // "N/A"')"
    fi
    
    # Save token for later use
    echo ""
    log_info "Save this token for future use:"
    echo "  export TDA_ACCESS_TOKEN='$ACCESS_TOKEN'"
}

# ============================================================================
# Main
# ============================================================================

main() {
    log_header "REST API Session Creation Test - Both Authentication Methods"
    
    check_dependencies
    test_server
    get_credentials
    
    log_header "APPROACH 1: JWT Token (24-hour session)"
    if ! test_jwt_approach; then
        log_error "JWT approach test failed"
    fi
    
    log_header "APPROACH 2: Access Token (90-day persistence)"
    if ! test_access_token_approach; then
        log_error "Access Token approach test failed"
    fi
    
    log_header "SUMMARY"
    
    echo -e "${YELLOW}JWT Token Approach:${NC}"
    echo "  - Lifetime: 24 hours"
    echo "  - Use case: Web UI, interactive sessions"
    echo "  - Revocation: Automatic after expiration"
    echo "  - Created via: POST /auth/login"
    
    echo -e "\n${YELLOW}Access Token Approach:${NC}"
    echo "  - Lifetime: 30/60/90/180/365 days or never"
    echo "  - Use case: API automation, CI/CD, scripts"
    echo "  - Revocation: Manual or automatic after expiration"
    echo "  - Created via: POST /api/v1/auth/tokens"
    echo "  - Stored: Secure hash in database"
    
    echo -e "\n${YELLOW}Key Advantages:${NC}"
    echo "  - ${GREEN}Both work for session creation${NC}"
    echo "  - ${GREEN}Both work for query execution${NC}"
    echo "  - ${GREEN}Both authenticate with Bearer scheme${NC}"
    echo "  - ${GREEN}Access token is better for automation${NC}"
    echo "  - ${GREEN}JWT is better for interactive use${NC}"
    
    echo -e "\n${BLUE}================================================================${NC}\n"
}

# Run main function
main "$@"
