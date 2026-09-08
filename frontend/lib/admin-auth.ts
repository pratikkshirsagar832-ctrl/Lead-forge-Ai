import { NextRequest } from 'next/server';
import crypto from 'crypto';

// There must never be a fallback credential in source control.  A missing
// secret deliberately makes the admin surface unavailable until deployment is
// configured correctly.
export const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || '';
// __Host- prefix: only accepted over HTTPS with Path=/ and no Domain — the
// attributes below satisfy that, and the prefix makes the cookie unreadable by
// any sibling site on the same registrable domain even if it finds a path/Domain
// injection elsewhere.
export const SESSION_COOKIE = '__Host-hc_admin_session';
const SALT = 'hyperclients-admin-v1';

export function sessionToken(): string {
  if (!ADMIN_PASSWORD) return '';
  return crypto.createHash('sha256').update(`${ADMIN_PASSWORD}:${SALT}`).digest('hex');
}

export function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return ab.length === bb.length && crypto.timingSafeEqual(ab, bb);
}

export function isAuthed(req: NextRequest): boolean {
  if (!ADMIN_PASSWORD) return false;
  const cookie = req.cookies.get(SESSION_COOKIE)?.value;
  return !!cookie && safeEqual(cookie, sessionToken());
}

export function sessionCookieHeader(maxAge: number): string {
  // Secure + no Domain + Path=/ are REQUIRED for the __Host- name; browsers
  // still permit Secure cookies on http://localhost, so local dev works.
  return `${SESSION_COOKIE}=${sessionToken()}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
}

export function clearCookieHeader(): string {
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;
}
