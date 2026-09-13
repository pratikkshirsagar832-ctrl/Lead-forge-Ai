import { NextRequest, NextResponse } from 'next/server';
import { isAuthed } from '../../../../../../lib/admin-auth';
import { saveDraft, deleteDraft, type DraftInput } from '../../../../../../lib/draft-store';

export const runtime = 'nodejs';

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== 'object') return NextResponse.json({ error: 'Invalid payload' }, { status: 400 });
  let result: { draft?: unknown; error?: string };
  try {
    result = saveDraft({ ...(body as DraftInput), id });
  } catch (err) {
    console.error('[admin/drafts] update failed', err);
    return NextResponse.json({ error: 'Could not save the draft (storage write failed)' }, { status: 500 });
  }
  if (result.error) return NextResponse.json({ error: result.error }, { status: 400 });
  return NextResponse.json({ draft: result.draft });
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;
  let result: { ok?: boolean; error?: string };
  try {
    result = deleteDraft(id);
  } catch (err) {
    console.error('[admin/drafts] delete failed', err);
    return NextResponse.json({ error: 'Could not delete the draft (storage write failed)' }, { status: 500 });
  }
  if (!result.ok) return NextResponse.json({ error: result.error || 'Draft not found' }, { status: 404 });
  return NextResponse.json({ ok: true });
}
