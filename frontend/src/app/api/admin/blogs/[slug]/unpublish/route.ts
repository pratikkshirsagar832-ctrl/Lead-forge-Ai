import { NextRequest, NextResponse } from 'next/server';
import { isAuthed } from '../../../../../../../lib/admin-auth';
import { unpublishPost } from '../../../../../../../lib/draft-store';

export const runtime = 'nodejs';

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ slug: string }> }
) {
  if (!isAuthed(req)) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  const { slug } = await params;
  let result: { draft?: unknown; error?: string };
  try {
    result = unpublishPost(slug);
  } catch (err) {
    console.error('[admin/blogs] unpublish failed', err);
    return NextResponse.json({ error: 'Could not unpublish (storage write failed)' }, { status: 500 });
  }
  if (result.error) return NextResponse.json({ error: result.error }, { status: 400 });
  return NextResponse.json({ draft: result.draft });
}
