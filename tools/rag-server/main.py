"""
MCP Tool Server: RAG (Retrieval-Augmented Generation)

Provides a complete knowledge-base pipeline over ChromaDB + Ollama embeddings.

Authentication:
  When KC_REALM_URL is set, every request must carry a valid Keycloak JWT.
  The 'delete' and 'ingest' operations additionally require the caller to hold
  the 'developer' or 'admin' realm role.
  When KC_REALM_URL is empty (dev mode), auth is disabled entirely.

Tools:
  ingest           — add / update documents in a named collection
  search           — semantic similarity search
  execute          — full RAG pipeline: search → formatted context string
  list_collections — list collections with document counts
  delete           — remove documents or an entire collection (role-gated)
  seed_demo        — populate a collection with sample documents for testing
"""

import os
import logging

import uvicorn
from fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.routing import Route
from pydantic import BaseModel, Field

import store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8000))
KC_REALM_URL = os.environ.get("KC_REALM_URL", "")
KC_ISSUER = os.environ.get("KC_ISSUER", KC_REALM_URL)
FASTMCP_BASE_URL = os.environ.get("FASTMCP_BASE_URL", f"http://mcp-rag-server:{PORT}")
AUTH_ENABLED = bool(KC_REALM_URL)

# ── Auth setup ────────────────────────────────────────────────────────────────

def _build_auth():
    if not AUTH_ENABLED:
        logger.info("Auth DISABLED (KC_REALM_URL not set — dev mode)")
        return None

    from fastmcp.server.auth import TokenVerifier, AccessToken
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier = JWTVerifier(
        jwks_uri=f"{KC_REALM_URL}/protocol/openid-connect/certs",
        issuer=KC_ISSUER,
        algorithm="RS256",
        required_scopes=["openid"],
    )

    class KeycloakVerifier(TokenVerifier):
        def __init__(self):
            super().__init__(base_url=FASTMCP_BASE_URL, required_scopes=["openid"])
        async def verify_token(self, token: str):
            return await verifier.verify_token(token)

    logger.info("Auth ENABLED — JWKS: %s/protocol/openid-connect/certs", KC_REALM_URL)
    return KeycloakVerifier()


auth = _build_auth()

# ── FastMCP server ────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="RAG Tool Server",
    instructions=(
        "Knowledge-base tools for Retrieval-Augmented Generation. "
        "Use 'ingest' to add documents, 'search' for similarity search, "
        "'execute' to get formatted context for a query. "
        f"Auth {'required (Keycloak JWT)' if AUTH_ENABLED else 'disabled (dev mode)'}."
    ),
    auth=auth,
)


# ── Shared helper: get caller roles ──────────────────────────────────────────

def _caller_roles() -> list[str]:
    """Return realm roles from the current JWT, or [] if auth is off."""
    if not AUTH_ENABLED:
        return ["admin"]  # dev mode: unrestricted
    from fastmcp.server.dependencies import get_access_token
    token = get_access_token()
    if token is None:
        return []
    return token.claims.get("realm_access", {}).get("roles", [])


def _require_role(*roles: str) -> None:
    """Raise PermissionError unless the caller holds at least one of the given roles."""
    caller = _caller_roles()
    if not any(r in caller for r in roles):
        raise PermissionError(
            f"This operation requires one of these roles: {list(roles)}. "
            f"Your roles: {caller}"
        )


# ── Pydantic models ───────────────────────────────────────────────────────────

class Document(BaseModel):
    id: str = Field(description="Unique document identifier (used for upsert dedup)")
    content: str = Field(description="Full text content to index")
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata stored alongside the document "
                    "(e.g. source, author, date, url)",
    )


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def ingest(
    documents: list[Document],
    collection: str = "default",
) -> dict:
    """
    Add or update documents in the knowledge base.

    Documents are embedded using Ollama and stored in ChromaDB under the given
    collection name. Existing documents with the same `id` are replaced (upsert).

    Auth: requires 'developer' or 'admin' role when auth is enabled.

    Args:
        documents:  List of document objects — each needs an 'id' and 'content'.
                    Optional 'metadata' dict (source, author, date, url, …).
        collection: Collection name to store into (default "default").
                    Creates the collection if it doesn't exist.

    Returns:
        indexed     (int)  documents added/updated
        collection  (str)  target collection name
        total       (int)  total documents in the collection after ingest
    """
    _require_role("developer", "admin")

    indexed = store.ingest(
        documents=[d.content for d in documents],
        ids=[d.id for d in documents],
        metadatas=[d.metadata for d in documents],
        collection=collection,
    )
    total = store.collection_count(collection)
    return {"indexed": indexed, "collection": collection, "total": total}


