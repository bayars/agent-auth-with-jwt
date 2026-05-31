"""
ChromaDB-backed vector store for the RAG tool server.

Provides a thin, async-friendly wrapper over ChromaDB with:
  - Collection-scoped document storage
  - Ollama embedding function (qwen2.5:1.5b by default)
  - Fallback to ChromaDB ONNX default embedding when Ollama is unavailable
  - Optional persistent storage via CHROMA_PERSIST_PATH
"""

import logging
import os
from typing import Any

import chromadb
import chromadb.api
from chromadb.config import Settings

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.0.224:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "qwen2.5:1.5b")
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "ollama")  # "ollama" | "default"
CHROMA_PERSIST_PATH = os.environ.get("CHROMA_PERSIST_PATH", "")
DEFAULT_COLLECTION = "default"
MAX_RESULTS = int(os.environ.get("MAX_SEARCH_RESULTS", "20"))


def _make_embedding_function():
    if EMBEDDING_PROVIDER == "ollama":
        from chromadb.utils.embedding_functions.ollama_embedding_function import (
            OllamaEmbeddingFunction,
        )
        logger.info(
            "Using Ollama embedding function: model=%s url=%s",
            OLLAMA_EMBED_MODEL, OLLAMA_URL,
        )
        return OllamaEmbeddingFunction(
            url=f"{OLLAMA_URL}/api/embeddings",
            model_name=OLLAMA_EMBED_MODEL,
        )
    else:
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import (
            ONNXMiniLM_L6_V2,
        )
        logger.info("Using built-in ONNX embedding function (all-MiniLM-L6-v2)")
        return ONNXMiniLM_L6_V2()


def _make_client() -> chromadb.Client:
    if CHROMA_PERSIST_PATH:
        logger.info("Persistent ChromaDB at %s", CHROMA_PERSIST_PATH)
        return chromadb.PersistentClient(
            path=CHROMA_PERSIST_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
    logger.info("In-memory ChromaDB (data lost on restart; set CHROMA_PERSIST_PATH to persist)")
    return chromadb.EphemeralClient(
        settings=Settings(anonymized_telemetry=False)
    )


# ── Module-level singletons ───────────────────────────────────────────────────
_client: chromadb.api.ClientAPI | None = None
_ef = None


def get_client() -> chromadb.api.ClientAPI:
    global _client
    if _client is None:
        _client = _make_client()
    return _client


def get_ef():
    global _ef
    if _ef is None:
        _ef = _make_embedding_function()
    return _ef


def get_or_create_collection(name: str) -> chromadb.Collection:
    return get_client().get_or_create_collection(
        name=name,
        embedding_function=get_ef(),
        metadata={"hnsw:space": "cosine"},
    )


# ── CRUD operations ───────────────────────────────────────────────────────────

def ingest(
    documents: list[str],
    ids: list[str],
    metadatas: list[dict] | None = None,
    collection: str = DEFAULT_COLLECTION,
) -> int:
    """Add or update documents. Returns number of documents upserted."""
    col = get_or_create_collection(collection)
    # ChromaDB 1.5+ rejects empty dicts — ensure every metadata entry is non-empty
    raw = metadatas or [{} for _ in ids]
    clean: list[dict | None] = [m if m else None for m in raw]
    col.upsert(
        documents=documents,
        ids=ids,
        metadatas=clean,  # type: ignore[arg-type]
    )
    return len(ids)


def search(
    query: str,
    collection: str = DEFAULT_COLLECTION,
    top_k: int = 5,
    where: dict | None = None,
) -> list[dict[str, Any]]:
    """Semantic search. Returns ranked list of {id, content, score, metadata}."""
    top_k = min(top_k, MAX_RESULTS)
    try:
        col = get_client().get_collection(collection, embedding_function=get_ef())
    except Exception:
        return []

    count = col.count()
    if count == 0:
        return []

    n = min(top_k, count)
    kwargs: dict[str, Any] = {"query_texts": [query], "n_results": n}
    if where:
        kwargs["where"] = where

    results = col.query(**kwargs)
    out = []
    for i in range(len(results["ids"][0])):
        out.append({
            "id": results["ids"][0][i],
            "content": results["documents"][0][i],
            "score": 1.0 - results["distances"][0][i],  # cosine sim: 1 - distance
            "metadata": (results["metadatas"] or [[{}] * n])[0][i],
        })
    return out


def delete_documents(doc_ids: list[str], collection: str = DEFAULT_COLLECTION) -> int:
    """Delete specific documents by ID. Returns number deleted."""
    try:
        col = get_client().get_collection(collection, embedding_function=get_ef())
    except Exception:
        return 0
    col.delete(ids=doc_ids)
    return len(doc_ids)


def delete_collection(name: str) -> bool:
    """Delete an entire collection. Returns True if existed."""
    try:
        get_client().delete_collection(name)
        return True
    except Exception:
        return False


def list_collections() -> list[dict]:
    """List all collections with their document counts."""
    cols = get_client().list_collections()
    out = []
    for c in cols:
        try:
            full = get_client().get_collection(c.name, embedding_function=get_ef())
            out.append({"name": c.name, "count": full.count()})
        except Exception:
            out.append({"name": c.name, "count": -1})
    return out


def collection_count(name: str) -> int:
    """Document count for a collection, or 0 if it doesn't exist."""
    try:
        col = get_client().get_collection(name, embedding_function=get_ef())
        return col.count()
    except Exception:
        return 0
