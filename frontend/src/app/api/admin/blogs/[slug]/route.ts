import { NextRequest, NextResponse } from 'next/server';
import { isAuthed } from '../../../../../../lib/admin-auth';
import { updateBlog, deleteBlog } from '../../../../../../lib/blog-store';

export const runtime = 'nodejs';

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { slug } = await params;
  const body = await req.json().catch(() => null);
  if (!body) return NextResponse.json({ error: 'Invalid payload' }, { status: 400 });
  let result: { post?: unknown; error?: string };
  try {
    result = updateBlog(slug, body);
  } catch (err) {
    console.error('[admin/blogs] update failed', err);
    return NextResponse.json({ error: 'Could not save the post (storage write failed)' }, { status: 500 });
  }
  if (result.error) return NextResponse.json({ error: result.error }, { status: 400 });
  return NextResponse.json({ blog: result.post });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { slug } = await params;
  let result: { ok?: boolean; error?: string };
  try {
    result = deleteBlog(slug);
  } catch (err) {
    console.error('[admin/blogs] delete failed', err);
    return NextResponse.json({ error: 'Could not delete the post (storage write failed)' }, { status: 500 });
  }
  if (!result.ok) return NextResponse.json({ error: result.error || 'Post not found' }, { status: 404 });
  return NextResponse.json({ ok: true });
}