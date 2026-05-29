// Reverse proxy for OpenCode. Validates the Keycloak JWT from the httpOnly cookie
// before forwarding any request. This is how OpenCode is "SSO-protected" without
// OpenCode natively supporting Keycloak.
//
// HTML responses are rewritten to replace root-relative asset paths with the
// /api/opencode prefix so the SPA works correctly inside the iframe.

import { NextRequest, NextResponse } from "next/server";
import { getAccessTokenFromCookie, isTokenExpired } from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const OPENCODE_INTERNAL_URL = process.env.OPENCODE_INTERNAL_URL!;
const OPENCODE_SERVER_PASSWORD = process.env.OPENCODE_SERVER_PASSWORD ?? "";
const PROXY_PREFIX = "/api/opencode";

// Headers that must not be forwarded upstream or back to the client
const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
]);

function rewriteHtmlPaths(html: string): string {
  // Rewrite root-relative paths in HTML so assets load through the proxy.
  // Only rewrite paths that start with / but not // (protocol-relative).
  return html.replace(
    /((?:src|href|action|data-src)=["'])\/(?!\/)/g,
    `$1${PROXY_PREFIX}/`
  );
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(req, await params);
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(req, await params);
}

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(req, await params);
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(req, await params);
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyRequest(req, await params);
}

async function proxyRequest(
  req: NextRequest,
  params: { path: string[] }
): Promise<NextResponse> {
  // 1. Auth check
  const token = await getAccessTokenFromCookie();
  if (!token || isTokenExpired(token)) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }

  // 2. Build upstream URL
  const pathSegments = params.path ?? [];
  const upstreamPath = "/" + pathSegments.join("/");
  const search = req.nextUrl.search;
  const upstreamUrl = `${OPENCODE_INTERNAL_URL}${upstreamPath}${search}`;

  // 3. Build forwarded headers
  const forwardHeaders = new Headers();
  for (const [key, value] of req.headers.entries()) {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "host") {
      forwardHeaders.set(key, value);
    }
  }
  const basicAuth = Buffer.from(`opencode:${OPENCODE_SERVER_PASSWORD}`).toString("base64");
  forwardHeaders.set("Authorization", `Basic ${basicAuth}`);
  forwardHeaders.set("X-Forwarded-Host", req.headers.get("host") ?? "localhost:3000");
  forwardHeaders.set("X-Forwarded-Proto", "http");
  forwardHeaders.set("X-Forwarded-Prefix", PROXY_PREFIX);

  // 4. Proxy the request
  let body: BodyInit | null = null;
  if (!["GET", "HEAD"].includes(req.method)) {
    body = await req.arrayBuffer();
  }

  let upstreamRes: Response;
  try {
    upstreamRes = await fetch(upstreamUrl, {
      method: req.method,
      headers: forwardHeaders,
      body,
      // @ts-expect-error — Node 18+ fetch supports duplex for streaming
      duplex: "half",
    });
  } catch (err) {
    console.error("[opencode proxy] fetch error:", err);
    return NextResponse.json(
      { error: "opencode_unavailable" },
      { status: 502 }
    );
  }

  // 5. Build response headers
  const resHeaders = new Headers();
  for (const [key, value] of upstreamRes.headers.entries()) {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      resHeaders.set(key, value);
    }
  }

  // 6. Rewrite HTML to fix root-relative asset paths
  const contentType = upstreamRes.headers.get("content-type") ?? "";
  if (contentType.includes("text/html")) {
    const html = await upstreamRes.text();
    const rewritten = rewriteHtmlPaths(html);
    resHeaders.set("content-type", "text/html; charset=utf-8");
    resHeaders.delete("content-length");
    return new NextResponse(rewritten, {
      status: upstreamRes.status,
      headers: resHeaders,
    });
  }

  return new NextResponse(upstreamRes.body, {
    status: upstreamRes.status,
    headers: resHeaders,
  });
}
