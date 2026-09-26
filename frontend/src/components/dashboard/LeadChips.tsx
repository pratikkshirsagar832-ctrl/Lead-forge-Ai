import { Clock, Flame } from 'lucide-react';
import { formatPostedAgo } from '@/lib/utils';

/** Hours since an ISO timestamp (null when unparseable). */
function hoursSince(iso: string): number | null {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : (Date.now() - t) / 3_600_000;
}

/** Age of a LinkedIn post, coloured by freshness: <24h mint (live dot),
 *  <3 days amber, older grey. Renders nothing without a timestamp. */
export function FreshnessChip({ postedAt, className = '' }: { postedAt?: string | null; className?: string }) {
  if (!postedAt) return null;
  const hours = hoursSince(postedAt);
  if (hours == null) return null;
  const tone = hours < 24
    ? 'text-steel bg-steel/10 ring-steel/25'
    : hours < 72
      ? 'text-brand-accent bg-brand-accent/10 ring-brand-accent/25'
      : 'text-ice/50 bg-white/5 ring-white/10';
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-semibold ring-1 tabular ${tone} ${className}`}>
      {hours < 24 ? (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full rounded-full bg-steel opacity-70 motion-safe:animate-ping" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-steel" />
        </span>
      ) : (
        <Clock className="h-3 w-3" />
      )}
      {formatPostedAgo(postedAt)}
    </span>
  );
}

/** Shown when the buyer's need reads as pressing (provider urgency >= 2 of 3). */
export function UrgencyChip({ urgency, className = '' }: { urgency?: number | null; className?: string }) {
  if (urgency == null || urgency < 2) return null;
  return (
    <span className={`inline-flex items-center gap-1 rounded-md bg-brand-accent/15 px-1.5 py-0.5 text-[10px] font-bold text-brand-accent ring-1 ring-brand-accent/30 ${className}`}>
      <Flame className="h-3 w-3" /> Urgent
    </span>
  );
}
