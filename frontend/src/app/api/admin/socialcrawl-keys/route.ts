import { NextRequest } from 'next/server';
import { adminProxy } from '../../../../../lib/admin-backend';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function GET(req: NextRequest) {
  return adminProxy(req, 'socialcrawl-keys', 'GET');
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => ({}));
  return adminProxy(req, 'socialcrawl-keys', 'POST', { key: String(body?.key || ''), label: String(body?.label || '') });
}
