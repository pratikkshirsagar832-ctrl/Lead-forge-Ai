import { NextRequest, NextResponse } from 'next/server';
import { isAuthed } from '../../../../../../../lib/admin-auth';
import { publishDraft } from '../../../../../../../lib/draft-store';

export const runtime = 'nodejs';

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { id } = await params;
  let result: { post?: unknown; error?: string };
  try {
    result = publishDraft(id);
  } catch (err) {
    console.error('[admin/drafts] publish failed', err);
    return NextResponse.json({ error: 'Could not publish (storage write failed)' }, { status: 500 });
  }
  if (result.error) return NextResponse.json({ error: result.error }, { status: 400 });
  return NextResponse.json({ blog: result.post }, { status: 201 });
}
