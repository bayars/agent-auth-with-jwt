# MCP Example Tool Servers

Five standalone FastMCP tool servers, each with its own Docker image, Helm chart, and build script.

## Servers and tools

| Server | Port | Tools | What it demonstrates |
|---|---|---|---|
| `http-caller` | 8001 | `fetch_url`, `fetch_json`, `post_json` | External HTTP calls, error handling, domain allow-listing |
| `file-generator` | 8002 | `generate_csv`, `generate_json_file`, `generate_markdown`, `generate_zip` | File output (text + base64 binary), Pydantic input models |
| `text-generator` | 8003 | `generate_readme`, `generate_api_docs`, `generate_changelog`, `generate_report` | Large text output, complex structured inputs |
| `text-utils` | 8004 | `count_words`, `format_json`, `base64_encode/decode`, `url_encode/decode`, `change_case`, `extract_lines`, `diff_texts` | Basic text returns, stdlib-only, no I/O |
| `rag-server` | 8005 | `ingest`, `search`, `execute`, `list_collections`, `delete`, `seed_demo`, `get_job_status`, `list_my_jobs` | Semantic search, ChromaDB + Ollama embeddings, async job store, Keycloak role-gating |

## Quick start (Docker Compose)

```bash
# From repo root — builds and starts all five tool servers
docker compose up mcp-http-caller mcp-file-generator mcp-text-generator mcp-text-utils mcp-rag-server -d

# Verify health
curl http://localhost:8001/health   # → {"status":"ok","server":"mcp-http-caller"}
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
curl http://localhost:8005/health   # → {"status":"ok","server":"mcp-rag-server"}
```

## Quick start (Kubernetes / Helm)

```bash
# Build and push images
IMAGE_REGISTRY=ghcr.io/your-org IMAGE_TAG=v1.0.0 PUSH=true ./tools/build-all.sh

# Install individual tool
helm install http-caller tools/http-caller/helm/mcp-http-caller \
  --set image.tag=v1.0.0

# Install all tools at once (umbrella chart)
# 1. Update chart dependencies first:
cd tools/mcp-tools-stack && helm dependency update && cd -

# 2. Install:
helm install mcp-tools tools/mcp-tools-stack \
  --set "mcp-http-caller.image.tag=v1.0.0"
```

## Build scripts

```bash
# Build one tool
cd tools/http-caller && bash build.sh

# Build all tools
bash tools/build-all.sh

# Build + push all (e.g. for CI)
IMAGE_REGISTRY=ghcr.io/your-org IMAGE_TAG=v1.0.0 PUSH=true bash tools/build-all.sh
```

## Documentation

| File | Contents |
|---|---|
| `docs/01-writing-tools.md` | How to write a tool: function signature, types, errors, DI |
| `docs/02-io-formats.md` | Input/output format reference, MCP JSON-RPC wire format |
| `docs/03-connecting-tools.md` | Registering servers in opencode.json, docker-compose, Helm |
| `docs/04-rag-tool.md` | RAG tool server: architecture, all 8 tools, job store, persistence, auth |

## Directory structure

```
tools/
├── build-all.sh                   ← build all five images
├── http-caller/
│   ├── main.py                    ← tool implementation
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── build.sh
│   └── helm/mcp-http-caller/      ← Helm chart
├── file-generator/    (same layout)
├── text-generator/    (same layout)
├── text-utils/        (same layout)
├── rag-server/
│   ├── main.py
│   ├── store.py                   ← ChromaDB wrapper
│   ├── job_store.py               ← Redis-backed async job tracker
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── build.sh
│   └── helm/mcp-rag-server/       ← Helm chart (with Redis sidecar + PVC)
├── mcp-tools-stack/               ← umbrella Helm chart (deploys all five)
│   ├── Chart.yaml
│   ├── values.yaml
│   └── templates/opencode-config.yaml
└── docs/
    ├── 01-writing-tools.md
    ├── 02-io-formats.md
    ├── 03-connecting-tools.md
    └── 04-rag-tool.md
```
