"""
MCP tools that demonstrate JWT claim extraction.

The fastmcp KeycloakAuthProvider (set up in main.py) validates every request
at the HTTP middleware level before any tool is called. Tools access the already-
validated claims via fastmcp's dependency injection system.

A fourth tool demonstrates raw python-jose validation to show the full JWKS chain.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import AccessToken, CurrentAccessToken, TokenClaim


def register_tools(mcp: FastMCP) -> None:

    # Lazy import to avoid module-level side effects
    from auth.jwt_validator import JWTValidationError, JWTValidator

    KC_REALM_URL = os.environ["KC_REALM_URL"]
    KC_ISSUER = os.environ.get("KC_ISSUER", KC_REALM_URL)
    _validator = JWTValidator(
        jwks_uri=f"{KC_REALM_URL}/protocol/openid-connect/certs",
        issuer=KC_ISSUER,
    )

    @mcp.tool()
    async def get_user_info(
        access_token: AccessToken = CurrentAccessToken(),
    ) -> dict[str, Any]:
        """Return identity claims from the validated JWT.

        The fastmcp middleware has already verified the signature and expiry.
        This tool simply reads the claims that are already stored in AccessToken.
        """
        claims = access_token.claims
        return {
            "sub": claims.get("sub"),
            "given_name": claims.get("given_name"),
            "family_name": claims.get("family_name"),
            "email": claims.get("email"),
            "issuer": claims.get("iss"),
        }

    @mcp.tool()
    async def get_user_roles(
        access_token: AccessToken = CurrentAccessToken(),
    ) -> list[str]:
        """Return the Keycloak realm roles from the validated JWT."""
        realm_access = access_token.claims.get("realm_access") or {}
        return realm_access.get("roles", [])

    @mcp.tool()
    async def whoami(
        given_name: str = TokenClaim("given_name"),
        family_name: str = TokenClaim("family_name"),
        access_token: AccessToken = CurrentAccessToken(),
    ) -> str:
        """Return a greeting that includes the user's name and roles.

        Demonstrates using both TokenClaim (single claim shortcut) and the
        full AccessToken object in the same tool.
        """
        realm_access = access_token.claims.get("realm_access") or {}
        roles = [r for r in realm_access.get("roles", []) if not r.startswith("default-")]
        role_str = ", ".join(roles) if roles else "none"
        return f"Hello, {given_name} {family_name}! Your roles: {role_str}"

    @mcp.tool()
    async def verify_with_python_jose(token: str) -> dict[str, Any]:
        """Independently validate a JWT using python-jose and return all claims.

        This tool performs a full JWT validation using python-jose[cryptography]:
          1. Fetches Keycloak's JWKS (cached 1 hour)
          2. Verifies the RS256 signature against the matching JWK
          3. Checks the issuer and expiry claims
          4. Returns the decoded payload

        Pass the access_token you received from Keycloak. This proves the full
        JWKS-based validation chain using python-jose independently of fastmcp's
        built-in middleware.
        """
        try:
            claims = await _validator.validate(token)
            return {
                "valid": True,
                "claims": claims,
                "python_jose_validated": True,
            }
        except JWTValidationError as exc:
            return {
                "valid": False,
                "error": str(exc),
                "python_jose_validated": True,
            }
