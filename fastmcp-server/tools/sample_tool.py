"""
sample_tool.py — check_access MCP tool.

Demonstrates practical JWT+SSO usage: MCP tools can enforce role-based access
control because the caller's Keycloak roles arrive with every request.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import AccessToken, CurrentAccessToken

# ── RBAC policy ──────────────────────────────────────────────────────────────
# resource → action → set of roles that may perform it.
# "admin" role is a wildcard: permitted on every resource/action via the check.
_POLICY: dict[str, dict[str, list[str]]] = {
    "code": {
        "read":   ["user", "developer", "admin"],
        "write":  ["developer", "admin"],
        "deploy": ["admin"],
        "review": ["developer", "admin"],
    },
    "config": {
        "read":   ["developer", "admin"],
        "write":  ["admin"],
    },
    "users": {
        "read":   ["admin"],
        "write":  ["admin"],
        "delete": ["admin"],
    },
    "reports": {
        "read":   ["user", "developer", "admin"],
        "export": ["developer", "admin"],
    },
    "secrets": {
        "read":   ["admin"],
        "write":  ["admin"],
    },
}


def _check(roles: list[str], resource: str, action: str) -> tuple[bool, str]:
    """Return (granted: bool, reason: str)."""
    if "admin" in roles:
        return True, "admin role grants unrestricted access"

    permitted = _POLICY.get(resource, {}).get(action, [])
    if not permitted:
        return False, f"unknown resource '{resource}' or action '{action}'"

    matching = [r for r in roles if r in permitted]
    if matching:
        return True, f"role '{matching[0]}' is allowed to {action} {resource}"

    return False, (
        f"none of your roles {roles} are in the allowed set "
        f"{permitted} for {resource}:{action}"
    )


# ── Tool registration ─────────────────────────────────────────────────────────

def register_sample_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def check_access(
        resource: str,
        action: str,
        access_token: AccessToken = CurrentAccessToken(),
    ) -> dict[str, Any]:
        """Check whether the authenticated user may perform an action on a resource.

        Uses the Keycloak realm roles embedded in the JWT to enforce a simple
        role-based access control (RBAC) policy. No database or external service
        is queried — the JWT is the authoritative source of truth.

        Args:
            resource: Target resource. Known resources: code, config, users,
                      reports, secrets.
            action:   Requested action. Common actions: read, write, deploy,
                      export, delete.

        Returns a dict with:
            - granted (bool): whether access is allowed
            - reason (str): human-readable explanation
            - user (str): subject identifier from JWT
            - roles (list[str]): the caller's current roles
            - policy (dict): full allowed-roles for this resource/action
        """
        realm_access = access_token.claims.get("realm_access") or {}
        raw_roles: list[str] = realm_access.get("roles", [])
        # Strip Keycloak's auto-generated default-roles-* entries for cleaner output
        roles = [r for r in raw_roles if not r.startswith("default-roles-")]

        granted, reason = _check(roles, resource, action)

        return {
            "granted": granted,
            "reason": reason,
            "user": access_token.claims.get("sub", "unknown"),
            "email": access_token.claims.get("email", ""),
            "roles": roles,
            "policy": _POLICY.get(resource, {}).get(action, []),
            "resource": resource,
            "action": action,
        }

    @mcp.tool()
    async def list_permissions(
        access_token: AccessToken = CurrentAccessToken(),
    ) -> dict[str, Any]:
        """List all resources and actions the authenticated user is allowed to access.

        Iterates the full RBAC policy and checks each resource/action combination
        against the caller's JWT roles. Returns a per-resource summary.
        """
        realm_access = access_token.claims.get("realm_access") or {}
        roles = [
            r for r in realm_access.get("roles", [])
            if not r.startswith("default-roles-")
        ]

        allowed: dict[str, list[str]] = {}
        for resource, actions in _POLICY.items():
            permitted_actions = [
                action
                for action, allowed_roles in actions.items()
                if "admin" in roles or any(r in allowed_roles for r in roles)
            ]
            if permitted_actions:
                allowed[resource] = permitted_actions

        return {
            "user": access_token.claims.get("sub", "unknown"),
            "email": access_token.claims.get("email", ""),
            "roles": roles,
            "allowed": allowed,
        }
