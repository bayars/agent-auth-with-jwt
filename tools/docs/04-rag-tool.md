# RAG Tool Server Reference

Complete reference for the `mcp-rag-server` — semantic search, document ingestion, and Retrieval-Augmented Generation tools.

## Overview

**What it does:** Provides a knowledge-base pipeline using ChromaDB (vector store) + Ollama (embeddings).
Users ingest documents, search them semantically, and retrieve formatted context for RAG workflows.

**Architecture:**
- **Vector Store:** ChromaDB (ephemeral or persistent via PVC)
- **Embeddings:** Ollama with `qwen2.5:1.5b` model (1536-dim, cosine similarity)
- **Job Store:** Redis (sidecar in Kubernetes, optional external)
- **Auth:** Keycloak JWT (role-gated ingest/delete operations)

---

## All 8 Tools

### Read-Only Tools (any user)

#### `execute(query, collection="default", top_k=5, min_score=0.2) → str`

**The primary RAG tool.** Searches a collection for documents similar to the query and returns a formatted Markdown context block ready to prepend to a prompt.

**Returns:** Formatted Markdown string with:
- `## Retrieved context for: {query}` header
- Per-document: ID, score (0–1 cosine sim), metadata hints (source, date)
- User-ready statement: "Use the above to answer the question"
- Or a helpful message if no documents match

**Example response:**
```
## Retrieved context for: how does JWT work?
*2 document(s) from collection 'rag-demo'*

### [1] jwt-basics (score: 0.847 · source: project-docs)

JSON Web Tokens (JWT) are compact, URL-safe means of representing claims...
```

---

#### `search(query, collection="default", top_k=5, min_score=0.0) → dict`

Semantic similarity search. Returns raw search results with scores and metadata.

**Returns:**
```json
{
  "query": "...",
  "collection": "...",
  "results": [
    {
      "id": "doc-id",
      "content": "...",
      "score": 0.847,
      "metadata": {"source": "wiki", "date": "2026-01-01"}
    }
  ],
  "count": 2
}
```

**Difference from `execute`:** Raw results + scores (for debugging / advanced use). `execute` is higher-level (formatted context).

---

#### `list_collections() → dict`

List all collections with their document counts.

**Returns:**
```json
{
  "collections": [
    {"name": "rag-demo", "count": 6},
    {"name": "customer-docs", "count": 143}
  ],
  "total": 2
}
```

---

### Write Tools (developer/admin role required)

#### `ingest(documents, collection="default") → dict`

Add or update documents. Small batches run synchronously; large batches return a job_id for background processing.

**Threshold:** Batches > 50 documents run asynchronously.

**Input:**
```json
{
  "documents": [
    {
      "id": "unique-doc-id",
      "content": "Full text to embed and index...",
      "metadata": {"source": "wiki", "date": "2026-01-01"}
    }
  ],
  "collection": "my-docs"
}
```

**Returns (small batch, ≤50 docs):**
```json
{
  "indexed": 3,
  "collection": "my-docs",
  "total": 10
}
```

**Returns (large batch, >50 docs):**
```json
{
  "job_id": "uuid-...",
  "status": "running",
  "document_count": 150,
  "message": "Ingesting 150 documents in the background. Call get_job_status('uuid-...') to track progress."
}
```

**Details:**
- Documents with duplicate IDs are **upserted** (replaced).
- Metadata is optional; empty `{}` is allowed.
- Each document is embedded via Ollama (blocking I/O).
- Large batches are embedded in parallel chunks (configurable).

---

#### `seed_demo(collection="rag-demo") → dict`

Populate a collection with 6 pre-written project documents (JWT, Keycloak, MCP, RAG, FastMCP, Ollama).
Useful for testing. Idempotent — running it again replaces docs by ID.

**Returns:**
```json
{
  "seeded": 6,
  "collection": "rag-demo",
  "example_queries": [
    "How does JWT authentication work?",
    "What is the MCP protocol?",
    "Explain RAG in simple terms",
    "How do I write a FastMCP tool?",
    "What Ollama models are available?"
  ]
}
```

