// Proxy for FastMCP. Accepts either:
//   (a) the kc_access_token httpOnly cookie — browser/iframe path
//   (b) an Authorization: Bearer header — server-to-server path (OpenCode process)
// Forwards whichever JWT is available to FastMCP as Authorization: Bearer.

import { NextRequest, NextResponse } from "next/server";
import { getAccessTokenFromCookie, isTokenExpired } from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const FASTMCP_INTERNAL_URL = process.env.FASTMCP_INTERNAL_URL!;

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

async function resolveToken(req: NextRequest): Promise<string | null> {
  // Prefer the cookie (browser session); fall back to Bearer header (server-to-server)
  const cookieToken = await getAccessTokenFromCookie();
  if (cookieToken && !isTokenExpired(cookieToken)) {
    return cookieToken;
  }

  const authHeader = req.headers.get("authorization");
  if (authHeader?.startsWith("Bearer ")) {
    const bearerToken = authHeader.slice(7);
    if (!isTokenExpired(bearerToken)) {
      return bearerToken;
    }
  }

  return null;
}

async function proxyToFastMcp(
  req: NextRequest,
  params: { path: string[] }
): Promise<NextResponse> {
  const token = await resolveToken(req);
  if (!token) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }

  const pathSegments = params.path ?? [];
  const upstreamPath = "/" + pathSegments.join("/");
  const search = req.nextUrl.search;
  const upstreamUrl = `${FASTMCP_INTERNAL_URL}${upstreamPath}${search}`;

  const forwardHeaders = new Headers();
  for (const [key, value] of req.headers.entries()) {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "host") {
      forwardHeaders.set(key, value);
    }
  }
  forwardHeaders.set("Authorization", `Bearer ${token}`);

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
      // @ts-expect-error — Node 18+ fetch duplex
      duplex: "half",
    });
  } catch (err) {
    console.error("[mcp proxy] fetch error:", err);
    return NextResponse.json({ error: "fastmcp_unavailable" }, { status: 502 });
  }

  const resHeaders = new Headers();
  for (const [key, value] of upstreamRes.headers.entries()) {
    if (!HOP_BY_HOP.has(key.toLowerCase())) {
      resHeaders.set(key, value);
    }
  }

  return new NextResponse(upstreamRes.body, {
    status: upstreamRes.status,
    headers: resHeaders,
  });
}

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToFastMcp(req, await params);
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToFastMcp(req, await params);
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToFastMcp(req, await params);
}
