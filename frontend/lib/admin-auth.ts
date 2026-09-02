import { NextRequest } from 'next/server';
import crypto from 'crypto';

// There must never be a fallback credential in source control.  A missing
// secret deliberately makes the admin surface unavailable until deployment is
// configured correctly.
export const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || '';
export const SESSION_COOKIE = 'hc_admin_session';
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
  return `${SESSION_COOKIE}=${sessionToken()}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`;
}

export function clearCookieHeader(): string {
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`;
}
