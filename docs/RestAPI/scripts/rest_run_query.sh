#!/bin/bash
# rest_run_query.sh
#
# This script automates the entire process of querying the Uderia Platform API.
# It creates a session, submits a user's question, and then monitors the
# progress until a final result is received.
#
# Usage: ./rest_run_query.sh <access_token> "Your question for the agent in quotes" [--session-id <session_id>] [--verbose]

# --- 1. Argument Parsing and Validation ---
VERBOSE=false
USER_QUESTION=""
ACCESS_TOKEN=""
SESSION_ID=""

# Parse arguments
while (( "$#" )); do
  case "$1" in
    --verbose)
      VERBOSE=true
      shift
      ;;
    --session-id)
      if [ -n "$2" ]; then
        SESSION_ID=$2
        shift 2
      else
        echo "Error: --session-id requires a non-empty argument." >&2
        exit 1
      fi
      ;;
    -*)
      echo "Unsupported flag $1" >&2
      exit 1
      ;;
    *)
      if [ -z "$ACCESS_TOKEN" ]; then
        ACCESS_TOKEN=$1
        shift
      elif [ -z "$USER_QUESTION" ]; then
        USER_QUESTION=$1
        shift
      else
        echo "Too many arguments provided." >&2
        exit 1
      fi
      ;;
  esac
done

# Check if required arguments are present
if [ -z "$ACCESS_TOKEN" ] || [ -z "$USER_QUESTION" ]; then
  echo "Usage: ./rest_run_query.sh <access_token> \"<your_question>\" [--session-id <session_id>] [--verbose]" >&2
  echo "Example: ./rest_run_query.sh tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p \"What is the business description for the DEMO_DB database?\" --session-id x-y-z --verbose" >&2
  echo "" >&2
  echo "To get an access token:" >&2
  echo "  1. Login: curl -X POST http://localhost:5050/auth/login -H 'Content-Type: application/json' -d '{\"username\":\"your_user\",\"password\":\"your_pass\"}' | jq -r '.token'" >&2
  echo "  2. Create token: curl -X POST http://localhost:5050/api/v1/auth/tokens -H 'Authorization: Bearer YOUR_JWT' -H 'Content-Type: application/json' -d '{\"name\":\"My Token\"}' | jq -r '.token'" >&2
  exit 1
fi
BASE_URL="http://127.0.0.1:5050"

# Function to print messages, redirecting to stderr if not verbose
log_message() {
  if [ "$VERBOSE" = false ]; then
    echo "$@" >&2
  else
    echo "$@"
  fi
}

# --- 2. Check for Dependencies ---
if ! command -v jq &> /dev/null; then
    log_message "Error: 'jq' is not installed. Please install it to continue."
    log_message "On macOS: brew install jq"
    log_message "On Debian/Ubuntu: sudo apt-get install jq"
    exit 1
fi

if [ ! -x "./rest_check_status.sh" ]; then
    log_message "Error: 'rest_check_status.sh' not found or is not executable."
    log_message "Please ensure it is in the same directory and run 'chmod +x rest_check_status.sh'."
    exit 1
fi



if [ -z "$SESSION_ID" ]; then
  # --- 4. Create a New Session ---
  log_message "--> Step 1: Creating a new session..."
  SESSION_ID=$(curl -s -X POST -H "Authorization: Bearer $ACCESS_TOKEN" "$BASE_URL/api/v1/sessions" | jq -r .session_id)

  if [ -z "$SESSION_ID" ] || [ "$SESSION_ID" = "null" ]; then
    log_message "Error: Failed to create a session. Is the server running and configured?"
    log_message "Check if your access token is valid."
    exit 1
  fi
  log_message "    Session created successfully: $SESSION_ID"
  log_message ""
else
  log_message "--> Step 1: Using existing session: $SESSION_ID"
  log_message ""
fi

# --- 5. Submit the Query ---
log_message "--> Step 2: Submitting your query..."
JSON_PAYLOAD=$(jq -n --arg prompt "$USER_QUESTION" '{prompt: $prompt}')

TASK_URL=$(curl -s -X POST "$BASE_URL/api/v1/sessions/$SESSION_ID/query" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $ACCESS_TOKEN" \
     -d "$JSON_PAYLOAD" | jq -r .status_url)

if [ -z "$TASK_URL" ] || [ "$TASK_URL" = "null" ]; then
  log_message "Error: Failed to submit the query and get a task URL."
  exit 1
fi
log_message "    Query submitted. Task URL path is: $TASK_URL"
log_message ""


# --- 6. Run the Status Checker ---
log_message "--> Step 3: Starting the status checker. Monitoring for results..."
log_message "================================================================="

# Execute the status checking script, passing it the task URL, access token, and verbose flag.
if [ "$VERBOSE" = true ]; then
  ./rest_check_status.sh "$TASK_URL" "$ACCESS_TOKEN" --verbose
else
  ./rest_check_status.sh "$TASK_URL" "$ACCESS_TOKEN"
fi
