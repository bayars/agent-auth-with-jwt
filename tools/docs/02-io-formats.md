# MCP Tool Input / Output Format Reference

## How MCP encodes tool calls

The MCP protocol uses JSON-RPC 2.0 over HTTP (streamable-HTTP transport).

### Request (tools/call)

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "fetch_url",
    "arguments": {
      "url": "https://httpbin.org/get",
      "method": "GET",
      "timeout": 15
    }
  }
}
```

`arguments` is a plain JSON object. Every key maps to a Python parameter.
FastMCP validates the arguments against the tool's JSON Schema before calling
the function.

### Response (success)

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"status\": 200, \"body\": \"...\"}"
      }
    ],
    "isError": false
  }
}
```

`content` is always a list of `TextContent` objects. For `dict`/`list` returns
FastMCP JSON-serialises the value into `text`. For `str` returns the string
is used as-is.

### Response (error)

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "ValueError: b must not be zero"
      }
    ],
    "isError": true
  }
}
```

---

## Input type mapping

### Scalar types

```python
# Python                  curl argument example
name: str                 "arguments": {"name": "Alice"}
count: int                "arguments": {"count": 42}
ratio: float              "arguments": {"ratio": 3.14}
verbose: bool             "arguments": {"verbose": true}
```

### Optional parameters

```python
# Python                          JSON
timeout: int = 30                 omit → uses 30
label: str | None = None          omit or send null → None
tags: list[str] = []              omit → empty list
```

### Lists and dicts

```python
# Python
headers: dict[str, str]           {"X-Api-Key": "abc", "Accept": "application/json"}
rows: list[list[str]]             [["Alice", "30"], ["Bob", "25"]]
files: list[dict]                 [{"name": "a.txt", "content": "hello"}]
```

### Pydantic models (recommended for complex inputs)

```python
class FileSpec(BaseModel):
    name: str
    content: str
    encoding: str = "utf-8"

@mcp.tool()
async def write_file(spec: FileSpec) -> str: ...
```

Argument in request:
```json
{
  "spec": {"name": "report.md", "content": "# Hello", "encoding": "utf-8"}
}
```

---

## Output format patterns

### Pattern 1 — Plain text (prose, markdown, code)

```python
@mcp.tool()
async def generate_readme(...) -> str:
    return "# Project Name\n\n..."    # returned as-is in TextContent.text
```

### Pattern 2 — Structured data

```python
@mcp.tool()
async def get_stats(text: str) -> dict:
    return {"words": 42, "lines": 5}  # JSON-serialised into TextContent.text
```

The LLM receives: `{"words": 42, "lines": 5}` as a string.

### Pattern 3 — File content (text)

Return the file contents as a string. Include `filename` in the dict so the
LLM knows what to save it as:

```python
@mcp.tool()
async def generate_csv(headers: list[str], rows: list[list[str]]) -> dict:
    # build CSV string
    return {
        "filename": "report.csv",
        "content": csv_string,
        "size_bytes": len(csv_string.encode()),
    }
```

### Pattern 4 — Binary file (ZIP, PDF, images)

Binary files must be base64-encoded. Indicate this in the return dict:

```python
@mcp.tool()
async def generate_zip(files: list[dict]) -> dict:
    # build zip in memory
    return {
        "filename": "archive.zip",
        "encoding": "base64",
        "content": base64.b64encode(zip_bytes).decode(),
        "size_bytes": len(zip_bytes),
    }
```

The LLM (or calling code) must base64-decode before writing the file.

### Pattern 5 — Large text (reports, documentation)

For multi-kilobyte outputs just return a `str`. FastMCP does not truncate.
Use markdown to give the LLM structure:

```python
@mcp.tool()
async def generate_api_docs(service: str, endpoints: list[dict]) -> str:
    lines = [f"# {service} API Reference\n"]
    for ep in endpoints:
        lines.append(f"## {ep['method']} {ep['path']}")
        lines.append(ep.get("description", ""))
        # ... etc
    return "\n".join(lines)   # can be 10 000+ characters
```

### Pattern 6 — Streaming progress (slow operations)

```python
from fastmcp import Context

@mcp.tool()
async def batch_process(items: list[str], ctx: Context) -> list[dict]:
    results = []
    for i, item in enumerate(items):
        await ctx.report_progress(i, len(items))
        results.append(await process(item))
    return results
```

---

## Authentication formats

When a tool server uses `KeycloakVerifier` or similar, every MCP HTTP request
must carry:

```
Authorization: Bearer <keycloak-access-token>
```

The token is validated before the tool function is called. Inside the tool, use
`CurrentAccessToken()` to read the claims.

If a tool server has NO auth (open tools), no Authorization header is needed.

---

## Full curl test sequence (all tool servers)

```bash
# 1. Initialise session
INIT=$(curl -si -X POST http://localhost:<PORT>/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{
        "protocolVersion":"2024-11-05","capabilities":{},
        "clientInfo":{"name":"test","version":"1"}}}')
SID=$(echo "$INIT" | grep -i mcp-session-id | awk '{print $2}' | tr -d '\r')

# 2. List tools
curl -sf -X POST http://localhost:<PORT>/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# 3. Call a tool
curl -sf -X POST http://localhost:<PORT>/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
        "name":"TOOL_NAME","arguments":{...}}}'
```
