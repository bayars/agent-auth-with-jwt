// PKCE helpers using the Web Crypto API (available in both Edge and Node runtimes)

function base64url(buf: ArrayBuffer): string {
  return Buffer.from(buf)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

export function generateCodeVerifier(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(96));
  return base64url(bytes.buffer);
}

export async function generateCodeChallenge(verifier: string): Promise<string> {
  const encoded = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest("SHA-256", encoded);
  return base64url(digest);
}

export function generateState(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return base64url(bytes.buffer);
}
