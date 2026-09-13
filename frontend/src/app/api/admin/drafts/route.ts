import { NextRequest, NextResponse } from 'next/server';
import { isAuthed } from '../../../../../lib/admin-auth';
import { getDrafts, saveDraft, publishDueDrafts } from '../../../../../lib/draft-store';

export const runtime = 'nodejs';

export async function GET(req: NextRequest) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  try {
    publishDueDrafts();
  } catch (err) {
    console.error('[admin/drafts] publish-due failed', err);
  }
  return NextResponse.json({ drafts: getDrafts() });
}

export async function POST(req: NextRequest) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== 'object') return NextResponse.json({ error: 'Invalid payload' }, { status: 400 });
  let result: { draft?: unknown; error?: string };
  try {
    result = saveDraft(body);
  } catch (err) {
    console.error('[admin/drafts] save failed', err);
    return NextResponse.json({ error: 'Could not save the draft (storage write failed)' }, { status: 500 });
  }
  if (result.error) return NextResponse.json({ error: result.error }, { status: 400 });
  return NextResponse.json({ draft: result.draft }, { status: 201 });
}
