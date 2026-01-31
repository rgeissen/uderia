#!/bin/bash

# Check for config file
if [ -z "$1" ]; then
  echo "Usage: ./rest_config.sh <config.json>"
  exit 1
fi

CONFIG_FILE=$1

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Error: Config file not found: $CONFIG_FILE"
  exit 1
fi

# Display the configuration (without apiKey)
echo "--- Configuration to be sent (excluding apiKey) ---"
jq 'del(.credentials.apiKey)' "$CONFIG_FILE"
echo "-------------------------------------------------"

# Send the configuration to the server
echo "Sending configuration to the server..."
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST http://127.0.0.1:5050/api/v1/configure \
-H "Content-Type: application/json" \
-d @"$CONFIG_FILE")

HTTP_STATUS=$(tail -n1 <<< "$RESPONSE")
HTTP_BODY=$(sed '$ d' <<< "$RESPONSE")

echo "--- Server Response (HTTP Status: $HTTP_STATUS) ---"
echo "$HTTP_BODY" | jq .
echo "-------------------------------------------------"

if [ "$HTTP_STATUS" -ne 200 ]; then
  echo "Error: Configuration failed."
  exit 1
fi
