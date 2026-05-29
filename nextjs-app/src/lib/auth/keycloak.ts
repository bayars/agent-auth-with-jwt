// Keycloak OIDC helpers — all HTTP calls use fetch() to work in both Edge and Node.

export const KC_URL = process.env.KC_URL!;
export const KC_REALM = process.env.KC_REALM!;
export const KC_CLIENT_ID = process.env.KC_CLIENT_ID!;
export const KC_REDIRECT_URI = process.env.KC_REDIRECT_URI!;

export function tokenEndpoint(): string {
  return `${KC_URL}/realms/${KC_REALM}/protocol/openid-connect/token`;
}

export function authorizationEndpoint(): string {
  return `${KC_URL}/realms/${KC_REALM}/protocol/openid-connect/auth`;
}

export function logoutEndpoint(): string {
  return `${KC_URL}/realms/${KC_REALM}/protocol/openid-connect/logout`;
}

export function jwksUri(): string {
  return `${KC_URL}/realms/${KC_REALM}/protocol/openid-connect/certs`;
}

export function buildAuthorizationUrl(codeChallenge: string, state: string): string {
  const params = new URLSearchParams({
    client_id: KC_CLIENT_ID,
    response_type: "code",
    redirect_uri: KC_REDIRECT_URI,
    scope: "openid profile email",
    code_challenge: codeChallenge,
    code_challenge_method: "S256",
    state,
  });
  return `${authorizationEndpoint()}?${params}`;
}

export function buildLogoutUrl(postRedirectUri: string): string {
  const params = new URLSearchParams({
    client_id: KC_CLIENT_ID,
    post_logout_redirect_uri: postRedirectUri,
  });
  return `${logoutEndpoint()}?${params}`;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  id_token: string;
  expires_in: number;
  refresh_expires_in: number;
  token_type: string;
}

export async function exchangeCodeForTokens(
  code: string,
  codeVerifier: string
): Promise<TokenResponse> {
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: KC_CLIENT_ID,
    redirect_uri: KC_REDIRECT_URI,
    code,
    code_verifier: codeVerifier,
  });

  const res = await fetch(tokenEndpoint(), {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    cache: "no-store",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Token exchange failed (${res.status}): ${text}`);
  }

  return res.json() as Promise<TokenResponse>;
}

export async function refreshAccessToken(
  refreshToken: string
): Promise<TokenResponse> {
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: KC_CLIENT_ID,
    refresh_token: refreshToken,
  });

  const res = await fetch(tokenEndpoint(), {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    cache: "no-store",
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Token refresh failed (${res.status}): ${text}`);
  }

  return res.json() as Promise<TokenResponse>;
}
