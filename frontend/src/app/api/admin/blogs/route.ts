import { NextRequest, NextResponse } from 'next/server';
import { isAuthed } from '../../../../../lib/admin-auth';
import { getBlogs, createBlog } from '../../../../../lib/blog-store';

export const runtime = 'nodejs';

export async function GET(req: NextRequest) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  return NextResponse.json({ blogs: getBlogs() });
}

export async function POST(req: NextRequest) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const body = await req.json().catch(() => null);
  if (!body) return NextResponse.json({ error: 'Invalid payload' }, { status: 400 });
  const result = createBlog(body);
  if (result.error) return NextResponse.json({ error: result.error }, { status: 400 });
  return NextResponse.json({ blog: result.post }, { status: 201 });
}