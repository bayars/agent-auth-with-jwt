"""
MCP Tool Server: HTTP Caller

Exposes tools for making HTTP requests to external services.
Demonstrates: external I/O, error handling, configurable domain allow-listing.

Tools:
  fetch_url   — generic GET/POST/PUT/DELETE with optional headers and body
  fetch_json  — GET that returns parsed JSON
  post_json   — POST a JSON payload, return parsed response
"""

import json
import os

import httpx
import uvicorn
from fastmcp import FastMCP

# ── Configuration from environment ───────────────────────────────────────────
PORT = int(os.environ.get("PORT", 8000))
TIMEOUT = int(os.environ.get("DEFAULT_TIMEOUT_SECONDS", "30"))
MAX_BODY_BYTES = int(os.environ.get("MAX_RESPONSE_BYTES", str(50_000)))

# Optional domain allowlist: comma-separated, e.g. "httpbin.org,api.example.com"
# Empty string = allow all
_ALLOWED_RAW = os.environ.get("ALLOWED_DOMAINS", "")
ALLOWED_DOMAINS: list[str] = [d.strip() for d in _ALLOWED_RAW.split(",") if d.strip()]


def _check_domain(url: str) -> None:
    """Raise ValueError if the URL's host is not in the allowlist."""
    if not ALLOWED_DOMAINS:
        return
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    if not any(host == d or host.endswith("." + d) for d in ALLOWED_DOMAINS):
        raise ValueError(
            f"Domain '{host}' is not in the allowed list: {ALLOWED_DOMAINS}"
        )


# ── FastMCP server ────────────────────────────────────────────────────────────
mcp = FastMCP(
    name="HTTP Caller",
    instructions=(
        "Tools for making HTTP requests to external APIs and services. "
        "Use fetch_url for full control, fetch_json for JSON APIs, "
        "post_json to POST data. "
        "Responses are truncated at "
        f"{MAX_BODY_BYTES} bytes."
    ),
)


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def fetch_url(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
    timeout: int = TIMEOUT,
) -> dict:
    """
    Make an HTTP request to any URL and return the full response.

    Args:
        url:     Fully-qualified URL, e.g. https://api.example.com/v1/users
        method:  HTTP method: GET, POST, PUT, DELETE, PATCH, HEAD (default GET)
        headers: Extra request headers as {"Header-Name": "value"}
        body:    Request body as a string (for POST/PUT). For JSON send a
                 JSON-serialised string and set Content-Type header.
        timeout: Timeout in seconds (default 30).

    Returns a dict with:
        status    (int)   HTTP status code
        ok        (bool)  true if 200-299
        headers   (dict)  response headers
        body      (str)   response body (first MAX_RESPONSE_BYTES bytes)
        url       (str)   final URL after redirects
    """
    _check_domain(url)
    method = method.upper()

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers or {},
                content=body.encode() if body else None,
                timeout=timeout,
            )
        except httpx.TimeoutException:
            return {"error": "timeout", "url": url, "timeout_seconds": timeout}
        except httpx.RequestError as exc:
            return {"error": str(exc), "url": url}

    raw = resp.content[:MAX_BODY_BYTES]
    body_text = raw.decode("utf-8", errors="replace")

    return {
        "status": resp.status_code,
        "ok": resp.is_success,
        "url": str(resp.url),
        "headers": dict(resp.headers),
        "body": body_text,
        "truncated": len(resp.content) > MAX_BODY_BYTES,
    }


@mcp.tool()
async def fetch_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: int = TIMEOUT,
) -> dict:
    """
    GET a URL and return the parsed JSON body.

    Useful for reading REST APIs that return JSON. Raises an error if the
    response is not valid JSON.

    Args:
        url:     JSON API endpoint URL
        headers: Optional extra headers (e.g. Authorization)
        timeout: Timeout in seconds (default 30)

    Returns the parsed JSON object/array, or a dict with an 'error' key on failure.
    """
    _check_domain(url)
    default_headers = {"Accept": "application/json"}
    if headers:
        default_headers.update(headers)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers=default_headers, timeout=timeout)
            resp.raise_for_status()
        except httpx.TimeoutException:
            return {"error": "timeout", "url": url}
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"HTTP {exc.response.status_code}",
                "url": url,
                "body": exc.response.text[:2000],
            }
        except httpx.RequestError as exc:
            return {"error": str(exc), "url": url}

    try:
        return resp.json()
    except json.JSONDecodeError:
        return {
            "error": "response_not_json",
            "content_type": resp.headers.get("content-type", ""),
            "body": resp.text[:2000],
        }


@mcp.tool()
async def post_json(
    url: str,
    payload: dict,
    headers: dict[str, str] | None = None,
    timeout: int = TIMEOUT,
) -> dict:
    """
    POST a JSON payload to a URL and return the parsed response.

    Args:
        url:     Endpoint URL to POST to
        payload: JSON-serialisable dict to send as the request body
        headers: Optional extra headers (Authorization etc.)
        timeout: Timeout in seconds (default 30)

    Returns the parsed JSON response, or a dict with an 'error' key on failure.
    """
    _check_domain(url)
    merged = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        merged.update(headers)

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            resp = await client.post(
                url, json=payload, headers=merged, timeout=timeout
            )
            resp.raise_for_status()
        except httpx.TimeoutException:
            return {"error": "timeout", "url": url}
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"HTTP {exc.response.status_code}",
                "body": exc.response.text[:2000],
            }
        except httpx.RequestError as exc:
            return {"error": str(exc), "url": url}

    try:
        return resp.json()
    except json.JSONDecodeError:
        return {"status": resp.status_code, "body": resp.text[:2000]}


# ── Health endpoint (no auth) ─────────────────────────────────────────────────
from starlette.responses import JSONResponse
from starlette.routing import Route

async def health(_):
    return JSONResponse({"status": "ok", "server": "mcp-http-caller"})

# ── Entrypoint ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = mcp.http_app(transport="streamable-http")
    app.routes.insert(0, Route("/health", health))
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
