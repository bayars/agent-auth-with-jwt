#!/usr/bin/env bash
# Fetches a client_credentials access token for the fastmcp-service client.
# Run after `docker compose up keycloak -d` and Keycloak is healthy.
#
# Usage:
#   ./scripts/get-service-token.sh
#
# Then copy the printed MCP_SERVICE_TOKEN value into your .env file.

set -euo pipefail

KC_URL="${KC_URL:-http://localhost:8080}"
KC_REALM="${KC_REALM:-poc-realm}"
CLIENT_ID="${CLIENT_ID:-fastmcp-service}"
CLIENT_SECRET="${CLIENT_SECRET:-fastmcp-service-secret-change-me}"

RESPONSE=$(curl -sf -X POST \
  "${KC_URL}/realms/${KC_REALM}/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=${CLIENT_ID}" \
  -d "client_secret=${CLIENT_SECRET}" \
  -d "scope=openid")

ACCESS_TOKEN=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

echo ""
echo "Add this to your .env file:"
echo ""
echo "MCP_SERVICE_TOKEN=${ACCESS_TOKEN}"
echo ""
echo "Note: this token expires in 5 minutes. For production, implement a token refresh mechanism."
