#!/bin/bash
"""
Wrapper script to run access token tests with rate limiting disabled.

This script temporarily disables rate limiting to allow comprehensive testing
without hitting rate limits (default: 3 registrations per hour per IP).
"""

# Disable rate limiting for testing
export TDA_RATE_LIMIT_ENABLED=false

echo "Running access token tests with rate limiting disabled..."
echo ""

# Run the test suite
python test/test_access_tokens.py

# Capture exit code
EXIT_CODE=$?

echo ""
echo "Tests complete. Exit code: $EXIT_CODE"

exit $EXIT_CODE
