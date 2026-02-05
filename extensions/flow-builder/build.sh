#!/bin/bash

# Flow Builder Build Script
# Builds the React frontend and copies the bundle to Uderia's static folder

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
OUTPUT_DIR="$SCRIPT_DIR/../../static/js/flowBuilder/dist"

echo "=== Uderia Flow Builder Build ==="
echo "Frontend source: $FRONTEND_DIR"
echo "Output directory: $OUTPUT_DIR"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Navigate to frontend directory
cd "$FRONTEND_DIR"

# Install dependencies if node_modules doesn't exist
if [ ! -d "node_modules" ]; then
    echo ""
    echo "Installing dependencies..."
    npm install
fi

# Build the React app
echo ""
echo "Building Flow Builder React app..."
npm run build

echo ""
echo "=== Build Complete ==="
echo "Bundle location: $OUTPUT_DIR/flowBuilder.bundle.js"
echo ""
echo "To start the Flow Builder backend:"
echo "  cd $SCRIPT_DIR/backend"
echo "  pip install -r ../requirements.txt"
echo "  python main.py"
echo ""
echo "The Flow Builder will be available in Uderia's navigation menu."
