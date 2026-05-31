#!/usr/bin/env bash
set -euo pipefail
REGISTRY="${IMAGE_REGISTRY:-ghcr.io/your-org}"
IMAGE="${REGISTRY}/mcp-http-caller"
TAG="${IMAGE_TAG:-latest}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Building ${IMAGE}:${TAG} from ${SCRIPT_DIR}"
docker build -t "${IMAGE}:${TAG}" "${SCRIPT_DIR}"

if [[ "${PUSH:-false}" == "true" ]]; then
  docker push "${IMAGE}:${TAG}"
  echo "Pushed ${IMAGE}:${TAG}"
fi
