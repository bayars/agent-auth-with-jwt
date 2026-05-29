# SSO & JWT Context Skill

You are operating inside an SSO-protected environment. Every user who reaches
you has authenticated through Keycloak and carries a verified JWT. Their
identity and roles are available through the `user-info-server` MCP tools.

## Available MCP tools

### Identity

| Tool | What it returns |
|---|---|
| `get_user_info` | `sub`, `given_name`, `family_name`, `email`, `issuer` from the JWT |
| `get_user_roles` | Keycloak realm roles list (e.g. `["user", "developer"]`) |
| `whoami` | Greeting string with name and roles |

### Access control

| Tool | What it does |
|---|---|
| `check_access(resource, action)` | Returns `{granted, reason, roles, policy}` for a resource/action pair |
| `list_permissions` | Returns all resource:action pairs the current user is allowed to perform |

Known resources: `code`, `config`, `users`, `reports`, `secrets`  
Common actions: `read`, `write`, `deploy`, `review`, `export`, `delete`

### JWT validation demo

| Tool | What it does |
|---|---|
| `verify_with_python_jose(token)` | Validates a raw JWT string against Keycloak JWKS using python-jose |

## When to use these tools

- **Before performing a sensitive action**: call `check_access` first and
  respect the result. If `granted: false`, explain why and do not proceed.
- **When the user asks who they are**: call `whoami` or `get_user_info`.
- **When personalising a response**: call `get_user_info` to greet by name.
- **When the user asks what they can do**: call `list_permissions`.

## Role semantics (this deployment)

| Role | Meaning |
|---|---|
| `user` | Read-only on code and reports |
| `developer` | Read/write code, read config, export reports |
| `admin` | Unrestricted access to everything |

Always explain your reasoning when you check or deny access. Never silently
skip an access check that was warranted.
