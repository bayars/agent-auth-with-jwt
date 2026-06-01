"""
MCP Tool Server: RAG (Retrieval-Augmented Generation)

Provides a complete knowledge-base pipeline over ChromaDB + Ollama embeddings.

Authentication:
  When KC_REALM_URL is set, every request must carry a valid Keycloak JWT.
  The 'delete', 'ingest', and 'seed_demo' operations additionally require the
  caller to hold the 'developer' or 'admin' realm role.
  When KC_REALM_URL is empty (dev mode), auth is disabled entirely.

Long-running jobs:
  When ingest is called with more than ASYNC_THRESHOLD documents (default 50),
  it runs in the background and immediately returns a {job_id, status:"running"}.
  Use get_job_status(job_id) to poll progress and retrieve the final result.
  Jobs are stored in Redis (REDIS_URL env var) or in-memory if Redis is not set.
  Jobs are scoped by the caller's JWT sub claim — only the owner can view them.

Tools:
  ingest           — add / update documents (async for large batches)
  search           — semantic similarity search
  execute          — full RAG pipeline: search → formatted context string
  list_collections — list collections with document counts
  delete           — remove documents or an entire collection (role-gated)
  seed_demo        — populate a collection with sample documents for testing
  get_job_status   — poll a background job by job_id
  list_my_jobs     — list the current user's recent background jobs
"""

import asyncio
import json
import logging
import os

import uvicorn
from fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.routing import Route
from pydantic import BaseModel, Field

import store
from job_store import get_job_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8000))
KC_REALM_URL = os.environ.get("KC_REALM_URL", "")
KC_ISSUER = os.environ.get("KC_ISSUER", KC_REALM_URL)
FASTMCP_BASE_URL = os.environ.get("FASTMCP_BASE_URL", f"http://mcp-rag-server:{PORT}")
AUTH_ENABLED = bool(KC_REALM_URL)
# Documents above this threshold are ingested in the background
ASYNC_THRESHOLD = int(os.environ.get("ASYNC_INGEST_THRESHOLD", "50"))

# ── Auth setup ────────────────────────────────────────────────────────────────

_jwt_verifier = None  # module-level; set below when AUTH_ENABLED


def _build_auth():
    global _jwt_verifier

    if not AUTH_ENABLED:
        logger.info("Auth DISABLED (KC_REALM_URL not set — dev mode)")
        return None

    from fastmcp.server.auth import TokenVerifier
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    _jwt_verifier = JWTVerifier(
        jwks_uri=f"{KC_REALM_URL}/protocol/openid-connect/certs",
        issuer=KC_ISSUER,
        algorithm="RS256",
        required_scopes=["openid"],
    )

    class KeycloakVerifier(TokenVerifier):
        def __init__(self):
            super().__init__(base_url=FASTMCP_BASE_URL, required_scopes=["openid"])
        async def verify_token(self, token: str):
            return await _jwt_verifier.verify_token(token)

    logger.info("Auth ENABLED — JWKS: %s/protocol/openid-connect/certs", KC_REALM_URL)
    return KeycloakVerifier()


auth = _build_auth()

# ── FastMCP server ────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="RAG Tool Server",
    instructions=(
        "Knowledge-base tools for Retrieval-Augmented Generation. "
        "Use 'ingest' to add documents (returns job_id for large batches), "
        "'search' for similarity search, 'execute' for full RAG context. "
        "Use 'get_job_status' to check background ingest progress. "
        f"Auth {'required (Keycloak JWT)' if AUTH_ENABLED else 'disabled (dev mode)'}."
    ),
    auth=auth,
)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _caller_sub() -> str:
    """Return the JWT sub claim, or 'anonymous' in dev mode."""
    if not AUTH_ENABLED:
        return "dev-anonymous"
    from fastmcp.server.dependencies import get_access_token
    token = get_access_token()
    return token.claims.get("sub", "unknown") if token else "unknown"


def _caller_roles() -> list[str]:
    """Return realm roles from the current JWT, or ['admin'] in dev mode."""
    if not AUTH_ENABLED:
        return ["admin"]
    from fastmcp.server.dependencies import get_access_token
    token = get_access_token()
    if token is None:
        return []
    return token.claims.get("realm_access", {}).get("roles", [])


