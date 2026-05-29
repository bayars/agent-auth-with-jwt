// Custom Next.js server — required to proxy WebSocket connections from the browser
// to the OpenCode container. Next.js App Router API routes cannot handle WS upgrades,
// so we intercept them here before Next.js routing takes over.
const { createServer } = require("http");
const { parse } = require("url");
const next = require("next");
const { WebSocketServer, WebSocket } = require("ws");

const dev = process.env.NODE_ENV !== "production";
const app = next({ dev });
const handle = app.getRequestHandler();

const OPENCODE_INTERNAL_URL = process.env.OPENCODE_INTERNAL_URL || "http://opencode:4321";
const OPENCODE_WS_URL = OPENCODE_INTERNAL_URL.replace(/^http/, "ws");
const OPENCODE_SERVER_PASSWORD = process.env.OPENCODE_SERVER_PASSWORD || "";
const OPENCODE_PROXY_PREFIX = "/api/opencode";

function getTokenFromCookieHeader(cookieHeader) {
  if (!cookieHeader) return null;
  const match = cookieHeader.match(/(?:^|;\s*)kc_access_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function isTokenExpired(token) {
  try {
    const payload = JSON.parse(
      Buffer.from(token.split(".")[1], "base64url").toString()
    );
    return Date.now() / 1000 >= payload.exp - 10;
  } catch {
    return true;
  }
}

app.prepare().then(() => {
  const server = createServer((req, res) => {
    const parsedUrl = parse(req.url, true);
    handle(req, res, parsedUrl);
  });

  // WebSocket proxy for OpenCode
  server.on("upgrade", (req, socket, head) => {
    const { pathname } = parse(req.url);

    if (!pathname.startsWith(OPENCODE_PROXY_PREFIX)) {
      socket.destroy();
      return;
    }

    // Validate JWT from cookie before upgrading
    const token = getTokenFromCookieHeader(req.headers.cookie);
    if (!token || isTokenExpired(token)) {
      socket.write("HTTP/1.1 401 Unauthorized\r\n\r\n");
      socket.destroy();
      return;
    }

    // Strip the /api/opencode prefix and forward the rest
    const upstreamPath = pathname.slice(OPENCODE_PROXY_PREFIX.length) || "/";
    const upstreamUrl = `${OPENCODE_WS_URL}${upstreamPath}${req.url.includes("?") ? "?" + req.url.split("?")[1] : ""}`;

    const upstream = new WebSocket(upstreamUrl, {
      headers: {
        host: new URL(OPENCODE_INTERNAL_URL).host,
        authorization: `Basic ${Buffer.from(`opencode:${OPENCODE_SERVER_PASSWORD}`).toString("base64")}`,
      },
    });

    const wss = new WebSocketServer({ noServer: true });
    wss.handleUpgrade(req, socket, head, (client) => {
      upstream.on("open", () => {
        client.on("message", (data) => upstream.send(data));
        upstream.on("message", (data) => client.send(data));
        client.on("close", () => upstream.close());
        upstream.on("close", () => client.close());
        client.on("error", () => upstream.close());
        upstream.on("error", () => client.close());
      });
      upstream.on("error", (err) => {
        console.error("[WS proxy] upstream error:", err.message);
        client.close(1011, "upstream error");
      });
    });
  });

  const port = parseInt(process.env.PORT || "3000", 10);
  server.listen(port, () => {
    console.log(`> Ready on http://localhost:${port}`);
  });
});
