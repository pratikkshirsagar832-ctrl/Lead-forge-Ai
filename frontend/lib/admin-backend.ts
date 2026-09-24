import { NextRequest, NextResponse } from 'next/server';
import { isAuthed } from './admin-auth';

/**
 * Server-side bridge from the /admin panel to the backend's admin endpoints.
 * The browser only ever talks to these Next.js routes (admin cookie); the
 * backend is called with ADMIN_API_TOKEN, which never leaves the server.
 */
const BACKEND = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

export async function adminProxy(req: NextRequest, path: string, method: string, body?: unknown): Promise<NextResponse> {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const token = process.env.ADMIN_API_TOKEN || '';
  if (!token) return NextResponse.json({ error: 'ADMIN_API_TOKEN is not set on the frontend server.' }, { status: 503 });
  try {
    const res = await fetch(`${BACKEND}/api/internal/admin/${path}`, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-Admin-Token': token },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = (data as { detail?: unknown }).detail;
      return NextResponse.json({ error: typeof detail === 'string' ? detail : `Backend error (${res.status})` }, { status: res.status });
    }
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    console.error('[admin-backend] request failed', err);
    return NextResponse.json({ error: 'Backend is unreachable.' }, { status: 502 });
  }
}