---

#### `delete(collection, doc_ids=None) → dict`

Delete specific documents or an entire collection.

**If `doc_ids` is provided:** Delete those documents.
```json
{
  "deleted": 2,
  "collection": "my-docs",
  "operation": "documents"
}
```

**If `doc_ids` is null/omitted:** Delete the entire collection (irreversible).
```json
{
  "deleted": 1,
  "collection": "my-docs",
  "operation": "collection"
}
```

---

### Job Tracking Tools

#### `get_job_status(job_id) → dict`

Poll the status of a background job (returned by `ingest` when >50 documents).

**Returns:**
```json
{
  "job_id": "uuid-...",
  "status": "pending | running | done | failed",
  "progress": 75,
  "tool": "ingest",
  "result": {"indexed": 150, "total": 285},  // present when status=done
  "error": "",                               // present when status=failed
  "created_at": "2026-01-01T12:00:00Z",
  "updated_at": "2026-01-01T12:00:45Z"
}
```

**Job ownership:** Only the user (via JWT `sub` claim) who created the job can view it. Returns "not found" for other users' jobs.

---

#### `list_my_jobs() → list[dict]`

List all background jobs created by the current user in the last hour, newest first.

**Returns:**
```json
[
  {
    "job_id": "uuid-1",
    "status": "done",
    "progress": 100,
    "tool": "ingest",
    "result": {...},
    "created_at": "2026-01-01T12:00:00Z",
    "updated_at": "2026-01-01T12:00:45Z"
  },
  {
    "job_id": "uuid-2",
    "status": "running",
    "progress": 30,
    "tool": "ingest",
    "created_at": "2026-01-01T11:55:00Z",
    "updated_at": "2026-01-01T11:55:30Z"
  }
]
```

---

## Authentication & Authorization

### No Auth (Dev Mode)
When `KC_REALM_URL` env var is empty:
- All tools are accessible
- No role checks
- Job ownership is by `dev-anonymous` service principal

### With Keycloak JWT
When `KC_REALM_URL` is set:
- All requests must carry a valid JWT (via Authorization header)
- Read tools (`execute`, `search`, `list_collections`) — any authenticated user
- Write tools (`ingest`, `delete`, `seed_demo`) — require `developer` or `admin` realm role
- `get_job_status` — only the job owner (by JWT `sub`) can view
- `list_my_jobs` — returns jobs owned by the authenticated user

**In Kubernetes:** The service account (fastmcp-service) must be assigned the `developer` realm role so OpenCode can call `ingest` and `seed_demo` from the server side.

---

## Storage & Persistence

### ChromaDB
- **Ephemeral (default):** In-memory only, lost on pod restart
- **Persistent:** Mount a PVC at `/data/chroma` via `persistence.enabled: true` in Helm values

### Redis (Job Store)
- **Sidecar (Kubernetes):** Redis pod in the same Deployment (stateless, no persistence)
- **External (optional):** Point to a managed Redis via `REDIS_URL` env var
- **In-Memory (dev fallback):** If `REDIS_URL` is not set, jobs are stored in-process (lost on restart)

**Job TTL:** Configured via `JOB_TTL_SECONDS` (default 3600 = 1 hour). Jobs expire and are removed after this time.

---

## Configuration (Environment Variables)

