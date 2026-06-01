# A2A Agent Delegation

A2A (Agent-to-Agent) protocol lets you delegate high-level tasks to specialist
agents. OpenCode speaks MCP; the a2a-bridge translates to A2A on your behalf.

## Tools (from `a2a-bridge` MCP server)

| Tool | Description |
|---|---|
| `list_a2a_agents()` | Discover all registered A2A agents and their skills |
| `a2a_delegate(agent_url, skill_id, message)` | Submit a task to an agent; waits for result |
| `a2a_task_status(agent_url, task_id)` | Poll a previously submitted task |

## Registered agents

| Agent | URL | Skills |
|---|---|---|
| RAG Knowledge Base | `http://mcp-rag-server:8000` | `knowledge_query`, `knowledge_search`, `ingest_documents` |
| Identity & Access | `http://fastmcp:8000` | `identify_user`, `check_access`, `list_permissions` |

## When to use A2A vs direct MCP tools

| Use A2A when | Use MCP tools directly when |
|---|---|
| Delegating a high-level task to a specialist | Fine-grained control over arguments |
| The task involves multiple steps inside the agent | You want the raw return value |
| You want agent discovery (what agents exist?) | You already know which MCP tool to call |

## Delegation workflow

```
1. list_a2a_agents()
   → returns agents with their skills

2. a2a_delegate(
     agent_url = "http://mcp-rag-server:8000",
     skill_id  = "knowledge_query",
     message   = "How does JWT authentication work?"
   )
   → status: "completed", result_text: "## Retrieved context..."

3. If status = "working" (large ingest):
   → Save task_id
   → Call a2a_task_status(agent_url, task_id) after ~10s
   → Repeat until status = "completed" or "failed"
```

## JWT identity in A2A

The bridge automatically forwards the caller's JWT to the target A2A agent.
This means:
- The RAG agent enforces the same role checks via the forwarded token
- `ingest_documents` requires `developer` or `admin` role — same as the MCP tool
- `identify_user` on the Identity Agent returns the SAME user as `whoami()` on MCP

## A2A skill reference

### RAG Knowledge Base Agent

**`knowledge_query`** — equivalent to `execute(message, collection)`
- Input: plain text question
- Output: formatted Markdown context block (result_text)

**`knowledge_search`** — equivalent to `search(message, collection, top_k=10)`
- Input: plain text query
- Output: `result_data = {results: [{id, content, score, metadata}], count}`

**`ingest_documents`** — equivalent to `ingest(documents, collection)`
- Input: data part = list of `{id, content, metadata}` dicts
- Output (small batch): `result_data = {indexed, total}`
- Output (large batch): `status: working` → poll `a2a_task_status`

### Identity & Access Agent

**`identify_user`** — equivalent to `get_user_info()` + `get_user_roles()`
- Input: any text (ignored)
- Output: `result_data = {sub, given_name, family_name, email, issuer, roles}`

**`check_access`** — equivalent to `check_access(resource, action)`
- Input: `"resource:action"` or `"resource action"` in message text
- Output: `result_data = {granted, reason, roles, resource, action, policy}`

**`list_permissions`** — equivalent to `list_permissions()`
- Input: any text (ignored)
- Output: `result_data = {user, email, roles, allowed: {resource: [actions]}}`
