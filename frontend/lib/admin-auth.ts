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

export function sessionToken(): string {
  if (!ADMIN_PASSWORD) return '';
  return crypto.createHash('sha256').update(`${ADMIN_PASSWORD}:${SALT}`).digest('hex');
}

export function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return ab.length === bb.length && crypto.timingSafeEqual(ab, bb);
}

function requestIsSecure(req: NextRequest): boolean {
  // nginx/Vercel set x-forwarded-proto; take the first hop.
  const proto = req.headers.get('x-forwarded-proto');
  return !!proto && proto.split(',')[0].trim() === 'https';
}

export function isAuthed(req: NextRequest): boolean {
  if (!ADMIN_PASSWORD) return false;
  const expected = sessionToken();
  const plain = req.cookies.get(SESSION_COOKIE)?.value;
  const host = req.cookies.get(HOST_SESSION_COOKIE)?.value;
  return (!!plain && safeEqual(plain, expected)) || (!!host && safeEqual(host, expected));
}

export function sessionCookieHeader(maxAge: number, secure: boolean): string {
  const name = secure ? HOST_SESSION_COOKIE : SESSION_COOKIE;
  const secureFlag = secure ? ' Secure;' : '';
  return `${name}=${sessionToken()}; Path=/; HttpOnly;${secureFlag} SameSite=Lax; Max-Age=${maxAge}`;
}

function clearCookieHeader(name: string): string {
  const secureFlag = name.startsWith('__Host-') ? ' Secure;' : '';
  return `${name}=; Path=/; HttpOnly;${secureFlag} SameSite=Lax; Max-Age=0`;
}

export function clearSessionCookieHeaders(): string[] {
  return [clearCookieHeader(SESSION_COOKIE), clearCookieHeader(HOST_SESSION_COOKIE)];
}
