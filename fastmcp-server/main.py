"""
FastMCP server with Keycloak JWT authentication.

Authentication flow:
  1. Every HTTP request must carry `Authorization: Bearer <jwt>`.
  2. A custom JWTVerifier validates the token using Keycloak's JWKS endpoint.
  3. JWKS is fetched from KC_REALM_URL (Docker-internal hostname).
  4. Issuer is validated against KC_ISSUER (external-facing URL, must match
     the `iss` claim in tokens issued to browser clients).
  5. On success, the validated AccessToken (including all JWT claims) is
     injected into tool functions via fastmcp's dependency injection system.

Why separate KC_REALM_URL and KC_ISSUER?
  Tokens issued to browser clients have iss=http://localhost:8080/...
  But the FastMCP container must fetch JWKS via the Docker service name
  (http://keycloak:8080/...). These two URLs must be configured separately.
"""

import os
import uuid

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.responses import JSONResponse
from starlette.routing import Route

from tools.user_tools import register_tools
from tools.sample_tool import register_sample_tools
from tools.sample_tool import _POLICY, _check

# Docker-internal URL — used to fetch JWKS keys from Keycloak
KC_REALM_URL = os.environ["KC_REALM_URL"]       # http://keycloak:8080/realms/poc-realm
# External-facing URL — must match the `iss` claim in Keycloak JWTs
KC_ISSUER = os.environ.get("KC_ISSUER", KC_REALM_URL)  # http://localhost:8080/realms/poc-realm
FASTMCP_BASE_URL = os.environ["FASTMCP_BASE_URL"]       # http://fastmcp:8000

verifier = JWTVerifier(
    jwks_uri=f"{KC_REALM_URL}/protocol/openid-connect/certs",
    issuer=KC_ISSUER,
    algorithm="RS256",
    required_scopes=["openid"],
)

# Wrap in a minimal TokenVerifier subclass so FastMCP's auth middleware accepts it
class KeycloakVerifier(TokenVerifier):
    def __init__(self):
        super().__init__(base_url=FASTMCP_BASE_URL, required_scopes=["openid"])

    async def verify_token(self, token: str):
        return await verifier.verify_token(token)


mcp = FastMCP(
    name="SSO-Aware MCP Server",
    instructions=(
        "This MCP server provides tools that use the caller's Keycloak JWT. "
        "All tools require a valid access token. "
        "Identity tools: get_user_info, get_user_roles, whoami. "
        "Access control tools: check_access, list_permissions. "
        "JWT validation demo: verify_with_python_jose."
    ),
    auth=KeycloakVerifier(),
)

register_tools(mcp)
register_sample_tools(mcp)

# ── A2A Agent Card ─────────────────────────────────────────────────────────────

_A2A_AGENT_CARD = {
    "name": "Identity & Access Agent",
    "description": (
        "Provides user identity and role-based access control decisions "
        "derived from Keycloak JWTs. All skills require a valid Bearer token."
    ),
    "url": FASTMCP_BASE_URL,
    "version": "1.0.0",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "authentication": {
        "schemes": ["bearer"],
        "bearerFormat": "JWT",
        "description": "Keycloak JWT required for all skills.",
    },
    "skills": [
        {
            "id": "identify_user",
            "name": "Identify User",
            "description": "Return the caller's name, email, sub, and realm roles from the JWT.",
            "inputModes": ["text"],
            "outputModes": ["data"],
            "tags": ["identity", "jwt"],
        },
        {
            "id": "check_access",
            "name": "Check Access",
            "description": "Decide whether the caller may perform an action on a resource.",
            "inputModes": ["text"],
            "outputModes": ["data"],
            "tags": ["access-control", "rbac"],
        },
        {
            "id": "list_permissions",
            "name": "List Permissions",
            "description": "Return all resource:action pairs the caller is permitted to perform.",
            "inputModes": ["text"],
            "outputModes": ["data"],
            "tags": ["access-control", "rbac"],
        },
    ],
}


async def agent_card(_):
    return JSONResponse(_A2A_AGENT_CARD)


# ── A2A task helpers ───────────────────────────────────────────────────────────

