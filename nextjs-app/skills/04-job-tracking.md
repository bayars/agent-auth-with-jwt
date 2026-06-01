# Long-Running Job Tracking

Some tools (large RAG ingest, >50 documents) run in the background to avoid
MCP client timeouts. They return a `job_id` immediately.

## Tools (from `rag` MCP server)

| Tool | Description |
|---|---|
| `get_job_status(job_id)` | Returns current state of a background job |
| `list_my_jobs()` | Returns all jobs owned by the current user (last hour) |

## Job status schema

```json
{
  "job_id":     "uuid",
  "status":     "pending | running | done | failed",
  "progress":   0,          // 0-100 percent
  "tool":       "ingest",
  "result":     {},         // present when status=done
  "error":      "",         // present when status=failed
  "created_at": "2026-01-01T12:00:00Z",
  "updated_at": "2026-01-01T12:00:05Z"
}
```

## Handling a returned job_id

When any tool returns `{job_id, status: "running"}`:

1. **Acknowledge immediately**: `"Your {n} documents are being indexed. Job ID: {job_id}"`
2. **Do not re-call the tool** — the job is already running
3. **Offer to poll**: `"Shall I check progress? I'll call get_job_status."`
4. **Poll once after ~10 seconds**:
   ```
   status = get_job_status("{job_id}")
   ```
5. **Report progress**: `"Progress: {progress}% — still running."`
6. **When done**: `"Indexing complete! {result.indexed} documents added, {result.total} total in collection."`
7. **On failure**: `"The job failed: {error}. Try again with a smaller batch or check Ollama availability."`

## Job ownership

Jobs are stored with `user_sub` (the JWT `sub` claim).
`get_job_status(job_id)` returns "not found" for jobs owned by other users.
`list_my_jobs()` only shows the current user's jobs — this is enforced server-side.

## Job TTL

Jobs expire after 1 hour (configurable via `JOB_TTL_SECONDS` env var).
`list_my_jobs()` only shows jobs created within the TTL window.
