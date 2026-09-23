import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(date: string | Date | null | undefined): string {
  if (!date) return '—';
  return new Date(date).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  });
}

export function formatDateTime(date: string | Date | null | undefined): string {
  if (!date) return '—';
  return new Date(date).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

/** "5h ago" / "2d ago" for exact timestamps; plain date for day-only values
 * (older LinkedIn leads only stored the day, so an hour count would be fake). */
export function formatPostedAgo(date: string | null | undefined): string {
  if (!date) return '—';
  const d = new Date(date);
  if (Number.isNaN(d.getTime())) return '—';
  // Day-only values (and rows backfilled to exact UTC midnight) carry no real
  // time of day — show the date instead of a fake hour count.
  if (!date.includes('T') || /T00:00:00(\.0+)?(Z|\+00:00)?$/.test(date)) return formatDate(date);
  const mins = Math.max(0, Math.round((Date.now() - d.getTime()) / 60000));
  if (mins < 60) return `${Math.max(1, mins)}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** Short display name for whatever the user typed as their service:
 * "I am a freelance video editor for YouTubers" -> "Video editor".
 * Mirrors the backend cleanup loosely (display only). Returns '' when the text
 * is a long description, so callers can fall back to a generic label. */
export function serviceLabel(raw: string | null | undefined): string {
  let s = (raw || '').replace(/[^\p{L}\p{N}\s&+/,.'-]/gu, ' ').replace(/\s+/g, ' ').trim();
  s = s.replace(/^(hi|hello|hey)\b[\s,!.]*/i, '');
  s = s.replace(/^(i|we)\s*(am|'m|are|'re)\s+(an?\s+|the\s+)?(freelance\s+|professional\s+|expert\s+)?/i, '');
  s = s.replace(/^(i|we)\s+(do|offer|provide|sell|deliver|build|create|make|design|develop|run|manage|write|edit|specialize in|specialise in)\s+/i, '');
  s = s.replace(/^(looking for|need|want|find|get)\s+(me\s+)?(new\s+)?(clients|leads|customers|work|projects)\s+(for|in)\s+(my\s+|our\s+)?/i, '');
  s = s.replace(/\s+(for|to|in|at|with|near)\s+.*$/i, '');
  s = s.replace(/\s+(services?|business|freelancing|freelancer|expert|specialist|company|studio|agency)\.?$/i, '');
  s = s.trim();
  if (!s || s.split(' ').length > 5) return '';
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function formatNumber(n: number | null | undefined): string {
  if (n == null) return '0';
  return n.toLocaleString();
}

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

export function truncate(text: string, max: number = 100): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + '…';
}

export function getInitials(name: string | null | undefined): string {
  if (!name) return '?';
  return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
}
