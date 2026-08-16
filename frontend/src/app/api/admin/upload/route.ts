import { NextRequest, NextResponse } from 'next/server';
import { isAuthed } from '../../../../../lib/admin-auth';
import crypto from 'crypto';

export const runtime = 'nodejs';

const MAX_BYTES = 5 * 1024 * 1024;
const ALLOWED = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/svg+xml']);

export async function POST(req: NextRequest) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL?.replace(/\/$/, '');
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceKey) {
    return NextResponse.json({ error: 'Storage not configured' }, { status: 500 });
  }

  const form = await req.formData().catch(() => null);
  const file = form?.get('file');
  if (!file || typeof file === 'string' || !(file instanceof File)) {
    return NextResponse.json({ error: 'No file provided' }, { status: 400 });
  }

  const type = file.type || 'application/octet-stream';
  if (!ALLOWED.has(type)) {
    return NextResponse.json({ error: 'Only PNG, JPG, WEBP, GIF or SVG images allowed' }, { status: 400 });
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json({ error: 'Image must be under 5MB' }, { status: 400 });
  }

  const ext = type === 'image/png' ? 'png' : type === 'image/jpeg' ? 'jpg' : type === 'image/webp' ? 'webp' : type === 'image/gif' ? 'gif' : 'svg';
  const name = `${Date.now()}-${crypto.randomBytes(4).toString('hex')}.${ext}`;
  const bytes = Buffer.from(await file.arrayBuffer());

  const res = await fetch(`${supabaseUrl}/storage/v1/object/blog-images/${name}`, {
    method: 'POST',
    headers: {
      apikey: serviceKey,
      Authorization: `Bearer ${serviceKey}`,
      'Content-Type': type,
      'x-upsert': 'false',
    },
    body: bytes,
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    return NextResponse.json({ error: `Upload failed (${res.status})`, detail }, { status: 500 });
  }

  return NextResponse.json({ url: `${supabaseUrl}/storage/v1/object/public/blog-images/${name}` });
}