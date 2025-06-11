#!/bin/bash

# Test cell creation via API

API_BASE_URL="http://localhost:9091/api/v1"
NOTEBOOK_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')

echo "Testing with notebook ID: $NOTEBOOK_ID"

# Create notebook
echo -e "\n1. Creating notebook..."
curl -X POST "$API_BASE_URL/notebooks" \
  -H "Content-Type: application/json" \
  -d "{\"id\": \"$NOTEBOOK_ID\", \"title\": \"Test Notebook\"}"

# Test cell creation query
echo -e "\n\n2. Testing cell creation query..."
SESSION_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')

curl -X POST "$API_BASE_URL/notebooks/$NOTEBOOK_ID/chat" \
  -H "Content-Type: application/json" \
  -d "{\"prompt\": \"Create a markdown cell with the content '# Test Header'\", \"session_id\": \"$SESSION_ID\"}" \
  --no-buffer

# Get cells
echo -e "\n\n3. Getting notebook cells..."
curl -X GET "$API_BASE_URL/notebooks/$NOTEBOOK_ID/cells" | jq '.'