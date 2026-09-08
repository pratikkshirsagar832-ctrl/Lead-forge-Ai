import { NextRequest, NextResponse } from 'next/server';
import { safeEqual, ADMIN_PASSWORD, sessionCookieHeader } from '../../../../../lib/admin-auth';

export const runtime = 'nodejs';

// Brute-force protection for the shared admin secret: in-memory per-IP
// sliding window. (Stateless deployments: process-local is acceptable for a
// single-admin panel; if you run many Next instances, terminate behind one
// proxy so each instance still sees most traffic, or move to a shared store.)
const WINDOW_MS = 15 * 60 * 1000; // 15 minutes
const MAX_ATTEMPTS = 8;
const failed: Map<string, number[]> = new Map();

function clientIp(req: NextRequest): string {
  // Behind nginx/Vercel the first X-Forwarded-For hop is the real client.
  const fwd = req.headers.get('x-forwarded-for');
  if (fwd) return fwd.split(',')[0].trim();
  return req.headers.get('x-real-ip') ?? 'unknown';
}

function isLockedOut(ip: string): boolean {
  const now = Date.now();
  const times = (failed.get(ip) || []).filter((t) => now - t < WINDOW_MS);
  failed.set(ip, times);
  return times.length >= MAX_ATTEMPTS;
}

function recordFailure(ip: string): void {
  const now = Date.now();
  const times = (failed.get(ip) || []).filter((t) => now - t < WINDOW_MS);
  times.push(now);
  failed.set(ip, times);
  // Bound memory: drop entries that fell out of the window.
  if (failed.size > 10_000) {
    for (const [k] of failed) {
      failed.set(k, (failed.get(k) || []).filter((t) => now - t < WINDOW_MS));
      if ((failed.get(k) || []).length === 0) failed.delete(k);
    }
  }
}

export async function POST(req: NextRequest) {
  const ip = clientIp(req);
  if (isLockedOut(ip)) {
    return NextResponse.json(
      { error: 'Too many failed attempts. Try again in 15 minutes.' },
      { status: 429 }
    );
  }

  const body = await req.json().catch(() => null);
  const password = body?.password ?? '';
  if (!ADMIN_PASSWORD) {
    return NextResponse.json({ error: 'Admin authentication is not configured' }, { status: 503 });
  }
  if (!password || !safeEqual(String(password), ADMIN_PASSWORD)) {
    recordFailure(ip);
    return NextResponse.json({ error: 'Invalid password' }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.headers.set('Set-Cookie', sessionCookieHeader(60 * 60 * 24 * 30));
  return res;
}
