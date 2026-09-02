import { NextRequest, NextResponse } from 'next/server';
import { safeEqual, ADMIN_PASSWORD, sessionCookieHeader } from '../../../../../lib/admin-auth';

export const runtime = 'nodejs';

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const password = body?.password ?? '';
  if (!ADMIN_PASSWORD) {
    return NextResponse.json({ error: 'Admin authentication is not configured' }, { status: 503 });
  }
  if (!password || !safeEqual(String(password), ADMIN_PASSWORD)) {
    return NextResponse.json({ error: 'Invalid password' }, { status: 401 });
  }
  const res = NextResponse.json({ ok: true });
  res.headers.set('Set-Cookie', sessionCookieHeader(60 * 60 * 24 * 30));
  return res;
}
