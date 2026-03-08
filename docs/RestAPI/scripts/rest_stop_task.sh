#!/bin/bash
# rest_stop_task.sh
#
# This script sends a cancellation request for a running task.
#
# Usage: ./rest_stop_task.sh <task_id> <access_token> [--base-url <url>]

# --- 1. Argument Parsing ---
TASK_ID=""
ACCESS_TOKEN=""
BASE_URL="http://127.0.0.1:5050"

while (( "$#" )); do
  case "$1" in
    --base-url)
      if [ -n "$2" ]; then
        BASE_URL=$2
        shift 2
      else
        echo "Error: --base-url requires a non-empty argument." >&2
        exit 1
      fi
      ;;
    -*)
      echo "Unsupported flag $1" >&2
      exit 1
      ;;
    *)
      if [ -z "$TASK_ID" ]; then
        TASK_ID=$1
        shift
      elif [ -z "$ACCESS_TOKEN" ]; then
        ACCESS_TOKEN=$1
        shift
      else
        echo "Too many arguments provided." >&2
        exit 1
      fi
      ;;
  esac
done

# Check if required arguments are present
if [ -z "$TASK_ID" ] || [ -z "$ACCESS_TOKEN" ]; then
  echo "Usage: ./rest_stop_task.sh <task_id> <access_token> [--base-url <url>]" >&2
  echo "Example: ./rest_stop_task.sh task-123-456 tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p" >&2
  exit 1
fi

# --- 2. Check Dependencies ---
if ! command -v jq &> /dev/null; then
    echo "Error: 'jq' is not installed. Please install it to continue." >&2
    echo "On macOS: brew install jq" >&2
    echo "On Debian/Ubuntu: sudo apt-get install jq" >&2
    exit 1
fi

# --- 3. Send Cancellation Request ---
CANCEL_URL="${BASE_URL}/api/v1/tasks/${TASK_ID}/cancel"
echo "Attempting to cancel task $TASK_ID at: $CANCEL_URL"

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$CANCEL_URL" \
  -H "Authorization: Bearer $ACCESS_TOKEN")

HTTP_STATUS=$(tail -n1 <<< "$RESPONSE")
HTTP_BODY=$(sed '$ d' <<< "$RESPONSE")

echo "--- Server Response (HTTP Status: $HTTP_STATUS) ---"

if [ "$HTTP_STATUS" -eq 200 ]; then
  echo "$HTTP_BODY" | jq .
  STATUS=$(echo "$HTTP_BODY" | jq -r '.status')
  MESSAGE=$(echo "$HTTP_BODY" | jq -r '.message')
  echo "Status: $STATUS"
  echo "Message: $MESSAGE"
elif [ "$HTTP_STATUS" -eq 404 ]; then
  echo "Error: Task not found or already completed."
  echo "$HTTP_BODY" | jq . 2>/dev/null || echo "$HTTP_BODY"
  exit 1
elif [ "$HTTP_STATUS" -eq 401 ]; then
  echo "Error: Authentication failed. Check your access token."
  echo "$HTTP_BODY" | jq . 2>/dev/null || echo "$HTTP_BODY"
  exit 1
else
  echo "Error: Received unexpected status code $HTTP_STATUS"
  echo "$HTTP_BODY" | jq . 2>/dev/null || echo "$HTTP_BODY"
  exit 1
fi
