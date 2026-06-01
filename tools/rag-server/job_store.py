"""
Job store for long-running MCP tool operations.

Uses Redis when REDIS_URL is set; falls back to an in-memory dict otherwise.
Jobs are scoped by user_sub (JWT subject claim) so users only see their own jobs.

Job lifecycle:
  pending  → created but not yet started
  running  → background task in progress (progress 0-100)
  done     → completed; result contains JSON-encoded output
  failed   → error contains the failure message

TTL: jobs expire after JOB_TTL_SECONDS (default 3600 = 1 hour).
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get("REDIS_URL", "")
JOB_TTL = int(os.environ.get("JOB_TTL_SECONDS", "3600"))


# ── In-memory fallback ─────────────────────────────────────────────────────────

class _MemoryStore:
    """Thread-safe in-memory job store for dev/single-process use.

    TTL is enforced: keys older than their TTL are evicted on next access or scan.
    """

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        # Maps key → expiry timestamp (seconds since epoch). -1 = no expiry.
        self._expiry: dict[str, float] = {}
        self._lock = asyncio.Lock()

    def _is_expired(self, key: str) -> bool:
        exp = self._expiry.get(key, -1)
        return exp != -1 and time.monotonic() > exp

    async def hset(self, key: str, mapping: dict) -> None:
        async with self._lock:
            existing = self._jobs.get(key, {})
            existing.update(mapping)
            self._jobs[key] = existing

    async def hgetall(self, key: str) -> dict:
        async with self._lock:
            if self._is_expired(key):
                self._jobs.pop(key, None)
                self._expiry.pop(key, None)
                return {}
            return dict(self._jobs.get(key, {}))

    async def expire(self, key: str, seconds: int) -> None:
        async with self._lock:
            self._expiry[key] = time.monotonic() + seconds

    async def keys(self, pattern: str) -> list[str]:
        async with self._lock:
            prefix = pattern.rstrip("*")
            now = time.monotonic()
            expired = [
                k for k, exp in self._expiry.items()
                if exp != -1 and now > exp
            ]
            for k in expired:
                self._jobs.pop(k, None)
                self._expiry.pop(k, None)
            return [k for k in self._jobs if k.startswith(prefix)]

    async def close(self) -> None:
        pass


# ── Redis backend ──────────────────────────────────────────────────────────────

class _RedisStore:
    def __init__(self, url: str):
        import redis.asyncio as aioredis
        self._client = aioredis.from_url(url, decode_responses=True)

    async def hset(self, key: str, mapping: dict) -> None:
        await self._client.hset(key, mapping=mapping)

    async def hgetall(self, key: str) -> dict:
        return await self._client.hgetall(key)

    async def expire(self, key: str, seconds: int) -> None:
        await self._client.expire(key, seconds)

    async def keys(self, pattern: str) -> list[str]:
        return await self._client.keys(pattern)

    async def close(self) -> None:
        await self._client.aclose()


# ── JobStore public API ────────────────────────────────────────────────────────

class JobStore:
    """Async job store backed by Redis or in-memory fallback."""

    def __init__(self):
        if REDIS_URL:
            logger.info("JobStore: using Redis at %s", REDIS_URL)
            self._backend = _RedisStore(REDIS_URL)
        else:
            logger.warning(
                "JobStore: REDIS_URL not set — using in-memory store. "
                "Jobs will be lost on process restart."
            )
            self._backend = _MemoryStore()

    def _key(self, job_id: str) -> str:
        return f"job:{job_id}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    async def create(
        self,
        user_sub: str,
        tool: str,
        args_summary: str = "",
        job_id: str | None = None,
    ) -> str:
        """Create a new job and return its job_id.

        Pass job_id explicitly to use a caller-supplied identifier (e.g. an A2A
        task_id) so that the same ID can be used for both job tracking and A2A
        tasks/get polling without any additional mapping.
        """
        job_id = job_id or str(uuid.uuid4())
        mapping = {
            "job_id": job_id,
            "user_sub": user_sub,
            "tool": tool,
            "args_summary": args_summary[:200],
            "status": "pending",
            "progress": "0",
            "result": "",
            "error": "",
            "created_at": self._now(),
            "updated_at": self._now(),
        }
        key = self._key(job_id)
        await self._backend.hset(key, mapping)
        await self._backend.expire(key, JOB_TTL)
        logger.info("Job created: %s tool=%s user=%s", job_id, tool, user_sub[:8])
        return job_id

    async def update(self, job_id: str, **fields: Any) -> None:
        """Update one or more fields on an existing job."""
        if not fields:
            return
        # Serialise non-string values
        serialised = {
            k: json.dumps(v) if not isinstance(v, (str, int, float)) else str(v)
            for k, v in fields.items()
        }
        serialised["updated_at"] = self._now()
        key = self._key(job_id)
        await self._backend.hset(key, serialised)
        await self._backend.expire(key, JOB_TTL)

    async def get(self, job_id: str) -> dict | None:
        """Fetch a job by ID. Returns None if not found."""
        raw = await self._backend.hgetall(self._key(job_id))
        if not raw:
            return None
        return self._deserialise(raw)

    async def list_for_user(self, user_sub: str) -> list[dict]:
        """Return all jobs owned by user_sub, newest first."""
        all_keys = await self._backend.keys("job:*")
        jobs = []
        for key in all_keys:
            raw = await self._backend.hgetall(key)
            if raw and raw.get("user_sub") == user_sub:
                jobs.append(self._deserialise(raw))
        # Sort by created_at descending
        jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
        return jobs

    def _deserialise(self, raw: dict) -> dict:
        """Convert Redis string values back to typed Python values."""
        out = dict(raw)
        # Parse result/error from JSON if set
        for field in ("result", "error"):
            val = out.get(field, "")
            if val:
                try:
                    out[field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass  # keep as string
        # Convert progress to int
        try:
            out["progress"] = int(out.get("progress", 0))
        except (ValueError, TypeError):
            out["progress"] = 0
        return out

    async def close(self) -> None:
        await self._backend.close()


# ── Module-level singleton ─────────────────────────────────────────────────────
_store: JobStore | None = None


def get_job_store() -> JobStore:
    global _store
    if _store is None:
        _store = JobStore()
    return _store