def _require_role(*roles: str) -> None:
    caller = _caller_roles()
    if not any(r in caller for r in roles):
        raise PermissionError(
            f"Requires one of roles: {list(roles)}. Your roles: {caller}"
        )


# ── Pydantic models ───────────────────────────────────────────────────────────

class Document(BaseModel):
    id: str = Field(description="Unique document identifier (used for upsert dedup)")
    content: str = Field(description="Full text content to index")
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary metadata: source, author, date, url, …",
    )


# ── Background ingest task ────────────────────────────────────────────────────

async def _ingest_background(
    job_id: str,
    docs: list[Document],
    collection: str,
) -> None:
    """Run a large ingest in the background, updating the job store as it progresses."""
    js = get_job_store()
    total = len(docs)
    batch_size = 10  # embed in batches so we can report progress

    try:
        await js.update(job_id, status="running", progress=0)
        indexed = 0

        for start in range(0, total, batch_size):
            batch = docs[start : start + batch_size]
            store.ingest(
                documents=[d.content for d in batch],
                ids=[d.id for d in batch],
                metadatas=[d.metadata for d in batch],
                collection=collection,
            )
            indexed += len(batch)
            pct = int(indexed / total * 100)
            await js.update(job_id, progress=pct)
            await asyncio.sleep(0)  # yield to event loop

        total_now = store.collection_count(collection)
        result = {"indexed": indexed, "collection": collection, "total": total_now}
        await js.update(job_id, status="done", progress=100, result=json.dumps(result))
        logger.info("Job %s done: indexed %d docs into '%s'", job_id, indexed, collection)

    except Exception as exc:
        logger.error("Job %s failed: %s", job_id, exc)
        await js.update(job_id, status="failed", error=str(exc))


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def ingest(
    documents: list[Document],
    collection: str = "default",
) -> dict:
    """
    Add or update documents in the knowledge base.

    For batches of 50 or fewer documents, ingest runs synchronously and returns
    the result immediately. For larger batches, ingest runs in the background
    and returns a job_id. Poll get_job_status(job_id) to track progress.

    Auth: requires 'developer' or 'admin' role.

    Args:
        documents:  List of {id, content, metadata?} objects to index.
                    Documents with duplicate IDs are updated (upserted).
        collection: Target collection (default "default"). Created if absent.

    Returns (small batch, ≤50 docs):
        indexed (int), collection (str), total (int)

    Returns (large batch, >50 docs):
        job_id (str), status "running", message (str), document_count (int)
    """
    _require_role("developer", "admin")

    if len(documents) <= ASYNC_THRESHOLD:
        # Synchronous path — fast enough to not timeout
        indexed = store.ingest(
            documents=[d.content for d in documents],
            ids=[d.id for d in documents],
            metadatas=[d.metadata for d in documents],
            collection=collection,
        )
        total = store.collection_count(collection)
        return {"indexed": indexed, "collection": collection, "total": total}

    # Asynchronous path — spawn background task
    js = get_job_store()
    user_sub = _caller_sub()
    summary = f"{len(documents)} docs into '{collection}'"
    job_id = await js.create(user_sub=user_sub, tool="ingest", args_summary=summary)

    asyncio.create_task(_ingest_background(job_id, documents, collection))

    return {
        "job_id": job_id,
        "status": "running",
        "document_count": len(documents),
        "message": (
            f"Ingesting {len(documents)} documents in the background. "
            f"Call get_job_status('{job_id}') to track progress."
        ),
    }


@mcp.tool()
async def get_job_status(job_id: str) -> dict:
    """
    Poll the status of a background job (e.g. a large ingest).

    Only the user who created the job can view it. If you pass a job_id that
    belongs to another user you will receive a 'not found' response.

    Args:
        job_id: The job ID returned by ingest when it ran asynchronously.

    Returns a dict with:
        job_id      (str)   the job identifier
        status      (str)   pending | running | done | failed
        progress    (int)   0–100 percent complete
        tool        (str)   which tool created this job
        result      (any)   the tool's output when status=done
        error       (str)   failure reason when status=failed
        created_at  (str)   ISO-8601 timestamp
        updated_at  (str)   ISO-8601 timestamp of last update
    """
    js = get_job_store()
    job = await js.get(job_id)

    if job is None:
        return {"error": "not_found", "job_id": job_id}

    # Enforce ownership
    caller_sub = _caller_sub()
    if AUTH_ENABLED and job.get("user_sub") != caller_sub:
        return {"error": "not_found", "job_id": job_id}  # don't reveal existence

    return job


