#!/usr/bin/env bash
# Build all MCP tool server Docker images.
#
# Usage:
#   ./tools/build-all.sh                     # build all, tag as latest
#   IMAGE_TAG=v1.2.0 ./tools/build-all.sh   # custom tag
#   IMAGE_TAG=v1.2.0 PUSH=true ./tools/build-all.sh  # build + push

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export IMAGE_TAG="${IMAGE_TAG:-latest}"
export PUSH="${PUSH:-false}"
export IMAGE_REGISTRY="${IMAGE_REGISTRY:-ghcr.io/your-org}"

TOOLS=(http-caller file-generator text-generator text-utils rag-server)
FAILED=()

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo " MCP Tool Builder"
echo " Registry : ${IMAGE_REGISTRY}"
echo " Tag      : ${IMAGE_TAG}"
echo " Push     : ${PUSH}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

for tool in "${TOOLS[@]}"; do
  echo ""
  echo "▶ Building ${tool}..."
  if bash "${SCRIPT_DIR}/${tool}/build.sh"; then
    echo "  ✓ ${tool} built"
  else
    echo "  ✗ ${tool} FAILED"
    FAILED+=("${tool}")
  fi
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ ${#FAILED[@]} -eq 0 ]]; then
  echo " All ${#TOOLS[@]} tools built successfully."
else
  echo " ${#FAILED[@]} tool(s) failed: ${FAILED[*]}"
  exit 1
fi
