import { NextResponse } from "next/server";
import { generateCodeVerifier, generateCodeChallenge, generateState } from "@/lib/auth/pkce";
import { buildAuthorizationUrl } from "@/lib/auth/keycloak";

export async function GET() {
  const verifier = generateCodeVerifier();
  const challenge = await generateCodeChallenge(verifier);
  const state = generateState();

  const authUrl = buildAuthorizationUrl(challenge, state);

  const cookieOpts = {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 300, // 5 min — enough to complete the PKCE flow
  };

  const response = NextResponse.redirect(authUrl);
  response.cookies.set("pkce_verifier", verifier, cookieOpts);
  response.cookies.set("pkce_state", state, cookieOpts);
  return response;
}
