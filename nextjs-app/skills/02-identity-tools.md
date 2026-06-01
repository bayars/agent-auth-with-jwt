# Identity and Access Control Tools

All tools below are from the `user-info-server` MCP server.
They require a valid Keycloak JWT (automatically attached to every request).

## Tool reference

| Tool | Returns | When to use |
|---|---|---|
| `whoami()` | `"Hello, {name}! Your roles: {roles}"` | Session start, user asks who they are |
| `get_user_info()` | `{sub, given_name, family_name, email, issuer}` | Personalisation, logging |
| `get_user_roles()` | `["developer", "user", ...]` | Before role-gated operations |
| `check_access(resource, action)` | `{granted, reason, roles, policy}` | Before sensitive operations |
| `list_permissions()` | `{allowed: {resource: [actions]}}` | When user asks "what can I do?" |
| `verify_with_python_jose(token)` | `{valid, claims, python_jose_validated}` | JWT debugging |

## Role semantics

| Role | Permissions |
|---|---|
| `user` | Read code and reports |
| `developer` | Read/write code; read config; export reports; ingest/delete RAG docs |
| `admin` | Unrestricted access to all resources and tools |

## Usage examples

**Before ingesting documents:**
```
roles = get_user_roles()
# If "developer" or "admin" not in roles → explain and stop
```

**Before a sensitive action:**
```
result = check_access("config", "write")
# If result.granted is false → explain result.reason and do not proceed
```

**When asked "what am I allowed to do?":**
```
perms = list_permissions()
# Summarise the allowed dict in plain language
```

## Never silently skip an access check that was warranted.
If `check_access` returns `granted: false`, explain the reason clearly.
Do not attempt the operation and do not suggest workarounds that bypass the policy.
