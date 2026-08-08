import { NextRequest } from 'next/server';
import crypto from 'crypto';

export const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || '@PatilHyperclients@1234';
export const SESSION_COOKIE = 'hc_admin_session';
const SALT = 'hyperclients-admin-v1';

export function sessionToken(): string {
  return crypto.createHash('sha256').update(`${ADMIN_PASSWORD}:${SALT}`).digest('hex');
}

export function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(String(a));
  const bb = Buffer.from(String(b));
  return ab.length === bb.length && crypto.timingSafeEqual(ab, bb);
}

export function isAuthed(req: NextRequest): boolean {
  const cookie = req.cookies.get(SESSION_COOKIE)?.value;
  return !!cookie && safeEqual(cookie, sessionToken());
}

export function sessionCookieHeader(maxAge: number): string {
  return `${SESSION_COOKIE}=${sessionToken()}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${maxAge}`;
}

export function clearCookieHeader(): string {
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`;
}