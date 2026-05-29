"use client";

// OpenCode is served through the Next.js /api/opencode/* proxy.
// The proxy validates the kc_access_token httpOnly cookie before forwarding
// any request, so the user never reaches OpenCode without being authenticated.
// Because both the parent page and this iframe are on the same origin
// (localhost:3000), the browser automatically sends the httpOnly cookie with
// all requests the iframe makes — including MCP calls to /api/mcp/*.
export default function OpenCodeFrame() {
  return (
    <iframe
      src="/api/opencode/"
      className="opencode-iframe"
      allow="clipboard-read; clipboard-write"
      title="OpenCode — AI coding assistant"
    />
  );
}