@mcp.tool()
async def search(
    query: str,
    collection: str = "default",
    top_k: int = 5,
    min_score: float = 0.0,
) -> dict:
    """
    Semantic similarity search over a document collection.

    Embeds the query using the same embedding model as ingest and returns the
    most similar documents ranked by cosine similarity.

    Args:
        query:      Natural-language search query
        collection: Collection to search (default "default")
        top_k:      Maximum number of results to return (default 5, max 20)
        min_score:  Minimum similarity score threshold 0.0–1.0 (default 0.0)

    Returns:
        query       (str)         the original query
        collection  (str)         collection searched
        results     (list)        ranked results, each with:
                      id       (str)   document id
                      content  (str)   document text
                      score    (float) cosine similarity 0–1 (higher = more similar)
                      metadata (dict)  stored metadata
        count       (int)         number of results returned
    """
    raw = store.search(query=query, collection=collection, top_k=top_k)
    filtered = [r for r in raw if r["score"] >= min_score]
    return {
        "query": query,
        "collection": collection,
        "results": filtered,
        "count": len(filtered),
    }


@mcp.tool()
async def execute(
    query: str,
    collection: str = "default",
    top_k: int = 5,
    min_score: float = 0.2,
) -> str:
    """
    Full RAG execution: search the knowledge base and return formatted context.

    This is the primary tool for RAG. It runs a semantic search and formats
    the retrieved documents as a ready-to-use context block. Prepend this
    output to your prompt when asking the LLM a question that requires
    knowledge from the document store.

    Example usage:
      context = execute("how does JWT authentication work?")
      answer  = llm.chat(f"{context}\\n\\nQuestion: how does JWT auth work?")

    Args:
        query:      The question or topic to retrieve context for
        collection: Collection to search (default "default")
        top_k:      Number of documents to retrieve (default 5)
        min_score:  Minimum similarity score; documents below this are excluded
                    (default 0.2 — filters noise)

    Returns a formatted Markdown string with the retrieved context, ready to
    prepend to a prompt. Returns a "no documents found" message if the
    collection is empty or no results pass the score threshold.
    """
    results = store.search(query=query, collection=collection, top_k=top_k)
    relevant = [r for r in results if r["score"] >= min_score]

    if not relevant:
        total = store.collection_count(collection)
        if total == 0:
            return (
                f"The collection '{collection}' is empty. "
                "Use the 'ingest' tool to add documents before searching."
            )
        return (
            f"No documents scored ≥ {min_score} for query: '{query}'. "
            f"Try lowering min_score or rephrasing the query. "
            f"(Collection '{collection}' has {total} documents total.)"
        )

    lines = [
        f"## Retrieved context for: {query}",
        f"*{len(relevant)} document(s) from collection '{collection}'*",
        "",
    ]
    for i, r in enumerate(relevant, 1):
        meta = r["metadata"]
        source_hint = ""
        if meta.get("source"):
            source_hint = f" · source: {meta['source']}"
        if meta.get("date"):
            source_hint += f" · {meta['date']}"
        lines.append(f"### [{i}] {r['id']}  (score: {r['score']:.3f}{source_hint})")
        lines.append("")
        lines.append(r["content"].strip())
        lines.append("")

    lines += [
        "---",
        "*End of retrieved context. Use the above to answer the question.*",
    ]
    return "\n".join(lines)


@mcp.tool()
async def list_collections() -> dict:
    """
    List all document collections with their document counts.

    No auth required — this is a read-only metadata operation.

    Returns:
        collections  list of {name, count} objects
        total        total number of collections
    """
    cols = store.list_collections()
    return {"collections": cols, "total": len(cols)}


@mcp.tool()
async def delete(
    collection: str,
    doc_ids: list[str] | None = None,
) -> dict:
    """
    Delete documents from a collection, or delete the entire collection.

    Auth: requires 'developer' or 'admin' role when auth is enabled.

    Args:
        collection: Collection name to operate on
        doc_ids:    List of document IDs to delete. If omitted or null,
                    the ENTIRE collection is deleted (irreversible).

    Returns:
        deleted     (int)   number of items removed
        collection  (str)   affected collection
        operation   (str)   "documents" or "collection"
    """
    _require_role("developer", "admin")

    if doc_ids:
        n = store.delete_documents(doc_ids, collection)
        return {"deleted": n, "collection": collection, "operation": "documents"}
    else:
        existed = store.delete_collection(collection)
        return {
            "deleted": 1 if existed else 0,
            "collection": collection,
            "operation": "collection",
        }


