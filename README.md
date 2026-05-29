# Agent Auth with JWT — POC

A proof-of-concept demonstrating a complete SSO/JWT authentication chain:

```
Browser → Next.js (PKCE login) → Keycloak → JWT stored in httpOnly cookie
             ↓                                   ↓
     OpenCode iframe            FastMCP server validates JWT via JWKS
     (proxied, SSO-gated)       MCP tools know user name, email, roles
```

**Nothing is mocked.** Every JWT is issued by Keycloak and validated against its JWKS endpoint.

---

## Architecture

```
Browser
  └── Next.js  :3000
        ├── /                   Dashboard + OpenCode iframe
        ├── /api/auth/*         PKCE login / callback / logout / session
        ├── /api/opencode/*     JWT-validated proxy → OpenCode :4321 (internal)
        └── /api/mcp/*          JWT-validated proxy → FastMCP :8000 (internal)

Keycloak  :8080
  └── poc-realm
        ├── nextjs-client       Public OIDC client (PKCE, browser login)
        └── fastmcp-service     Confidential client (client_credentials, server-to-server)

FastMCP   :8000  (internal only)
  └── KeycloakAuthProvider → validates JWT via JWKS on every MCP request
  └── Tools: get_user_info, get_user_roles, whoami, verify_with_python_jose
```

### How JWT flows end-to-end

| Leg | Mechanism |
|---|---|
| Browser → Keycloak | PKCE authorization code flow |
| Keycloak → Next.js | Auth code exchanged server-side; JWT stored in httpOnly cookie |
| Browser → OpenCode iframe | Cookie present on same origin; Next.js proxy validates `exp` before forwarding |
| Browser → FastMCP (via `/api/mcp/*`) | Same cookie forwarded as `Authorization: Bearer` |
| OpenCode server process → FastMCP | `MCP_SERVICE_TOKEN` from Keycloak client credentials grant |
| FastMCP validates | `KeycloakAuthProvider` → JWKS fetch → RS256 signature + issuer + expiry check |

### Why OpenCode is "already logged in"

OpenCode's web UI is served through the Next.js `/api/opencode/*` proxy. The proxy returns 401 if the `kc_access_token` cookie is absent or expired. OpenCode never sees a login page — access is gated upstream.

---

## Prerequisites

- **Docker** + **Docker Compose** v2+
- An **Anthropic API key** (or another AI provider supported by OpenCode)
- `curl`, `python3` (for the helper script)

---

## Setup

### 1. Clone and configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENCODE_SERVER_PASSWORD=choose-a-strong-password
# Leave MCP_SERVICE_TOKEN empty for now — Step 3 will fill it
```

### 2. Start Keycloak

```bash
docker compose up keycloak -d
```

Wait until healthy (~30–60 seconds):

```bash
docker compose ps keycloak
# Should show: healthy
```

### 3. Get the service token for OpenCode → FastMCP

```bash
./scripts/get-service-token.sh
```

Copy the printed `MCP_SERVICE_TOKEN=...` line into your `.env` file.

> The default client secret for `fastmcp-service` is `fastmcp-service-secret-change-me`
> (set in `keycloak/realm-export.json`). Change it for any non-throwaway deployment.

### 4. Start everything

```bash
docker compose up -d
```

---

## Verification

### Step 1 — Login through Next.js SSO

Open **http://localhost:3000** in a browser.

You should be redirected to Keycloak. Login with:

- Username: `testuser`
- Password: `Test1234!`

After login you should see the Next.js dashboard with your name and roles in the top bar, and OpenCode loaded in the iframe.

**Verify the cookie is httpOnly** (not readable by JavaScript):

1. Open DevTools → Application → Cookies → `http://localhost:3000`
2. Find `kc_access_token` — the **HttpOnly** column must be checked
3. Open the Console and run `document.cookie` — `kc_access_token` must NOT appear

### Step 2 — Verify OpenCode proxy enforces auth

```bash
# Without cookie → 401
curl -s -o /dev/null -w "Status: %{http_code}\n" http://localhost:3000/api/opencode/
# Expected: Status: 401

# With a valid token in the cookie → OpenCode HTML
TOKEN=$(curl -sf -X POST \
  http://localhost:8080/realms/poc-realm/protocol/openid-connect/token \
  -d 'grant_type=client_credentials&client_id=fastmcp-service&client_secret=fastmcp-service-secret-change-me' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -o /dev/null -w "Status: %{http_code}\n" \
  http://localhost:3000/api/opencode/ \
  --cookie "kc_access_token=$TOKEN"
# Expected: Status: 200
```

### Step 3 — Verify FastMCP JWT validation and tools

```bash
# Get a fresh service token
TOKEN=$(curl -sf -X POST \
  http://localhost:8080/realms/poc-realm/protocol/openid-connect/token \
  -d 'grant_type=client_credentials&client_id=fastmcp-service&client_secret=fastmcp-service-secret-change-me' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# List available MCP tools (calls FastMCP directly — bypasses Next.js proxy)
curl -sf http://localhost:8000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | python3 -m json.tool

# Call whoami — demonstrates token → name + roles extraction
curl -sf http://localhost:8000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"whoami","arguments":{}}}' \
  | python3 -m json.tool
# Expected: "Hello, <service account name>! Your roles: ..."

# Call get_user_info — returns claims from fastmcp middleware AccessToken
curl -sf http://localhost:8000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"get_user_info","arguments":{}}}' \
  | python3 -m json.tool
```

