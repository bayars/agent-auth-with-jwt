import { NextRequest, NextResponse } from "next/server";
import { exchangeCodeForTokens } from "@/lib/auth/keycloak";
import { setSessionCookies } from "@/lib/auth/session";

export async function GET(req: NextRequest) {
  const { searchParams } = req.nextUrl;
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const error = searchParams.get("error");

  if (error) {
    const desc = searchParams.get("error_description") ?? error;
    return NextResponse.redirect(
      new URL(`/api/auth/login?error=${encodeURIComponent(desc)}`, req.url)
    );
  }

  if (!code || !state) {
    return NextResponse.redirect(
      new URL("/api/auth/login?error=missing_params", req.url)
    );
  }

  const savedState = req.cookies.get("pkce_state")?.value;
  if (!savedState || savedState !== state) {
    return NextResponse.redirect(
      new URL("/api/auth/login?error=state_mismatch", req.url)
    );
  }

  const verifier = req.cookies.get("pkce_verifier")?.value;
  if (!verifier) {
    return NextResponse.redirect(
      new URL("/api/auth/login?error=missing_verifier", req.url)
    );
  }

  try {
    const tokens = await exchangeCodeForTokens(code, verifier);
    await setSessionCookies(
      tokens.access_token,
      tokens.refresh_token,
      tokens.expires_in,
      tokens.refresh_expires_in
    );
  } catch (err) {
    const msg = err instanceof Error ? err.message : "token_exchange_failed";
    return NextResponse.redirect(
      new URL(`/api/auth/login?error=${encodeURIComponent(msg)}`, req.url)
    );
  }

  const response = NextResponse.redirect(new URL("/", req.url));
  // Clear PKCE cookies
  response.cookies.delete("pkce_verifier");
  response.cookies.delete("pkce_state");
  return response;
}