@mcp.tool()
async def list_my_jobs() -> list[dict]:
    """
    List all background jobs created by the current user (last hour).

    Returns a list ordered from newest to oldest. Each item is the same shape
    as get_job_status(). In dev mode (no auth), returns jobs for 'dev-anonymous'.
    """
    js = get_job_store()
    user_sub = _caller_sub()
    return await js.list_for_user(user_sub)


@mcp.tool()
async def search(
    query: str,
    collection: str = "default",
    top_k: int = 5,
    min_score: float = 0.0,
) -> dict:
    """
    Semantic similarity search over a document collection.

    Args:
        query:      Natural-language search query
        collection: Collection to search (default "default")
        top_k:      Maximum results (default 5, max 20)
        min_score:  Minimum cosine similarity 0.0–1.0 (default 0.0)

    Returns {query, collection, results:[{id, content, score, metadata}], count}.
    """
    raw = store.search(query=query, collection=collection, top_k=top_k)
    filtered = [r for r in raw if r["score"] >= min_score]
    return {"query": query, "collection": collection, "results": filtered, "count": len(filtered)}


@mcp.tool()
async def execute(
    query: str,
    collection: str = "default",
    top_k: int = 5,
    min_score: float = 0.2,
) -> str:
    """
    Full RAG execution: search the knowledge base and return formatted context.

    The primary RAG tool. Searches the collection for documents relevant to the
    query and formats them as a Markdown context block ready to prepend to a
    prompt. The LLM should use ONLY this context when answering — do not guess.

    Args:
        query:      The question or topic to retrieve context for
        collection: Collection to search (default "default")
        top_k:      Number of documents to retrieve (default 5)
        min_score:  Score threshold — lower = broader recall (default 0.2)

    Returns a formatted Markdown context string, or a helpful "empty/no results"
    message when no relevant documents are found.
    """
    results = store.search(query=query, collection=collection, top_k=top_k)
    relevant = [r for r in results if r["score"] >= min_score]

    if not relevant:
        total = store.collection_count(collection)
        if total == 0:
            return (
                f"The collection '{collection}' is empty. "
                "Use 'ingest' or 'seed_demo' to add documents first."
            )
        return (
            f"No documents scored ≥ {min_score} for: '{query}'. "
            f"Collection '{collection}' has {total} docs — try lowering min_score."
        )

    lines = [
        f"## Retrieved context for: {query}",
        f"*{len(relevant)} document(s) from collection '{collection}'*",
        "",
    ]
    for i, r in enumerate(relevant, 1):
        meta = r.get("metadata") or {}
        hints = []
        if meta.get("source"):
            hints.append(f"source: {meta['source']}")
        if meta.get("date"):
            hints.append(meta["date"])
        hint_str = " · ".join(hints)
        if hint_str:
            hint_str = f" · {hint_str}"
        lines.append(f"### [{i}] {r['id']}  (score: {r['score']:.3f}{hint_str})")
        lines.append("")
        lines.append(r["content"].strip())
        lines.append("")

    lines += ["---", "*End of retrieved context. Base your answer on the above.*"]
    return "\n".join(lines)


@mcp.tool()
async def list_collections() -> dict:
    """List all document collections with their document counts."""
    cols = store.list_collections()
    return {"collections": cols, "total": len(cols)}


@mcp.tool()
async def delete(
    collection: str,
    doc_ids: list[str] | None = None,
) -> dict:
    """
    Delete specific documents or an entire collection.

    Auth: requires 'developer' or 'admin' role.

    Args:
        collection: Collection to operate on
        doc_ids:    Document IDs to delete. If omitted, the entire collection
                    is deleted (irreversible).

    Returns {deleted, collection, operation ("documents"|"collection")}.
    """
    _require_role("developer", "admin")
    if doc_ids:
        n = store.delete_documents(doc_ids, collection)
        return {"deleted": n, "collection": collection, "operation": "documents"}
    existed = store.delete_collection(collection)
    return {"deleted": 1 if existed else 0, "collection": collection, "operation": "collection"}


