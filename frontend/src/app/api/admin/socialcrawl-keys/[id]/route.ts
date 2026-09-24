import { NextRequest } from 'next/server';
import { adminProxy } from '../../../../../../lib/admin-backend';

export const runtime = 'nodejs';

type Ctx = { params: Promise<{ id: string }> };

export async function PATCH(req: NextRequest, { params }: Ctx) {
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  return adminProxy(req, `socialcrawl-keys/${encodeURIComponent(id)}`, 'PATCH', { enabled: !!body?.enabled });
}

export async function DELETE(req: NextRequest, { params }: Ctx) {
  const { id } = await params;
  return adminProxy(req, `socialcrawl-keys/${encodeURIComponent(id)}`, 'DELETE');
}
