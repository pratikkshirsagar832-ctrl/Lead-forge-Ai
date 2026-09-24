import { NextRequest } from 'next/server';
import { adminProxy } from '../../../../../../lib/admin-backend';

export const runtime = 'nodejs';

export async function POST(req: NextRequest) {
  return adminProxy(req, 'socialcrawl-keys/refresh', 'POST');
}
