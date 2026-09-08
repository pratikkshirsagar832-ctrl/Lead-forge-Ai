import { NextRequest, NextResponse } from 'next/server';
import { isAuthed } from '../../../../../lib/admin-auth';
import crypto from 'crypto';

export const runtime = 'nodejs';

const MAX_BYTES = 5 * 1024 * 1024;
// SVG is intentionally excluded: served from public storage it can carry
// scripts (stored XSS on the blog). Only raster formats are accepted.
const ALLOWED = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);

/** Content-Type from the client is spoofable — verify the magic bytes. */
function sniffType(bytes: Uint8Array): string | null {
  const ascii = (off: number, len: number) =>
    String.fromCharCode(...Array.from(bytes.subarray(off, off + len)));
  if (bytes.length >= 4 && ascii(0, 4) === '\x89PNG') return 'image/png';
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return 'image/jpeg';
  if (bytes.length >= 12 && ascii(0, 4) === 'RIFF' && ascii(8, 4) === 'WEBP') return 'image/webp';
  if (bytes.length >= 6 && ascii(0, 4) === 'GIF8') return 'image/gif';
  return null;
}

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
    return NextResponse.json({ error: 'Only PNG, JPG, WEBP or GIF images allowed' }, { status: 400 });
  }
  if (file.size > MAX_BYTES) {
    return NextResponse.json({ error: 'Image must be under 5MB' }, { status: 400 });
  }

  const bytes = new Uint8Array(await file.arrayBuffer());
  const sniffed = sniffType(bytes);
  if (!sniffed || sniffed !== type) {
    return NextResponse.json({ error: 'File content does not match its declared image type' }, { status: 400 });
  }

  const ext = sniffed === 'image/png' ? 'png' : sniffed === 'image/jpeg' ? 'jpg' : sniffed === 'image/webp' ? 'webp' : 'gif';
  const name = `${Date.now()}-${crypto.randomBytes(4).toString('hex')}.${ext}`;
  const buf = Buffer.from(bytes);

  const res = await fetch(`${supabaseUrl}/storage/v1/object/blog-images/${name}`, {
    method: 'POST',
    headers: {
      apikey: serviceKey,
      Authorization: `Bearer ${serviceKey}`,
      'Content-Type': sniffed,
      'x-upsert': 'false',
    },
    body: buf,
  });

  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    return NextResponse.json({ error: `Upload failed (${res.status})`, detail }, { status: 500 });
  }

  return NextResponse.json({ url: `${supabaseUrl}/storage/v1/object/public/blog-images/${name}` });
}