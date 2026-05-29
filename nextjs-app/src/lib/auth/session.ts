// Server-side only — manages the httpOnly session cookies.
// Never call this from a client component.

import { cookies } from "next/headers";
import { decodeJwt } from "jose";

const ACCESS_TOKEN_COOKIE = "kc_access_token";
const REFRESH_TOKEN_COOKIE = "kc_refresh_token";

const BASE_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
};

export async function setSessionCookies(
  accessToken: string,
  refreshToken: string,
  expiresIn: number,
  refreshExpiresIn: number
): Promise<void> {
  const jar = await cookies();
  jar.set(ACCESS_TOKEN_COOKIE, accessToken, {
    ...BASE_COOKIE_OPTIONS,
    maxAge: expiresIn,
  });
  jar.set(REFRESH_TOKEN_COOKIE, refreshToken, {
    ...BASE_COOKIE_OPTIONS,
    maxAge: refreshExpiresIn,
  });
}

export async function clearSessionCookies(): Promise<void> {
  const jar = await cookies();
  jar.set(ACCESS_TOKEN_COOKIE, "", { ...BASE_COOKIE_OPTIONS, maxAge: 0 });
  jar.set(REFRESH_TOKEN_COOKIE, "", { ...BASE_COOKIE_OPTIONS, maxAge: 0 });
}

export async function getAccessTokenFromCookie(): Promise<string | null> {
  const jar = await cookies();
  return jar.get(ACCESS_TOKEN_COOKIE)?.value ?? null;
}

export async function getRefreshTokenFromCookie(): Promise<string | null> {
  const jar = await cookies();
  return jar.get(REFRESH_TOKEN_COOKIE)?.value ?? null;
}

export interface SessionUser {
  sub: string;
  given_name: string;
  family_name: string;
  email: string;
  roles: string[];
}

export async function getSessionUser(): Promise<SessionUser | null> {
  const token = await getAccessTokenFromCookie();
  if (!token) return null;
  try {
    const claims = decodeJwt(token);
    const realmAccess = claims.realm_access as { roles?: string[] } | undefined;
    return {
      sub: claims.sub ?? "",
      given_name: (claims.given_name as string) ?? "",
      family_name: (claims.family_name as string) ?? "",
      email: (claims.email as string) ?? "",
      roles: realmAccess?.roles ?? [],
    };
  } catch {
    return null;
  }
}

export function isTokenExpired(token: string, bufferSeconds = 30): boolean {
  try {
    const claims = decodeJwt(token);
    if (!claims.exp) return true;
    return Date.now() / 1000 >= claims.exp - bufferSeconds;
  } catch {
    return true;
  }
}
