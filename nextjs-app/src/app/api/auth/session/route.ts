import { NextResponse } from "next/server";
import { getSessionUser } from "@/lib/auth/session";

// Returns public session info (no raw JWT) for use by client components.
export async function GET() {
  const user = await getSessionUser();
  if (!user) {
    return NextResponse.json({ error: "unauthenticated" }, { status: 401 });
  }
  return NextResponse.json(user);
}
