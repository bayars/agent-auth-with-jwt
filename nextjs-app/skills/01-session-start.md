# Session Start Protocol

Run this at the very start of every conversation — before answering anything.

## Sequence

### Step 1 — Fetch full identity (user-info-server)
Call **both** tools to get all fields needed for the session:
```
info  = get_user_info()   → {sub, given_name, family_name, email, issuer}
roles = get_user_roles()  → ["developer", "user", ...]
```
`get_user_info()` returns a structured dict — no string parsing needed.

### Step 2 — Check the knowledge base (rag server)
```
cols = list_collections()
```
If the `rag-demo` collection is absent or has 0 documents:
```
seed_demo("rag-demo")
```
This seeds 6 project documents so RAG queries work immediately.

### Step 3 — Greet the user
Format: `"Hello, {given_name}! You have {roles} access."`
If roles include `developer` or `admin`, mention you can ingest documents.
If roles are only `user`, mention read-only access to knowledge base and reports.

## What to store for the session

```
USER_NAME  = "{info.given_name} {info.family_name}"
USER_EMAIL = info.email
USER_ROLES = roles                  (list from get_user_roles())
USER_SUB   = info.sub               (JWT subject — scopes job ownership)
```

## How user identity flows to tools

Two MCP call paths exist:

| Path | Token | Use case |
|---|---|---|
| Browser → Next.js /api/mcp → FastMCP | User's personal JWT | When you're called from the browser UI |
| OpenCode server → FastMCP | Service account JWT | When OpenCode calls tools server-side |

In both cases, the tools receive a valid JWT and extract identity from it.
For role-gated operations, always check USER_ROLES before calling the tool —
the JWT validation on the server side will also enforce it as a second line of defense.