async def _a2a_verify_request(request) -> tuple[dict | None, dict | None]:
    """
    Verify the Bearer JWT on an A2A request using the same JWTVerifier as MCP.

    Returns (claims, None) on success.
    Returns (None, error_body) on failure.

    The A2A endpoint is a plain Starlette route that does NOT go through the
    FastMCP auth middleware, so we must call the verifier explicitly here.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return None, _a2a_err(-32001, "Missing Bearer token")

    token = auth_header[7:]
    try:
        access_token = await verifier.verify_token(token)
        return access_token.claims, None
    except Exception as exc:
        return None, _a2a_err(-32001, f"Invalid token: {exc}")


def _a2a_result(task_id: str, state: str, data=None) -> dict:
    artifacts = []
    if data is not None:
        artifacts.append({"parts": [{"type": "data", "data": data}]})
    return {"jsonrpc": "2.0", "result": {"id": task_id, "status": {"state": state}, "artifacts": artifacts}}


def _a2a_err(code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}}


# ── A2A task endpoint ──────────────────────────────────────────────────────────

async def a2a_handler(request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_a2a_err(-32700, "Parse error"))

    method = body.get("method", "")
    params = body.get("params", {})
    task_id = params.get("id", str(uuid.uuid4()))

    # All A2A methods require a valid JWT — verify before routing
    claims, err_body = await _a2a_verify_request(request)
    if err_body:
        return JSONResponse(err_body, status_code=401)

    realm_access = claims.get("realm_access") or {}
    raw_roles: list[str] = realm_access.get("roles", [])
    roles = [r for r in raw_roles if not r.startswith("default-roles-")]

    if method == "tasks/get":
        # Identity tasks complete synchronously — there is no async job to poll.
        # Any valid JWT is sufficient to call tasks/get; the task_id is not secret.
        return JSONResponse(_a2a_result(task_id, "completed"))

    if method != "tasks/send":
        return JSONResponse(_a2a_err(-32601, f"Unknown method: {method}"))

    skill_id = params.get("skill_id", "")
    message_parts = params.get("message", {}).get("parts", [])
    message_text = next((p["text"] for p in message_parts if p.get("type") == "text"), "")

    if skill_id == "identify_user":
        data = {
            "sub": claims.get("sub"),
            "given_name": claims.get("given_name"),
            "family_name": claims.get("family_name"),
            "email": claims.get("email"),
            "issuer": claims.get("iss"),
            "roles": roles,
        }
        return JSONResponse(_a2a_result(task_id, "completed", data=data))

    if skill_id == "check_access":
        # Parse "resource:action" or "resource action" from message_text
        parts = message_text.replace(":", " ").split()
        resource = parts[0] if parts else ""
        action = parts[1] if len(parts) > 1 else ""
        granted, reason = _check(roles, resource, action)
        data = {
            "granted": granted, "reason": reason,
            "user": claims.get("sub"), "roles": roles,
            "resource": resource, "action": action,
            "policy": _POLICY.get(resource, {}).get(action, []),
        }
        return JSONResponse(_a2a_result(task_id, "completed", data=data))

    if skill_id == "list_permissions":
        allowed: dict[str, list[str]] = {}
        for resource, actions in _POLICY.items():
            permitted = [
                action for action, allowed_roles in actions.items()
                if "admin" in roles or any(r in allowed_roles for r in roles)
            ]
            if permitted:
                allowed[resource] = permitted
        data = {"user": claims.get("sub"), "email": claims.get("email"), "roles": roles, "allowed": allowed}
        return JSONResponse(_a2a_result(task_id, "completed", data=data))

    return JSONResponse(_a2a_err(-32602, f"Unknown skill_id: {skill_id}"))


async def health(_):
    return JSONResponse({"status": "ok", "server": "mcp-fastmcp", "a2a": "enabled"})


if __name__ == "__main__":
    app = mcp.http_app(transport="streamable-http")
    app.routes.insert(0, Route("/health", health))
    app.routes.insert(0, Route("/.well-known/agent.json", agent_card))
    app.routes.insert(0, Route("/a2a", a2a_handler, methods=["POST"]))
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