| Var | Default | Purpose |
|---|---|---|
| `PORT` | 8000 | FastMCP server port |
| `CHROMA_PERSIST_PATH` | "" (empty) | Path to ChromaDB directory (for persistent storage) |
| `EMBEDDING_PROVIDER` | "ollama" | "ollama" or "default" (ONNX built-in) |
| `OLLAMA_URL` | http://10.0.0.224:11434 | Base URL of Ollama service |
| `OLLAMA_EMBED_MODEL` | qwen2.5:1.5b | Ollama model to use for embeddings |
| `MAX_SEARCH_RESULTS` | 20 | Max documents returned by search/execute |
| `ASYNC_INGEST_THRESHOLD` | 50 | Documents above this count run asynchronously |
| `JOB_TTL_SECONDS` | 3600 | Job store entry lifespan |
| `REDIS_URL` | "" (empty) | Redis connection string (e.g., redis://host:6379/0) |
| `KC_REALM_URL` | "" (empty) | Keycloak realm URL for JWT validation (enables auth) |
| `KC_ISSUER` | same as KC_REALM_URL | External-facing issuer URL (must match JWT `iss` claim) |
| `FASTMCP_BASE_URL` | http://mcp-rag-server:8000 | Self-referential base URL (used for JWT verifier) |

---

## Helm Chart

Located at `tools/rag-server/helm/mcp-rag-server/`.

### Key Values

```yaml
persistence:
  enabled: true
  size: 2Gi
redis:
  internal:
    enabled: true
env:
  EMBEDDING_PROVIDER: "ollama"
  OLLAMA_URL: "http://10.0.0.224:11434"
  OLLAMA_EMBED_MODEL: "qwen2.5:1.5b"
  ASYNC_INGEST_THRESHOLD: "50"
```

### Deployment
- Pod includes the RAG server container + Redis sidecar (if `redis.internal.enabled`)
- Liveness probe: `GET /health` every 20s
- Readiness probe: `GET /health` every 10s
- PVC (if enabled) with `helm.sh/resource-policy: keep` (survives `helm uninstall`)

---

## Workflow

### Recommended Usage

```
1. list_collections()                    # Check what exists
2. (if empty) seed_demo("rag-demo")      # Populate with project docs
3. execute("user question", "rag-demo")  # Retrieve context
4. Answer the user based on the context
```

### For Large Ingests (>50 documents)

```
1. Call ingest(documents, "my-collection")
   → Returns {job_id, status: "running"}
2. Tell the user: "Ingesting {n} documents, job: {job_id}"
3. Periodically call get_job_status(job_id)
4. When status=done, report result.indexed and result.total
```

### For Dynamic Knowledge

Combine `ingest` + `list_my_jobs` to let users:
- Upload documentation files
- Monitor background indexing
- See results when ready

---

## Examples

### Seed the demo collection
```
seed_demo("rag-demo")
```

### Add custom documents
```
ingest([
  {"id": "doc-1", "content": "...", "metadata": {"source": "wiki"}},
  {"id": "doc-2", "content": "...", "metadata": {"source": "manual"}}
], "custom-docs")
```

### Execute RAG for a question
```
execute("How do I deploy this?", "rag-demo", top_k=5, min_score=0.2)
```

### Monitor a large ingest
```
job = ingest(large_document_list, "archive")
# job.job_id is returned
status = get_job_status(job.job_id)
# Poll until status.status == "done"
```

---

## Troubleshooting

| Issue | Cause | Fix |
|---|---|---|
| "The collection 'X' is empty" | No documents ingested | Call `seed_demo()` or `ingest()` |
| "No documents scored ≥ 0.2" | Query not matching stored docs | Lower `min_score` parameter or rephrase query |
| Status 401 Unauthorized | Invalid/missing JWT | Ensure Bearer token is passed via Authorization header |
| "Requires one of roles: [developer]" | User lacks role | Assign `developer` or `admin` realm role in Keycloak |
| Ingest timing out | Ollama embedding slow | Check Ollama health; consider smaller batch size |
| Job status "failed" | Background task error | Check server logs; try again with fewer documents |

---

## Health Endpoint

`GET /health` returns:
```json
{
  "status": "ok",
  "server": "mcp-rag-server",
  "auth": "enabled | disabled",
  "async_threshold": 50,
  "job_store": "redis | in-memory",
  "embedding": {
    "provider": "ollama | default",
    "model": "qwen2.5:1.5b"
  },
  "collections": 2,
  "total_documents": 42
}
```
