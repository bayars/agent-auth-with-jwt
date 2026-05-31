# Connecting MCP Tool Servers

## Option 1 — Register directly in opencode.json (recommended)

Each tool server gets its own entry in the `mcp` section of `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "user-info-server": {
      "type": "remote",
      "url": "http://fastmcp:8000",
      "enabled": true,
      "headers": { "Authorization": "Bearer ${MCP_SERVICE_TOKEN}" }
    },
    "http-caller": {
      "type": "remote",
      "url": "http://mcp-http-caller:8001",
      "enabled": true
    },
    "file-generator": {
      "type": "remote",
      "url": "http://mcp-file-generator:8002",
      "enabled": true
    },
    "text-generator": {
      "type": "remote",
      "url": "http://mcp-text-generator:8003",
      "enabled": true
    },
    "text-utils": {
      "type": "remote",
      "url": "http://mcp-text-utils:8004",
      "enabled": true
    }
  }
}
```

OpenCode connects to each server independently. Tools from all servers appear
in the same tool list.

**Headers** — pass per-server auth headers:
```json
"headers": {
  "Authorization": "Bearer ${MY_TOKEN}",
  "X-Api-Key": "${API_KEY}"
}
```
Environment variables in `${}` are expanded at runtime.

---

## Option 2 — Register tools in a single FastMCP server

Import and register tools from multiple modules into one server:

```python
# main.py (aggregator server)
from fastmcp import FastMCP
from tools.http_caller import register_http_tools
from tools.file_generator import register_file_tools

mcp = FastMCP("All Tools")
register_http_tools(mcp)
register_file_tools(mcp)
```

Each module exports a `register_*(mcp: FastMCP) -> None` function:

```python
# tools/http_caller.py
def register_http_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    async def fetch_url(url: str) -> dict: ...

    @mcp.tool()
    async def fetch_json(url: str) -> dict: ...
```

Tradeoff vs Option 1:
- Pro: one server, one port, one Helm release
- Con: any tool crashing takes down all tools; harder to scale per-tool

---

## Option 3 — FastMCP Proxy (tool server aggregation)

FastMCP 3.x can proxy all tools from a remote server:

```python
import fastmcp

# Create a proxy that exposes all tools from another server
proxy = await fastmcp.Client("http://mcp-http-caller:8001").get_proxy()

# Mount it under the main server
mcp.mount("http-caller", proxy)
```

Useful when you want a single ingress URL but independent deployments behind it.

---

## Connecting to an authenticated server

When the tool server uses `KeycloakVerifier`:

```python
# main.py of the tool server
auth = KeycloakVerifier()
mcp = FastMCP("Secure Tools", auth=auth)
```

Clients must pass a valid Keycloak access token:

```json
{
  "type": "remote",
  "url": "http://mcp-secure-tool:8000",
  "headers": { "Authorization": "Bearer ${KC_ACCESS_TOKEN}" }
}
```

For server-to-server (OpenCode → tool), use a client-credentials token:
```bash
KC_TOKEN=$(curl -sf -X POST http://keycloak:8080/realms/poc-realm/protocol/openid-connect/token \
  -d 'grant_type=client_credentials&client_id=fastmcp-service&client_secret=...')
```

---

## docker-compose.yml integration

Add each new tool as a service. No `depends_on` needed unless the tool calls
another internal service at startup:

```yaml
services:
  mcp-http-caller:
    build: ./tools/http-caller
    ports:
      - "8001:8000"
    environment:
      PORT: "8000"
      ALLOWED_DOMAINS: ""   # empty = allow all
    networks:
      - poc-net

  mcp-file-generator:
    build: ./tools/file-generator
    ports:
      - "8002:8000"
    networks:
      - poc-net

  mcp-text-generator:
    build: ./tools/text-generator
    ports:
      - "8003:8000"
    networks:
      - poc-net

  mcp-text-utils:
    build: ./tools/text-utils
    ports:
      - "8004:8000"
    networks:
      - poc-net
```

Then update `opencode.json` with the Docker service names:
```json
"http-caller": {
  "type": "remote",
  "url": "http://mcp-http-caller:8000"
}
```
(Inside Docker the container port is 8000; the host-port 8001 is only for
direct host access.)

---

## Kubernetes / Helm integration

Each tool's Helm chart creates:
- `Deployment` running the tool server
- `ClusterIP Service` at port 8000

In the umbrella chart `mcp-tools-stack`, a `ConfigMap` is rendered with the
complete `opencode.json` incorporating all tool URLs using Kubernetes DNS:

```yaml
# mcp-tools-stack/templates/opencode-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: opencode-config
data:
  opencode.json: |
    {
      "mcp": {
        {{- if .Values.httpCaller.enabled }}
        "http-caller": {
          "type": "remote",
          "url": "http://{{ .Release.Name }}-mcp-http-caller:8000"
        },
        {{- end }}
        ...
      }
    }
```

Mount it into the OpenCode pod:
```yaml
volumeMounts:
  - name: opencode-config
    mountPath: /workspace/opencode.json
    subPath: opencode.json
volumes:
  - name: opencode-config
    configMap:
      name: opencode-config
```

---

## Testing a new tool server end-to-end

```bash
# 1. Build and start the tool locally
cd tools/http-caller
docker build -t mcp-http-caller .
docker run -p 8001:8000 mcp-http-caller

# 2. Run the test script
python tools/test_all_tools.py --port 8001 --tool fetch_url \
  --args '{"url": "https://httpbin.org/get"}'

# 3. In OpenCode, ask: "Use the http-caller MCP tool to fetch https://httpbin.org/get"
```
