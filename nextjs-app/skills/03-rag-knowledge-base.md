# RAG Knowledge Base Tools

All tools below are from the `rag` MCP server.
They use the caller's JWT for access control and job ownership.

## Tool reference

| Tool | Auth required | Returns |
|---|---|---|
| `list_collections()` | any | `{collections:[{name, count}], total}` |
| `seed_demo(collection)` | developer/admin | `{seeded, collection, example_queries}` |
| `ingest(documents, collection)` | developer/admin | Sync: `{indexed, total}` OR Async: `{job_id, status:"running"}` |
| `search(query, collection, top_k, min_score)` | any | `{results:[{id,content,score,metadata}], count}` |
| `execute(query, collection, top_k, min_score)` | any | Formatted Markdown context string |
| `delete(collection, doc_ids?)` | developer/admin | `{deleted, operation}` |
| `get_job_status(job_id)` | job owner | `{status, progress, result, error}` |
| `list_my_jobs()` | any | List of the caller's recent jobs |

## Standard RAG workflow

```
1. list_collections()                        → what exists?
2. (if rag-demo is empty) seed_demo("rag-demo") → seed project docs
3. execute("user question", "rag-demo")      → retrieve context
4. Answer using ONLY the retrieved context
```

## When to use RAG (mandatory)

Call `execute()` BEFORE answering questions about:
- JWT, Keycloak, OIDC, PKCE, JWKS
- MCP protocol, FastMCP, tool servers
- RAG, ChromaDB, embeddings
- Ollama, LLM models
- Project architecture, skill files, deployment

Do NOT answer from memory for these topics. Retrieved context is ground truth.

## User identity in RAG operations

**Before ingest or delete**, verify USER_ROLES:
```
if "developer" not in USER_ROLES and "admin" not in USER_ROLES:
    → Tell the user they need developer/admin role, do not call the tool
```

**When ingest returns a job_id** (>50 documents):
1. Tell the user: `"Indexing {n} documents in the background. Job: {job_id}"`
2. Do NOT call ingest again — the job is already running
3. Offer to poll: `"Shall I check the status? Use get_job_status('{job_id}')`
4. When status=done, report `result.indexed` and `result.total`

**Job ownership:** Only the user who started a job can view it.
`list_my_jobs()` returns jobs scoped to `USER_SUB` (the JWT `sub` claim).

## Ingest document format

```json
[
  {
    "id": "unique-doc-id",
    "content": "Full text to index...",
    "metadata": {"source": "wiki", "date": "2026-01-01", "topic": "auth"}
  }
]
```
- `id` is used for upsert dedup — same ID = update existing doc
- `metadata` is optional; empty `{}` is treated as no metadata
- `content` is embedded via Ollama (qwen2.5:1.5b, 1536 dims, cosine similarity)

## Interpreting execute() output

The context block starts with `## Retrieved context for: {query}`.
Each document shows its ID, cosine similarity score, and optionally source/date.
A score > 0.6 indicates high relevance. Use min_score=0.4 for broader recall.
