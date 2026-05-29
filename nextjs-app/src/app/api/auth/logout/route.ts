import { NextRequest, NextResponse } from "next/server";
import { buildLogoutUrl } from "@/lib/auth/keycloak";
import { clearSessionCookies } from "@/lib/auth/session";

export async function GET(req: NextRequest) {
  await clearSessionCookies();
  const postRedirectUri = new URL("/", req.url).toString();
  const logoutUrl = buildLogoutUrl(postRedirectUri);
  return NextResponse.redirect(logoutUrl);
}