@mcp.tool()
async def seed_demo(collection: str = "rag-demo") -> dict:
    """
    Populate a demo collection with 6 project-specific documents.

    Idempotent — running multiple times replaces documents by ID.
    Auth: requires 'developer' or 'admin' role.

    Args:
        collection: Target collection (default "rag-demo")

    Returns {seeded, collection, example_queries}.
    """
    _require_role("developer", "admin")

    docs = [
        Document(id="jwt-basics", metadata={"source": "project-docs", "topic": "auth"},
            content=(
                "JSON Web Tokens (JWT) are a compact, URL-safe means of representing "
                "claims transferred between two parties. A JWT has three Base64URL parts: "
                "Header.Payload.Signature. The header specifies the algorithm (RS256). "
                "The payload contains claims: sub, exp, iss, given_name, family_name, email, "
                "realm_access.roles. The signature is verified via Keycloak's JWKS endpoint."
            )),
        Document(id="keycloak-overview", metadata={"source": "project-docs", "topic": "auth"},
            content=(
                "Keycloak is an open-source Identity and Access Management solution. "
                "Realms isolate users and apps. Clients request tokens. "
                "PKCE is the recommended flow for public clients (SPAs). "
                "JWKS endpoint: /realms/{realm}/protocol/openid-connect/certs. "
                "Roles: user (read-only), developer (read/write code), admin (unrestricted)."
            )),
        Document(id="mcp-protocol", metadata={"source": "project-docs", "topic": "mcp"},
            content=(
                "The Model Context Protocol (MCP) connects LLMs to external tools. "
                "Servers expose tools (functions), resources (data), prompts (templates). "
                "Streamable-HTTP transport: JSON-RPC 2.0 over POST with SSE streaming. "
                "Clients need Accept: application/json, text/event-stream and a session ID "
                "from initialize. FastMCP builds MCP servers with Python decorators."
            )),
        Document(id="rag-concept", metadata={"source": "project-docs", "topic": "rag"},
            content=(
                "Retrieval-Augmented Generation (RAG) improves LLM responses. "
                "Pipeline: 1) Embed the query → find similar documents (cosine similarity). "
                "2) Prepend retrieved documents to the prompt. "
                "3) LLM generates a response grounded in retrieved context. "
                "RAG reduces hallucinations and enables knowledge from proprietary data."
            )),
        Document(id="fastmcp-tools", metadata={"source": "project-docs", "topic": "mcp"},
            content=(
                "FastMCP tools are async Python functions with @mcp.tool(). "
                "Types: str, int, float, bool, list, dict, Pydantic models → JSON Schema. "
                "CurrentAccessToken() injects the JWT AccessToken with .claims dict. "
                "TokenClaim('name') injects one claim. Raise exceptions for errors. "
                "Large operations return a job_id; use get_job_status to poll."
            )),
        Document(id="ollama-setup", metadata={"source": "project-docs", "topic": "llm"},
            content=(
                "Ollama runs LLMs locally. OpenAI-compatible at /v1/chat/completions. "
                "Embedding API at /api/embeddings (any model). "
                "Available: qwen2.5-coder:14b (coding), qwen2.5:1.5b (embeddings/small), "
                "qwen3:8b (general), llama3.1:8b (general). "
                "qwen2.5:1.5b → 1536-dim cosine embeddings used by this RAG server."
            )),
    ]

    n = store.ingest(
        documents=[d.content for d in docs],
        ids=[d.id for d in docs],
        metadatas=[d.metadata for d in docs],
        collection=collection,
    )
    return {
        "seeded": n,
        "collection": collection,
        "example_queries": [
            "How does JWT authentication work?",
            "What is the MCP protocol?",
            "Explain RAG in simple terms",
            "How do I write a FastMCP tool?",
            "What Ollama models are available?",
        ],
    }


# ── A2A Agent Card ─────────────────────────────────────────────────────────────

