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

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth import TokenVerifier
from fastmcp.server.auth.providers.jwt import JWTVerifier

from tools.user_tools import register_tools
from tools.sample_tool import register_sample_tools

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

if __name__ == "__main__":
    uvicorn.run(
        mcp.http_app(transport="streamable-http"),
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
