#!/bin/bash
# rest_check_status.sh
#
# This script polls a task status URL until the task is complete,
# printing new events as they arrive.
#
# Usage: ./rest_check_status.sh <task_url_path> <access_token> [--verbose]

# --- 1. Argument Parsing and Validation ---
VERBOSE=false
TASK_URL_PATH=""
ACCESS_TOKEN=""

# Parse arguments
while (( "$#" )); do
  case "$1" in
    --verbose)
      VERBOSE=true
      ;;
    -*)
      echo "Unsupported flag $1" >&2
      exit 1
      ;;
    *)
      if [ -z "$TASK_URL_PATH" ]; then
        TASK_URL_PATH=$1
      elif [ -z "$ACCESS_TOKEN" ]; then
        ACCESS_TOKEN=$1
      else
        echo "Too many arguments provided." >&2
        exit 1
      fi
      ;;
  esac
  shift
done

# Check if required arguments are present
if [ -z "$TASK_URL_PATH" ] || [ -z "$ACCESS_TOKEN" ]; then
  echo "Usage: ./rest_check_status.sh <task_url_path> <access_token> [--verbose]" >&2
  echo "Example: ./rest_check_status.sh /api/v1/tasks/some-task-id tda_1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p --verbose" >&2
  exit 1
fi

# Function to print messages, redirecting to stderr if not verbose
log_message() {
  if [ "$VERBOSE" = false ]; then
    echo "$@" >&2
  else
    echo "$@"
  fi
}

# --- 2. Initialization ---
BASE_URL="http://127.0.0.1:5050"
FULL_URL="$BASE_URL$TASK_URL_PATH"
EVENTS_SEEN=0

log_message "Polling status for task at: $FULL_URL"
log_message "-------------------------------------"

# --- 3. Polling Loop ---
while true; do
  # Fetch the latest task status using Bearer token authentication
  RESPONSE=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "$FULL_URL")

  # Gracefully handle cases where the server response is empty
  if [ -z "$RESPONSE" ]; then
    log_message "Warning: Received empty response from server. Retrying..."
    sleep 2
    continue
  fi

  # --- Print NEW events ---
  # Safely get the total number of events, providing a default of 0
  TOTAL_EVENTS=$(echo "$RESPONSE" | jq '(.events | length) // 0')

  # Add a final check to ensure TOTAL_EVENTS is a number before comparison
  if ! [[ "$TOTAL_EVENTS" =~ ^[0-9]+$ ]]; then
    log_message "Warning: Could not parse event count from response. The response may not be valid JSON."
    TOTAL_EVENTS=$EVENTS_SEEN # Avoid breaking the loop; use the last known good count
  fi

  # Check if there are more events now than we've seen before
  if [ "$TOTAL_EVENTS" -gt "$EVENTS_SEEN" ]; then
    # If so, get only the new events
    NEW_EVENTS=$(echo "$RESPONSE" | jq -c ".events[$EVENTS_SEEN:] | .[]")

    # Print each new event, formatting with jq for readability
    if [ "$VERBOSE" = true ]; then
      echo "$NEW_EVENTS" | jq
    fi

    # Update the count of events we've seen
    EVENTS_SEEN=$TOTAL_EVENTS
  fi

  # --- Check for completion ---
  STATUS=$(echo "$RESPONSE" | jq -r .status)
  if [[ "$STATUS" == "complete" || "$STATUS" == "error" || "$STATUS" == "cancelled" ]]; then # Added cancelled status check
    log_message "-------------------------------------"
    log_message "--- FINAL STATUS: $STATUS ---"
    log_message "--- FINAL RESULT ---"
    echo "$RESPONSE" | jq '.result' # Always print final result to stdout
    break
  fi

  sleep 1
done