_A2A_AGENT_CARD = {
    "name": "RAG Knowledge Base Agent",
    "description": (
        "Semantic search and document ingestion over the project knowledge base. "
        "Answers questions by retrieving the most relevant documents using "
        "Ollama embeddings and ChromaDB cosine similarity."
    ),
    "url": FASTMCP_BASE_URL,
    "version": "1.0.0",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": True,
    },
    "authentication": {
        "schemes": ["bearer"],
        "bearerFormat": "JWT",
        "description": (
            "Keycloak JWT required when KC_REALM_URL is set. "
            "developer or admin realm role needed for ingest_documents."
        ),
    },
    "skills": [
        {
            "id": "knowledge_query",
            "name": "Knowledge Query (RAG)",
            "description": (
                "Search the knowledge base for documents relevant to a question "
                "and return formatted Markdown context ready to prepend to a prompt."
            ),
            "inputModes": ["text"],
            "outputModes": ["text"],
            "tags": ["rag", "search", "knowledge"],
        },
        {
            "id": "knowledge_search",
            "name": "Semantic Search",
            "description": "Return ranked search results with similarity scores and metadata.",
            "inputModes": ["text"],
            "outputModes": ["data"],
            "tags": ["search", "semantic"],
        },
        {
            "id": "ingest_documents",
            "name": "Ingest Documents",
            "description": (
                "Add documents to the knowledge base. "
                "Small batches are synchronous; large batches (>50 docs) are async "
                "and return a task_id in working state — poll tasks/get for completion."
            ),
            "inputModes": ["data"],
            "outputModes": ["data"],
            "tags": ["ingest", "write"],
        },
    ],
}


async def agent_card(_):
    return JSONResponse(_A2A_AGENT_CARD)


# ── A2A JWT verification ───────────────────────────────────────────────────────

async def _a2a_verify_request(request) -> tuple[dict | None, JSONResponse | None]:
    """
    Verify the Bearer JWT on an A2A request.

    Returns (claims, None) on success.
    Returns (None, error_response) when verification fails.

    When AUTH_ENABLED=False (dev mode), returns synthetic claims with admin role
    so the A2A handler can be exercised locally without Keycloak.
    """
    if not AUTH_ENABLED:
        return {"sub": "dev-anonymous", "realm_access": {"roles": ["admin"]}}, None

    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None, JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32001, "message": "Missing Bearer token"}},
            status_code=401,
        )

    token = auth_header[7:]
    try:
        access_token = await _jwt_verifier.verify_token(token)
        return access_token.claims, None
    except Exception as exc:
        return None, JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32001, "message": f"Invalid token: {exc}"}},
            status_code=401,
        )


def _a2a_ok(task_id: str, state: str, text: str = "", data=None, progress: int = 100) -> dict:
    artifacts = []
    if text:
        artifacts.append({"parts": [{"type": "text", "text": text}]})
    if data is not None:
        artifacts.append({"parts": [{"type": "data", "data": data}]})
    return {
        "jsonrpc": "2.0",
        "result": {
            "id": task_id,
            "status": {"state": state, "progress": progress},
            "artifacts": artifacts,
        },
    }


def _a2a_error(task_id: str, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "error": {"code": code, "message": message},
        "result": {"id": task_id, "status": {"state": "failed", "message": message}},
    }


# ── A2A task endpoint ──────────────────────────────────────────────────────────

