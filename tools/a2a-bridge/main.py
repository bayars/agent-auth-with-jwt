"""
MCP Tool Server: A2A Bridge

Exposes three MCP tools that allow OpenCode's LLM to discover and delegate
tasks to A2A-compatible agents without speaking A2A directly.

A2A (Agent-to-Agent) protocol basics:
  - Agent Card: GET /.well-known/agent.json  → describes the agent's skills
  - Task submission: POST /a2a              → JSON-RPC 2.0 tasks/send
  - Task polling:    POST /a2a              → JSON-RPC 2.0 tasks/get

Implements A2A protocol directly with httpx (no a2a-sdk dependency).
JWT forwarding: reads the caller's Bearer token from the MCP context and
passes it to the target A2A agent unchanged.

Tools:
  list_a2a_agents   — discover available agents and their skills
  a2a_delegate      — submit a task and wait for the result
  a2a_task_status   — check status of a previously submitted task
"""

import asyncio
import json
import logging
import os
import uuid

import httpx
import uvicorn
from fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.routing import Route

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8000))
# JSON array of A2A agent base URLs, e.g. ["http://mcp-rag-server:8000","http://fastmcp:8000"]
AGENT_REGISTRY: list[str] = json.loads(os.environ.get("AGENT_REGISTRY", "[]"))
# How long to wait for a task to complete before giving up (seconds)
DELEGATE_TIMEOUT = int(os.environ.get("DELEGATE_TIMEOUT_SECONDS", "300"))
# Polling interval for long-running tasks (seconds)
POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL_SECONDS", "3"))
# Per-request HTTP timeout
HTTP_TIMEOUT = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "30"))


# ── FastMCP server ─────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="A2A Bridge",
    instructions=(
        "Bridge between OpenCode (MCP) and A2A-compatible agents. "
        "Use list_a2a_agents() to discover available agents, "
        "then a2a_delegate() to run a task on a specific agent."
    ),
)


# ── JWT forwarding ─────────────────────────────────────────────────────────────

def _auth_headers() -> dict[str, str]:
    """
    Extract the caller's JWT from the MCP context and return it as an
    Authorization header to forward to the target A2A agent.
    Returns {} in dev mode (no auth configured on the bridge).
    """
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
        if token and hasattr(token, "raw_token"):
            return {"Authorization": f"Bearer {token.raw_token}"}
    except Exception:
        pass
    return {}


# ── A2A client helpers ─────────────────────────────────────────────────────────

