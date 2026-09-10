import { NextResponse } from 'next/server';
import { clearSessionCookieHeaders } from '../../../../../lib/admin-auth';

export const runtime = 'nodejs';

export async function POST() {
  const res = NextResponse.json({ ok: true });
  // Clear both cookie variants so a scheme change cannot strand a session.
  for (const header of clearSessionCookieHeaders()) {
    res.headers.append('Set-Cookie', header);
  }
  return res;
}