### Step 4 — Verify python-jose validation chain

```bash
# Call verify_with_python_jose — independently validates the JWT with python-jose
curl -sf http://localhost:8000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"verify_with_python_jose\",\"arguments\":{\"token\":\"$TOKEN\"}}}" \
  | python3 -m json.tool
# Expected: { "valid": true, "python_jose_validated": true, "claims": { "sub": ..., ... } }

# Test with a tampered token — should return valid: false
TAMPERED="${TOKEN}tampered"
curl -sf http://localhost:8000/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"tools/call\",\"params\":{\"name\":\"verify_with_python_jose\",\"arguments\":{\"token\":\"$TAMPERED\"}}}" \
  | python3 -m json.tool
# Expected: { "valid": false, "error": "Token validation failed: ..." }
```

### Step 5 — Verify MCP proxy chain through Next.js

```bash
# Call MCP through the Next.js proxy using the cookie path
curl -sf http://localhost:3000/api/mcp/mcp \
  -H "Cookie: kc_access_token=$TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | python3 -m json.tool
# Expected: same tools list as direct FastMCP call

# Without cookie → 401
curl -s -o /dev/null -w "Status: %{http_code}\n" \
  http://localhost:3000/api/mcp/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
# Expected: Status: 401
```

---

## Keycloak admin console

URL: **http://localhost:8080/admin**  
Credentials: `admin` / `admin`

Realm to inspect: **poc-realm**

Key things to verify in the admin console:
- `nextjs-client` → Settings: PKCE code challenge method = S256, Standard flow enabled
- `fastmcp-service` → Settings: Service accounts enabled, Standard flow disabled
- `testuser` → Role Mappings: user, developer
- `testuser` → Credentials: temporary = false

---

## Project Structure

```
.
├── docker-compose.yml
├── .env.example
├── keycloak/
│   └── realm-export.json         # Imported on Keycloak boot via --import-realm
├── nextjs-app/
│   ├── server.js                 # Custom server — handles WebSocket proxy for OpenCode
│   ├── opencode.json             # OpenCode config — MCP server URL + auth header
│   └── src/
│       ├── middleware.ts         # JWT expiry check + refresh on every request
│       ├── lib/auth/
│       │   ├── pkce.ts           # PKCE code verifier/challenge (Web Crypto API)
│       │   ├── keycloak.ts       # Keycloak URL helpers + token exchange
│       │   └── session.ts        # httpOnly cookie get/set/clear
│       ├── app/api/
│       │   ├── auth/             # login, callback, logout, session routes
│       │   ├── opencode/[...path]/ # JWT-gated OpenCode proxy
│       │   └── mcp/[...path]/    # JWT-forwarding FastMCP proxy
│       └── components/
│           └── OpenCodeFrame.tsx # <iframe src="/api/opencode/" />
└── fastmcp-server/
    ├── main.py                   # FastMCP + KeycloakAuthProvider
    ├── auth/jwt_validator.py     # python-jose JWKS validation (used in verify_with_python_jose tool)
    └── tools/user_tools.py       # get_user_info, get_user_roles, whoami, verify_with_python_jose
```

---

## JWT validation layers

| Layer | Validates | Details |
|---|---|---|
| Next.js middleware | `exp` claim only | `jose.decodeJwt()` — no sig verify; cookie is trusted because server set it |
| `/api/opencode/*` proxy | `exp` + cookie presence | Blocks access to OpenCode without a valid session |
| `/api/mcp/*` proxy | `exp` + cookie or Bearer header | Forwards token to FastMCP |
| FastMCP `KeycloakAuthProvider` | Full: signature + issuer + expiry + scopes | RS256 + JWKS from Keycloak; `required_scopes=["openid"]` |
| `verify_with_python_jose` tool | Full: signature + issuer + expiry | Explicitly uses `python-jose[cryptography]` to demonstrate raw JWKS validation |

---

## Troubleshooting

**Keycloak takes too long to start**

```bash
docker compose logs keycloak --tail=30
```

The health check retries up to 18 times (3 minutes). If it still fails, check if port 8080 is occupied.

**`MCP_SERVICE_TOKEN` expired (token lifespan is 5 minutes)**

Keycloak issues short-lived tokens. For the POC, re-run `./scripts/get-service-token.sh` and update `.env`, then restart:

```bash
docker compose restart opencode
```

For a real deployment, implement token refresh in OpenCode's MCP connection or extend the access token lifespan for the `fastmcp-service` client in Keycloak admin.

**OpenCode iframe shows a blank page**

OpenCode's `npx opencode-ai@latest` command may take a moment to download. Check:

```bash
docker compose logs opencode --tail=30
```

**FastMCP returns 401 despite a valid token**

The `KeycloakAuthProvider` checks the `openid` scope. Ensure your token was obtained with `scope=openid`. The `fastmcp-service` client's default scopes include `openid` via the realm's `profile` scope.

Check that Keycloak is reachable from the FastMCP container:

```bash
docker compose exec fastmcp curl -sf http://keycloak:8080/realms/poc-realm/protocol/openid-connect/certs | python3 -m json.tool | head -10
```
