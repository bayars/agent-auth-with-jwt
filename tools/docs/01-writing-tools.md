# How to Write MCP Tools with FastMCP

## Anatomy of a tool server

Every tool server is a Python file that creates a `FastMCP` instance, registers
tools with the `@mcp.tool()` decorator, and starts an HTTP server.

```
main.py                ← entry point: mcp = FastMCP(...); mcp.tool() decorators; uvicorn.run(...)
Dockerfile             ← python:3.12-slim, COPY . ., CMD ["python", "main.py"]
requirements.txt       ← fastmcp==3.3.1 + any tool-specific libs
build.sh               ← docker build wrapper
helm/<chart-name>/     ← Kubernetes Helm chart
```

---

## Minimal working tool

```python
# main.py
import uvicorn
from fastmcp import FastMCP

mcp = FastMCP(
    name="My Tool Server",                      # shown in tools/list
    instructions="One-paragraph description of what these tools do.",
)

@mcp.tool()
async def greet(name: str) -> str:
    """Return a greeting for the given name."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    uvicorn.run(
        mcp.http_app(transport="streamable-http"),
        host="0.0.0.0",
        port=int(__import__("os").environ.get("PORT", 8000)),
        log_level="info",
    )
```

Start it:  `python main.py`
Test it:   `curl http://localhost:8000/mcp`

---

## Function signature rules

### Parameters

Every parameter becomes a JSON Schema field in the tool's input schema.

| Python type               | JSON Schema type  | Notes                                  |
|---------------------------|-------------------|----------------------------------------|
| `str`                     | `string`          |                                        |
| `int`                     | `integer`         |                                        |
| `float`                   | `number`          |                                        |
| `bool`                    | `boolean`         |                                        |
| `list[str]`               | `array of string` |                                        |
| `dict[str, str]`          | `object`          |                                        |
| `dict` / `list`           | `object` / `array`| Use when structure varies              |
| `SomeModel` (Pydantic)    | full JSON Schema  | Recommended for complex inputs         |
| `param = None`            | optional field    | Adds `"required": false` to schema     |
| `param = "default"`       | optional + default| Shown in schema as `"default"`         |

```python
from pydantic import BaseModel, Field

class Endpoint(BaseModel):
    path: str = Field(description="URL path, e.g. /users/{id}")
    method: str = Field(default="GET", description="HTTP method")
    description: str = ""

@mcp.tool()
async def document_endpoint(endpoint: Endpoint) -> str:
    """Generate docs for a single API endpoint."""
    return f"## {endpoint.method} {endpoint.path}\n{endpoint.description}"
```

### Return values

| Python return type      | What the LLM receives          | Use case                        |
|-------------------------|--------------------------------|---------------------------------|
| `str`                   | plain text                     | prose, markdown, code           |
| `int` / `float` / `bool`| number / boolean as text       | simple scalar results           |
| `dict` / `list`         | JSON-formatted text            | structured data                 |
| `None`                  | empty                          | side-effect-only tools          |

> FastMCP wraps every return value in an MCP `TextContent` block. The LLM sees
> the value serialised as a string. For `dict`/`list` it is JSON-encoded.

---

## Docstring = tool description

The function's docstring becomes the tool description visible to the LLM.
Write it from the model's perspective: what does calling this tool do,
what should I pass, what will I get back?

```python
@mcp.tool()
async def fetch_url(url: str, timeout: int = 30) -> dict:
    """
    Fetch the response from any HTTP URL.

    Args:
        url:     Fully-qualified URL including scheme, e.g. https://api.example.com/data
        timeout: Request timeout in seconds (default 30).

    Returns a dict with keys:
        status  (int)   HTTP status code
        headers (dict)  response headers
        body    (str)   response body text (first 10 000 chars)
    """
```

---

## Error handling

Raise a plain `Exception` or a typed error — FastMCP catches it and returns an
MCP error result. The LLM sees the exception message.

```python
@mcp.tool()
async def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("b must not be zero")   # becomes MCP isError=true
    return a / b
```

For expected, recoverable errors, return a dict with an `"error"` key instead
so the LLM can reason about the failure:

```python
@mcp.tool()
async def fetch_url(url: str) -> dict:
    try:
        resp = await httpx.AsyncClient().get(url, timeout=10)
        return {"status": resp.status_code, "body": resp.text[:10_000]}
    except httpx.TimeoutException:
        return {"error": "timeout", "url": url}
```

---

## Tool context and dependencies

FastMCP injects typed dependencies via default-value sentinels:

```python
from fastmcp.server.dependencies import CurrentAccessToken, AccessToken, TokenClaim

@mcp.tool()
async def whoami(
    token: AccessToken = CurrentAccessToken(),  # ← note the ()
) -> dict:
    """Return the caller's identity from their JWT."""
    return {"sub": token.claims.get("sub"), "email": token.claims.get("email")}
```

Available built-in dependencies:

| Sentinel                  | Resolved value                              |
|---------------------------|---------------------------------------------|
| `CurrentAccessToken()`    | `AccessToken` with `.claims` dict           |
| `TokenClaim("claim_name")`| single claim value as `str`                 |
| `CurrentContext()`        | `Context` (logging, progress reporting)     |

---

## Progress reporting for slow tools

```python
from fastmcp import FastMCP, Context

@mcp.tool()
async def slow_task(n: int, ctx: Context) -> str:
    """Process n items, reporting progress."""
    results = []
    for i in range(n):
        await ctx.report_progress(i, n)      # LLM sees live progress
        results.append(await process_one(i))
    return "\n".join(results)
```

---

## Environment-driven configuration

Never hard-code URLs, secrets, or thresholds. Read from environment variables:

```python
import os
ALLOWED_DOMAINS = os.environ.get("ALLOWED_DOMAINS", "").split(",")
MAX_RESPONSE_SIZE = int(os.environ.get("MAX_RESPONSE_SIZE", "10000"))
```

Pass them via Docker `--env` or Kubernetes `env:` in the Deployment.
