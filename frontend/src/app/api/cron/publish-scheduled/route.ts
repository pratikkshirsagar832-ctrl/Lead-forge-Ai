import { NextRequest, NextResponse } from 'next/server';
import { publishDueDrafts } from '../../../../../lib/draft-store';

export const runtime = 'nodejs';

/**
 * Optional exact-time scheduler hook. Point an external cron (cron-job.org,
 * VPS crontab, …) at GET /api/cron/publish-scheduled with:
 *   Authorization: Bearer <CRON_SECRET>
 * Without CRON_SECRET configured the route refuses to run.
 * (Scheduled drafts also publish lazily on every admin API hit, so this is
 * strictly a timeliness enhancement, not a requirement.)
 */
export async function GET(req: NextRequest) {
  const secret = process.env.CRON_SECRET || '';
  if (!secret) {
    return NextResponse.json({ error: 'Cron not configured' }, { status: 503 });
  }
  const header = req.headers.get('authorization') || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : '';
  if (!token || token !== secret) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }
  let result: { published: string[]; failed: { id: string; error: string }[] };
  try {
    result = publishDueDrafts();
  } catch (err) {
    console.error('[cron/publish-scheduled] failed', err);
    return NextResponse.json({ error: 'Publish check failed' }, { status: 500 });
  }
  return NextResponse.json({ ok: true, ...result });
}