async def a2a_handler(request):
    """Handle A2A JSON-RPC 2.0 tasks/send and tasks/get."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})

    method = body.get("method", "")
    params = body.get("params", {})
    task_id = params.get("id", "unknown")

    # ── tasks/get ─────────────────────────────────────────────────────────────
    if method == "tasks/get":
        job = await get_job_store().get(task_id)
        if job is None:
            return JSONResponse(_a2a_error(task_id, -32001, "Task not found"))
        status_map = {"pending": "working", "running": "working", "done": "completed", "failed": "failed"}
        a2a_state = status_map.get(job.get("status", ""), "working")
        progress = job.get("progress", 0)
        result = job.get("result") or {}
        text = json.dumps(result) if isinstance(result, dict) and result else ""
        return JSONResponse(_a2a_ok(task_id, a2a_state, text=text, progress=progress))

    # ── tasks/send ────────────────────────────────────────────────────────────
    if method != "tasks/send":
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Unknown method: {method}"}})

    skill_id = params.get("skill_id", "")
    message_parts = params.get("message", {}).get("parts", [])
    message_text = next((p["text"] for p in message_parts if p.get("type") == "text"), "")
    collection = params.get("collection", "rag-demo")

    claims, err_resp = await _a2a_verify_request(request)
    if err_resp:
        return err_resp
    roles = [r for r in (claims.get("realm_access") or {}).get("roles", [])
             if not r.startswith("default-roles-")]
    user_sub = claims.get("sub", "anonymous")

    # ── knowledge_query ───────────────────────────────────────────────────────
    if skill_id == "knowledge_query":
        results = store.search(query=message_text, collection=collection, top_k=5)
        relevant = [r for r in results if r["score"] >= 0.2]
        if not relevant:
            total = store.collection_count(collection)
            text = (
                f"The collection '{collection}' is empty. Ingest documents first."
                if total == 0
                else f"No documents scored ≥ 0.2 for: '{message_text}'. Collection has {total} docs."
            )
        else:
            lines = [f"## Retrieved context for: {message_text}", f"*{len(relevant)} document(s)*", ""]
            for i, r in enumerate(relevant, 1):
                meta = r.get("metadata") or {}
                hint = f" · source: {meta['source']}" if meta.get("source") else ""
                lines += [f"### [{i}] {r['id']}  (score: {r['score']:.3f}{hint})", "", r["content"].strip(), ""]
            lines += ["---", "*End of retrieved context.*"]
            text = "\n".join(lines)
        return JSONResponse(_a2a_ok(task_id, "completed", text=text))

    # ── knowledge_search ──────────────────────────────────────────────────────
    if skill_id == "knowledge_search":
        results = store.search(query=message_text, collection=collection, top_k=10)
        return JSONResponse(_a2a_ok(task_id, "completed", data={"results": results, "count": len(results)}))

    # ── ingest_documents ──────────────────────────────────────────────────────
    if skill_id == "ingest_documents":
        if AUTH_ENABLED and not any(r in roles for r in ("developer", "admin")):
            return JSONResponse(_a2a_error(task_id, -32003, "Requires developer or admin role"))

        # Parse documents from data parts
        data_part = next((p.get("data") for p in message_parts if p.get("type") == "data"), None)
        if not data_part or not isinstance(data_part, list):
            return JSONResponse(_a2a_error(task_id, -32602, "ingest_documents requires a data part with a list of {id, content, metadata}"))

        docs = [Document(**d) if isinstance(d, dict) else d for d in data_part]

        if len(docs) <= ASYNC_THRESHOLD:
            # Synchronous
            n = store.ingest(
                documents=[d.content for d in docs],
                ids=[d.id for d in docs],
                metadatas=[d.metadata for d in docs],
                collection=collection,
            )
            total = store.collection_count(collection)
            return JSONResponse(_a2a_ok(task_id, "completed", data={"indexed": n, "total": total}))
        else:
            # Async — reuse the A2A task_id as the job_id so that tasks/get
            # can look up progress directly via job_store.get(task_id).
            js = get_job_store()
            await js.create(
                user_sub=user_sub,
                tool="a2a:ingest_documents",
                args_summary=f"{len(docs)} docs into '{collection}'",
                job_id=task_id,
            )
            asyncio.create_task(_ingest_background(task_id, docs, collection))
            return JSONResponse(_a2a_ok(task_id, "working", progress=0))

    return JSONResponse(_a2a_error(task_id, -32602, f"Unknown skill_id: {skill_id}"))


# ── Health endpoint (no auth) ─────────────────────────────────────────────────

async def health(_):
    cols = store.list_collections()
    total_docs = sum(c.get("count", 0) for c in cols)
    return JSONResponse({
        "status": "ok",
        "server": "mcp-rag-server",
        "auth": "enabled" if AUTH_ENABLED else "disabled",
        "async_threshold": ASYNC_THRESHOLD,
        "job_store": "redis" if os.environ.get("REDIS_URL") else "in-memory",
        "a2a": "enabled",
        "embedding": {
            "provider": os.environ.get("EMBEDDING_PROVIDER", "ollama"),
            "model": os.environ.get("OLLAMA_EMBED_MODEL", "qwen2.5:1.5b"),
        },
        "collections": len(cols),
        "total_documents": total_docs,
    })


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = mcp.http_app(transport="streamable-http")
    app.routes.insert(0, Route("/health", health))
    app.routes.insert(0, Route("/.well-known/agent.json", agent_card))
    app.routes.insert(0, Route("/a2a", a2a_handler, methods=["POST"]))
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
