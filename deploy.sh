#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# deploy.sh — build all Docker images, push them, then deploy with helmfile.
#
# Usage:
#   bash deploy.sh                  # build + push + helmfile sync
#   bash deploy.sh --build-only     # build images, skip push and deploy
#   bash deploy.sh --deploy-only    # skip build/push, only helmfile sync
#   bash deploy.sh --dry-run        # helmfile diff instead of sync
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Load env file ─────────────────────────────────────────────────────────────
ENV_FILE=".helm.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found."
  echo "       Copy .helm.env.example to .helm.env and fill in all values."
  exit 1
fi
set -a; source "$ENV_FILE"; set +a

# ── Parse flags ───────────────────────────────────────────────────────────────
BUILD=true
PUSH=true
DEPLOY=true
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --build-only)  PUSH=false;  DEPLOY=false ;;
    --deploy-only) BUILD=false; PUSH=false   ;;
    --dry-run)     DRY_RUN=true              ;;
  esac
done

REGISTRY="${IMAGE_REGISTRY}"
TAG="${IMAGE_TAG}"

# ── Helper ────────────────────────────────────────────────────────────────────
build_and_push() {
  local name="$1"   # e.g. mcp-fastmcp
  local dir="$2"    # e.g. fastmcp-server
  local img="${REGISTRY}/${name}:${TAG}"

  if [[ "$BUILD" == "true" ]]; then
    echo "  ▶ Building ${img}..."
    docker build -t "${img}" "${dir}"
  fi
  if [[ "$PUSH" == "true" ]]; then
    echo "  ▶ Pushing ${img}..."
    docker push "${img}"
  fi
}

# ── 1. Build and push images ──────────────────────────────────────────────────
if [[ "$BUILD" == "true" || "$PUSH" == "true" ]]; then
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo " Building images  (registry: ${REGISTRY}, tag: ${TAG})"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  build_and_push "mcp-fastmcp"        "fastmcp-server"
  build_and_push "nextjs-app"         "nextjs-app"
  build_and_push "mcp-http-caller"    "tools/http-caller"
  build_and_push "mcp-file-generator" "tools/file-generator"
  build_and_push "mcp-text-generator" "tools/text-generator"
  build_and_push "mcp-text-utils"     "tools/text-utils"
  build_and_push "mcp-rag-server"     "tools/rag-server"

  echo ""
  echo "  ✓  All images built${PUSH:+ and pushed}"
fi

# ── 2. Create required Kubernetes secrets (if DEPLOY=true) ────────────────────
if [[ "$DEPLOY" == "true" && "$DRY_RUN" == "false" ]]; then
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo " Ensuring Kubernetes secrets"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  NS="${NAMESPACE}"

  kubectl create namespace "${NS}" --dry-run=client -o yaml | kubectl apply -f -

  # Keycloak admin secret
  kubectl create secret generic keycloak-admin-secret \
    --namespace "${NS}" \
    --from-literal=admin-password="${KC_ADMIN_PASSWORD}" \
    --dry-run=client -o yaml | kubectl apply -f -

  # Keycloak DB secret
  kubectl create secret generic keycloak-db-secret \
    --namespace "${NS}" \
    --from-literal=password="${KC_DB_PASSWORD}" \
    --dry-run=client -o yaml | kubectl apply -f -

  # Next.js app secrets
  kubectl create secret generic nextjs-secret \
    --namespace "${NS}" \
    --from-literal=OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD}" \
    --from-literal=MCP_SERVICE_TOKEN="${MCP_SERVICE_TOKEN}" \
    --dry-run=client -o yaml | kubectl apply -f -

  echo "  ✓  Secrets applied"
fi

# ── 3. Helmfile sync / diff ───────────────────────────────────────────────────
if [[ "$DEPLOY" == "true" ]]; then
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  if [[ "$DRY_RUN" == "true" ]]; then
    echo " Helmfile DIFF (dry-run)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    helmfile diff
  else
    echo " Helmfile SYNC"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    helmfile sync
    echo ""
    echo "  ✓  Deployment complete"
    echo ""
    echo "  Next.js : https://${APP_HOST}"
    echo "  Keycloak: ${KC_EXTERNAL_URL}"
  fi
fi
