"""
JWT validator using python-jose[cryptography].

This class fetches Keycloak's JWKS, caches it for one hour, and uses
python-jose to fully validate JWTs (signature, issuer, expiry).
It is used directly inside MCP tools to demonstrate raw python-jose validation,
separate from the fastmcp KeycloakAuthProvider middleware validation.
"""

import time
from typing import Any

import httpx
from jose import JWTError, jwk, jwt
from jose.exceptions import ExpiredSignatureError


class JWTValidationError(Exception):
    pass


class JWTValidator:
    def __init__(
        self,
        jwks_uri: str,
        issuer: str,
        algorithms: list[str] | None = None,
    ) -> None:
        self._jwks_uri = jwks_uri
        self._issuer = issuer
        self._algorithms = algorithms or ["RS256"]
        self._jwks_cache: dict | None = None
        self._cache_expires_at: float = 0.0
        self._cache_ttl = 3600  # 1 hour

    async def _get_jwks(self) -> dict:
        now = time.monotonic()
        if self._jwks_cache and now < self._cache_expires_at:
            return self._jwks_cache

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self._jwks_uri)
            resp.raise_for_status()
            self._jwks_cache = resp.json()
            self._cache_expires_at = now + self._cache_ttl
            return self._jwks_cache

    async def validate(self, token: str) -> dict[str, Any]:
        """Validate a JWT against Keycloak's JWKS.

        Returns the full decoded claims dict on success.
        Raises JWTValidationError on any failure.
        """
        try:
            jwks = await self._get_jwks()
        except httpx.HTTPError as exc:
            raise JWTValidationError(f"Failed to fetch JWKS: {exc}") from exc

        # python-jose can decode with a JWKS dict directly.
        # We set verify_aud=False because Keycloak tokens may not have a simple aud.
        try:
            claims = jwt.decode(
                token,
                jwks,
                algorithms=self._algorithms,
                issuer=self._issuer,
                options={"verify_aud": False},
            )
            return claims
        except ExpiredSignatureError as exc:
            raise JWTValidationError("Token has expired") from exc
        except JWTError as exc:
            raise JWTValidationError(f"Token validation failed: {exc}") from exc
