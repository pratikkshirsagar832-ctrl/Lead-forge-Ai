import { NextRequest } from 'next/server';
import crypto from 'crypto';

// There must never be a fallback credential in source control.  A missing
// secret deliberately makes the admin surface unavailable until deployment is
// configured correctly.
export const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || '';

// The __Host- prefix is only honoured over HTTPS (and browsers refuse to store
// such cookies on plain HTTP).  HTTP deployments — e.g. a bare-IP server behind
// nginx on port 80 — must fall back to the plain name.  Readers accept both
// names so a scheme change never locks an existing session out.
export const SESSION_COOKIE = 'hc_admin_session';
export const HOST_SESSION_COOKIE = `__Host-${SESSION_COOKIE}`;
const SALT = 'hyperclients-admin-v1';

export function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return ab.length === bb.length && crypto.timingSafeEqual(ab, bb);
}

function signSessionPayload(payload: string): string {
  return crypto
    .createHmac('sha256', `${ADMIN_PASSWORD}:${SALT}`)
    .update(payload)
    .digest('hex');
}

/**
 * Issue a session cookie value: `<exp>.<nonce>.<hmac>`.
 *
 * This used to be a single static `sha256(password + salt)` value — identical
 * on every login, never expiring server-side, and therefore a long-lived
 * password-equivalent secret that leaked session validity forever. The token is
 * now unique per login and carries its own expiry, while staying stateless
 * (no session table required).
 */
export function issueSessionToken(maxAgeSeconds: number): string {
  if (!ADMIN_PASSWORD) return '';
  const expiresAt = Math.floor(Date.now() / 1000) + Math.max(60, Math.floor(maxAgeSeconds));
  const nonce = crypto.randomBytes(18).toString('hex');
  const payload = `${expiresAt}.${nonce}`;
  return `${payload}.${signSessionPayload(payload)}`;
}

/** Verify a session cookie value (signature + expiry). */
export function verifySessionToken(token: string | undefined | null): boolean {
  if (!ADMIN_PASSWORD || !token) return false;
  const parts = token.split('.');
  if (parts.length !== 3) return false;
  const [expiresAt, nonce, signature] = parts;
  if (!/^\d{1,12}$/.test(expiresAt)) return false;
  if (!/^[0-9a-f]{16,64}$/.test(nonce)) return false;
  if (!/^[0-9a-f]{64}$/.test(signature)) return false;
  if (!safeEqual(signature, signSessionPayload(`${expiresAt}.${nonce}`))) return false;
  return Number(expiresAt) * 1000 > Date.now();
}

function requestIsSecure(req: NextRequest): boolean {
  // nginx/Vercel set x-forwarded-proto; take the first hop.
  const proto = req.headers.get('x-forwarded-proto');
  return !!proto && proto.split(',')[0].trim() === 'https';
}

export function isAuthed(req: NextRequest): boolean {
  if (!ADMIN_PASSWORD) return false;
  const plain = req.cookies.get(SESSION_COOKIE)?.value;
  const host = req.cookies.get(HOST_SESSION_COOKIE)?.value;
  return verifySessionToken(plain) || verifySessionToken(host);
}

export function sessionCookieHeader(maxAge: number, secure: boolean): string {
  const name = secure ? HOST_SESSION_COOKIE : SESSION_COOKIE;
  const secureFlag = secure ? ' Secure;' : '';
  return `${name}=${issueSessionToken(maxAge)}; Path=/; HttpOnly;${secureFlag} SameSite=Lax; Max-Age=${maxAge}`;
}

function clearCookieHeader(name: string): string {
  const secureFlag = name.startsWith('__Host-') ? ' Secure;' : '';
  return `${name}=; Path=/; HttpOnly;${secureFlag} SameSite=Lax; Max-Age=0`;
}

export function clearSessionCookieHeaders(): string[] {
  return [clearCookieHeader(SESSION_COOKIE), clearCookieHeader(HOST_SESSION_COOKIE)];
}
