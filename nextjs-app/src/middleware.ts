import { NextRequest, NextResponse } from "next/server";
import { decodeJwt } from "jose";
import { refreshAccessToken } from "@/lib/auth/keycloak";

const PUBLIC_PREFIXES = ["/api/auth", "/_next", "/favicon.ico"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((p) => pathname.startsWith(p));
}

function getTokenFromCookies(req: NextRequest): string | null {
  return req.cookies.get("kc_access_token")?.value ?? null;
}

function getRefreshTokenFromCookies(req: NextRequest): string | null {
  return req.cookies.get("kc_refresh_token")?.value ?? null;
}

function isExpired(token: string, bufferSeconds = 30): boolean {
  try {
    const { exp } = decodeJwt(token);
    return !exp || Date.now() / 1000 >= exp - bufferSeconds;
  } catch {
    return true;
  }
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (isPublic(pathname)) {
    return NextResponse.next();
  }

  const accessToken = getTokenFromCookies(req);

  if (!accessToken) {
    return NextResponse.redirect(new URL("/api/auth/login", req.url));
  }

  if (!isExpired(accessToken)) {
    return NextResponse.next();
  }

  // Token is expired — try to refresh
  const refreshToken = getRefreshTokenFromCookies(req);
  if (!refreshToken) {
    return NextResponse.redirect(new URL("/api/auth/login", req.url));
  }

  try {
    const tokens = await refreshAccessToken(refreshToken);
    const response = NextResponse.next();
    const cookieOpts = {
      httpOnly: true,
      sameSite: "lax" as const,
      secure: process.env.NODE_ENV === "production",
      path: "/",
    };
    response.cookies.set("kc_access_token", tokens.access_token, {
      ...cookieOpts,
      maxAge: tokens.expires_in,
    });
    response.cookies.set("kc_refresh_token", tokens.refresh_token, {
      ...cookieOpts,
      maxAge: tokens.refresh_expires_in,
    });
    return response;
  } catch {
    const loginUrl = new URL("/api/auth/login", req.url);
    const response = NextResponse.redirect(loginUrl);
    response.cookies.delete("kc_access_token");
    response.cookies.delete("kc_refresh_token");
    return response;
  }
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