async def _fetch_agent_card(client: httpx.AsyncClient, base_url: str) -> dict | None:
    """Fetch the Agent Card from /.well-known/agent.json."""
    try:
        url = base_url.rstrip("/") + "/.well-known/agent.json"
        r = await client.get(url, timeout=HTTP_TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception as exc:
        logger.warning("Could not fetch agent card from %s: %s", base_url, exc)
    return None


async def _a2a_rpc(
    client: httpx.AsyncClient,
    base_url: str,
    method: str,
    params: dict,
    extra_headers: dict | None = None,
) -> dict:
    """Send a JSON-RPC 2.0 request to the agent's /a2a endpoint."""
    url = base_url.rstrip("/") + "/a2a"
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
    r = await client.post(url, json=body, headers=headers, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"A2A error {data['error'].get('code')}: {data['error'].get('message')}")
    return data.get("result", {})


def _extract_text(task_result: dict) -> str:
    """Pull text from the first text artifact part of a completed task."""
    for artifact in task_result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("type") == "text":
                return part["text"]
    return ""


def _extract_data(task_result: dict) -> dict | list | None:
    """Pull data from the first data artifact part of a completed task."""
    for artifact in task_result.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("type") == "data":
                return part.get("data")
    return None


def _task_state(task_result: dict) -> str:
    return task_result.get("status", {}).get("state", "unknown")


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_a2a_agents() -> list[dict]:
    """
    Discover all registered A2A agents and their skills.

    Fetches the Agent Card (/.well-known/agent.json) from each URL in the
    AGENT_REGISTRY environment variable and returns a summary.

    Returns a list of agents, each with:
        name        (str)   agent's human-readable name
        url         (str)   agent's base URL
        description (str)   what the agent does
        skills      (list)  each skill: {id, name, description, inputModes, outputModes}
        available   (bool)  false if the agent card could not be fetched
    """
    async with httpx.AsyncClient() as client:
        cards = await asyncio.gather(
            *[_fetch_agent_card(client, url) for url in AGENT_REGISTRY],
            return_exceptions=True,
        )

    result = []
    for url, card in zip(AGENT_REGISTRY, cards):
        if isinstance(card, dict):
            result.append({
                "name": card.get("name", url),
                "url": url,
                "description": card.get("description", ""),
                "version": card.get("version", ""),
                "skills": [
                    {
                        "id": s.get("id"),
                        "name": s.get("name", s.get("id")),
                        "description": s.get("description", ""),
                        "input_modes": s.get("inputModes", ["text"]),
                        "output_modes": s.get("outputModes", ["text"]),
                        "tags": s.get("tags", []),
                    }
                    for s in card.get("skills", [])
                ],
                "capabilities": card.get("capabilities", {}),
                "authentication": card.get("authentication", {}),
                "available": True,
            })
        else:
            result.append({
                "name": url,
                "url": url,
                "description": "Agent card could not be fetched",
                "skills": [],
                "available": False,
                "error": str(card) if isinstance(card, Exception) else "unknown",
            })
    return result


@mcp.tool()
async def a2a_delegate(
    agent_url: str,
    skill_id: str,
    message: str,
    task_id: str | None = None,
) -> dict:
    """
    Submit a task to an A2A agent and wait for the result.

    For short tasks (state=completed immediately): returns the result text.
    For long-running tasks (state=working, e.g. large document ingest):
    polls every few seconds until done or DELEGATE_TIMEOUT_SECONDS is reached.

    The caller's JWT is forwarded to the target agent so it can enforce
    its own role-based access control.

    Args:
        agent_url:  Base URL of the A2A agent (from list_a2a_agents output)
        skill_id:   The skill to invoke (from the agent's skills list)
        message:    Natural-language message / instruction for the skill
        task_id:    Optional: provide a specific task ID (default: auto-generated UUID)

    Returns:
        task_id     (str)   the task identifier (use with a2a_task_status to poll)
        status      (str)   "completed", "failed", "working", or "canceled"
        result_text (str)   text content from the agent's response (if any)
        result_data (any)   structured data from the agent (if any)
        agent_url   (str)   which agent handled the task
        skill_id    (str)   which skill was invoked
    """
    tid = task_id or str(uuid.uuid4())
    auth = _auth_headers()

    params = {
        "id": tid,
        "skill_id": skill_id,
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": message}],
        },
    }

    async with httpx.AsyncClient() as client:
        task = await _a2a_rpc(client, agent_url, "tasks/send", params, extra_headers=auth)
        state = _task_state(task)
        logger.info("A2A task %s submitted to %s/%s → state=%s", tid, agent_url, skill_id, state)

        # Poll until terminal state
        elapsed = 0.0
        while state == "working" and elapsed < DELEGATE_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            task = await _a2a_rpc(
                client, agent_url, "tasks/get",
                {"id": tid}, extra_headers=auth,
            )
            state = _task_state(task)
            progress = task.get("status", {}).get("progress", 0)
            logger.info("A2A task %s: state=%s progress=%s", tid, state, progress)

    result_text = _extract_text(task)
    result_data = _extract_data(task)
    error = task.get("status", {}).get("message", "")

    return {
        "task_id": tid,
        "status": state,
        "result_text": result_text,
        "result_data": result_data,
        "error": error if state == "failed" else None,
        "agent_url": agent_url,
        "skill_id": skill_id,
    }


@mcp.tool()
async def a2a_task_status(agent_url: str, task_id: str) -> dict:
    """
    Check the current status of a previously submitted A2A task.

    Use this when a2a_delegate returned status="working" and you want to
    poll for completion later without waiting inline.

    Args:
        agent_url:  Base URL of the A2A agent that received the task
        task_id:    Task ID returned by a2a_delegate

    Returns:
        task_id     (str)   the task identifier
        status      (str)   "pending", "working", "completed", "failed", "canceled"
        progress    (int)   0–100 percent complete (if the agent reports it)
        result_text (str)   text content (if status=completed)
        result_data (any)   structured data (if status=completed)
        error       (str)   failure reason (if status=failed)
    """
    auth = _auth_headers()
    async with httpx.AsyncClient() as client:
        task = await _a2a_rpc(
            client, agent_url, "tasks/get",
            {"id": task_id}, extra_headers=auth,
        )

    state = _task_state(task)
    progress = task.get("status", {}).get("progress", 0)

    return {
        "task_id": task_id,
        "status": state,
        "progress": progress,
        "result_text": _extract_text(task) if state == "completed" else "",
        "result_data": _extract_data(task) if state == "completed" else None,
        "error": task.get("status", {}).get("message", "") if state == "failed" else None,
    }


# ── Health endpoint ────────────────────────────────────────────────────────────

async def health(_):
    return JSONResponse({
        "status": "ok",
        "server": "mcp-a2a-bridge",
        "registered_agents": len(AGENT_REGISTRY),
        "agent_urls": AGENT_REGISTRY,
    })


# ── Entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = mcp.http_app(transport="streamable-http")
    app.routes.insert(0, Route("/health", health))
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
