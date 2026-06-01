# HTTP Caller Tools

All tools are from the `http-caller` MCP server.
They make outbound HTTP requests from within the deployment network.

## Tools

| Tool | Description |
|---|---|
| `fetch_url(url, method, headers, body, timeout)` | Generic HTTP request — full control |
| `fetch_json(url, headers, timeout)` | GET + parse JSON response |
| `post_json(url, payload, headers, timeout)` | POST JSON body + parse JSON response |

## Return shape (fetch_url)

```json
{
  "status":    200,
  "ok":        true,
  "url":       "https://...",   // final URL after redirects
  "headers":   {...},
  "body":      "...",           // first 50 000 bytes
  "truncated": false
}
```

On error (timeout, DNS, TLS):
```json
{"error": "timeout", "url": "https://...", "timeout_seconds": 30}
```

## Usage examples

**Check an external API:**
```
fetch_json("https://api.open-meteo.com/v1/forecast?latitude=52&longitude=13&current_weather=true")
```

**POST data to a webhook:**
```
post_json("https://hooks.example.com/notify", {"event": "deploy", "user": USER_EMAIL})
```

**Check internal Keycloak health:**
```
fetch_url("http://keycloak:8080/health/ready")
```

## Domain allow-list

The server may be configured with `ALLOWED_DOMAINS` to restrict which hosts
can be reached. If a domain is blocked, the tool returns:
`{"error": "Domain 'x.y.z' is not in the allowed list: [...]"}`

Advise the user to contact the administrator to add the domain if needed.

## Security note

Do not pass secrets (API keys, passwords) in URLs or unencrypted request bodies
unless the target endpoint uses HTTPS. Always use the `headers` parameter for
`Authorization` headers.
