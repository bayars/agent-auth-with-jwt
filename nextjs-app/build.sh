#!/usr/bin/env bash
set -euo pipefail
REGISTRY="${IMAGE_REGISTRY:-ghcr.io/your-org}"
IMAGE="${REGISTRY}/nextjs-app"
TAG="${IMAGE_TAG:-latest}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Building ${IMAGE}:${TAG}"
docker build -t "${IMAGE}:${TAG}" "${SCRIPT_DIR}"
if [[ "${PUSH:-false}" == "true" ]]; then docker push "${IMAGE}:${TAG}"; fi