@mcp.tool()
async def seed_demo(collection: str = "rag-demo") -> dict:
    """
    Populate a demo collection with sample documents about this project.

    Useful for quickly testing the RAG pipeline without ingesting real data.
    Idempotent — running it multiple times replaces documents with the same IDs.

    Args:
        collection: Collection name for the demo data (default "rag-demo")

    Returns the number of documents seeded and example queries to try.
    """
    _require_role("developer", "admin")

    docs = [
        Document(
            id="jwt-basics",
            content=(
                "JSON Web Tokens (JWT) are a compact, URL-safe means of representing "
                "claims transferred between two parties. A JWT consists of three "
                "Base64URL-encoded parts separated by dots: Header.Payload.Signature. "
                "The header specifies the algorithm (typically RS256 or HS256). "
                "The payload contains claims such as sub (subject), exp (expiration), "
                "iss (issuer), and arbitrary custom claims. The signature is computed "
                "by the server using a private key and verified by clients using the "
                "corresponding public key or JWKS endpoint."
            ),
            metadata={"source": "project-docs", "topic": "auth"},
        ),
        Document(
            id="keycloak-overview",
            content=(
                "Keycloak is an open-source Identity and Access Management solution. "
                "It supports OIDC, OAuth 2.0, and SAML 2.0. Key concepts: "
                "Realms isolate groups of users and applications. "
                "Clients are applications that request tokens from Keycloak. "
                "PKCE (Proof Key for Code Exchange) is the recommended flow for public "
                "clients such as Single Page Applications. "
                "Keycloak exposes a JWKS endpoint at "
                "/realms/{realm}/protocol/openid-connect/certs that allows "
                "resource servers to verify JWT signatures without calling Keycloak."
            ),
            metadata={"source": "project-docs", "topic": "auth"},
        ),
        Document(
            id="mcp-protocol",
            content=(
                "The Model Context Protocol (MCP) is an open protocol for connecting "
                "LLMs to external tools and data sources. "
                "An MCP server exposes tools (callable functions), resources (readable "
                "data), and prompts (reusable templates). "
                "The streamable-HTTP transport uses JSON-RPC 2.0 over HTTP POST with "
                "Server-Sent Events for streaming responses. "
                "Clients must include Accept: application/json, text/event-stream "
                "and obtain a session ID via an initialize request. "
                "FastMCP is a Python framework that makes building MCP servers simple "
                "using function decorators."
            ),
            metadata={"source": "project-docs", "topic": "mcp"},
        ),
        Document(
            id="rag-concept",
            content=(
                "Retrieval-Augmented Generation (RAG) is a technique that improves "
                "LLM responses by retrieving relevant documents from a knowledge base "
                "and including them in the prompt as context. "
                "The pipeline has three stages: "
                "1) Retrieval — embed the user query and find semantically similar "
                "documents using vector similarity (cosine or dot-product). "
                "2) Augmentation — prepend the retrieved documents to the user query. "
                "3) Generation — the LLM generates a response grounded in the context. "
                "RAG reduces hallucinations and allows LLMs to answer questions about "
                "proprietary or up-to-date information."
            ),
            metadata={"source": "project-docs", "topic": "rag"},
        ),
        Document(
            id="fastmcp-tools",
            content=(
                "FastMCP tools are Python async functions decorated with @mcp.tool(). "
                "Parameters become the tool's JSON Schema input. "
                "Supported types: str, int, float, bool, list, dict, Pydantic models. "
                "Return values are wrapped in MCP TextContent: "
                "str returns are used as-is; dict/list are JSON-serialised. "
                "Dependency injection is done via default-value sentinels: "
                "CurrentAccessToken() injects the validated JWT AccessToken, "
                "TokenClaim('claim_name') injects a single claim value. "
                "Raise exceptions for errors; they become MCP isError=true results."
            ),
            metadata={"source": "project-docs", "topic": "mcp"},
        ),
        Document(
            id="ollama-setup",
            content=(
                "Ollama is a tool for running large language models locally. "
                "It exposes an OpenAI-compatible API at /v1/chat/completions "
                "and a native API at /api/generate and /api/embeddings. "
                "Models available in this deployment: qwen2.5-coder:14b (coding), "
                "qwen2.5:1.5b (fast, small), qwen3:8b (general), llama3.1:8b (general). "
                "The embedding API accepts any model and returns a float array. "
                "qwen2.5:1.5b produces 1536-dimensional embeddings suitable for RAG."
            ),
            metadata={"source": "project-docs", "topic": "llm"},
        ),
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


# ── Health endpoint (no auth) ─────────────────────────────────────────────────

async def health(_):
    cols = store.list_collections()
    total_docs = sum(c.get("count", 0) for c in cols)
    return JSONResponse({
        "status": "ok",
        "server": "mcp-rag-server",
        "auth": "enabled" if AUTH_ENABLED else "disabled",
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
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
