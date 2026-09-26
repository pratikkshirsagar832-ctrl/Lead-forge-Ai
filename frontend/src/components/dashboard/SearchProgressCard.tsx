'use client';

import { useEffect, useState } from 'react';
import { useSearchStore } from '@/stores/searchStore';
import { Badge } from '@/components/shared/Badge';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { GlassCard } from '@/components/shared/GlassCard';
import { SEARCH_STATUSES } from '@/lib/constants';
import { motion } from 'framer-motion';
import { CheckCircle, XCircle, Users, ScanSearch, Timer, MapPin, Linkedin, ArrowRight, Lightbulb } from 'lucide-react';
import Link from 'next/link';

interface SearchProgressCardProps {
  onCancel: () => void;
  isCancelling: boolean;
}

// Why a search ended short, in plain words, plus what to try next.
const STOP_REASON_HELP: Record<string, { title: string; tip: string }> = {
  empty_rounds_stop: { title: 'No more new buyers were posting right now', tip: 'Try again later today, or describe your service more broadly (e.g. "video editing" instead of "YouTube shorts editing").' },
  ceiling_hit: { title: 'This search reached its limit before finding more', tip: 'Try a broader wording or the other lane (Freelancer / Agency).' },
  deadline_hit: { title: 'This search ran out of time', tip: 'Run it again - new buyer posts appear every hour.' },
  query_pool_exhausted: { title: 'We tried every phrasing for this niche', tip: 'Use a more common name for your service, or add a second service.' },
  iteration_cap: { title: 'This search reached its maximum rounds', tip: 'Run it again later for fresh posts.' },
};

function formatElapsed(total: number): string {
  const s = Math.max(0, Math.floor(total));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${String(s % 60).padStart(2, '0')}s` : `${s}s`;
}

/** 3D radar: a tilted ring with a sweeping beam while the search runs. */
function Radar({ state }: { state: 'running' | 'completed' | 'failed' }) {
  if (state !== 'running') {
    const ok = state === 'completed';
    return (
      <motion.span
        initial={{ scale: 0.6, rotateY: -90, opacity: 0 }}
        animate={{ scale: 1, rotateY: 0, opacity: 1 }}
        transition={{ type: 'spring', stiffness: 260, damping: 18 }}
        className={`${ok ? 'tile-3d text-steel' : 'bg-rose-500/15 text-rose-400 ring-1 ring-rose-500/30'} grid h-16 w-16 place-items-center rounded-2xl`}
      >
        {ok ? <CheckCircle className="h-8 w-8" /> : <XCircle className="h-8 w-8" />}
      </motion.span>
    );
  }
  return (
    <div className="stage-3d grid h-16 w-16 place-items-center" aria-hidden="true">
      <div className="preserve-3d relative h-16 w-16 [transform:rotateX(58deg)]">
        <div className="absolute inset-0 rounded-full border border-steel/40 shadow-[0_0_24px_rgba(79,216,195,0.35)]" />
        <div className="absolute inset-3 rounded-full border border-steel/25" />
        <div className="absolute inset-0 rounded-full bg-[conic-gradient(from_0deg,rgba(79,216,195,0.55),transparent_28%)] motion-safe:animate-spin [animation-duration:1.6s]" />
      </div>
      <span className="absolute h-2.5 w-2.5 rounded-full bg-brand-accent shadow-[0_0_14px_rgba(255,176,32,0.9)]" />
    </div>
  );
}

export function SearchProgressCard({ onCancel, isCancelling }: SearchProgressCardProps) {
  const { progress } = useSearchStore();
  const isFinished = progress ? ['completed', 'failed', 'cancelled'].includes(progress.status ?? '') : false;
  const statusConfig = progress
    ? SEARCH_STATUSES[(progress.status ?? 'queued') as keyof typeof SEARCH_STATUSES] || SEARCH_STATUSES.queued
    : SEARCH_STATUSES.queued;
  const percentage = progress ? (isFinished ? 100 : Math.max(5, progress.progress_percent || 0)) : 0;

  // Elapsed ticks locally between polls so the timer feels live.
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (isFinished) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [isFinished, progress?.elapsed_seconds]);
  useEffect(() => { setTick(0); }, [progress?.elapsed_seconds]);

  // "Found" stays honest to the requested count: never the number of posts
  // reviewed, only delivered leads, capped at what was asked for.
  const requestedCount = progress?.requested_count ?? null;
  const totalFound = progress?.total_results ?? 0;
  const displayedFound = requestedCount ? Math.min(Number(totalFound), Number(requestedCount)) : Number(totalFound);

  if (!progress) return null;

  const isLinkedIn = progress.source === 'linkedin';
  const radarState = !isFinished ? 'running' : progress.status === 'completed' ? 'completed' : 'failed';
  const stopHelp = isFinished && progress.stop_reason && progress.stop_reason !== 'target_reached'
    && requestedCount != null && displayedFound < requestedCount
    ? STOP_REASON_HELP[progress.stop_reason] : undefined;

  const stats = [
    { label: 'Leads found', value: requestedCount ? `${displayedFound} / ${requestedCount}` : String(displayedFound), icon: Users },
    { label: isLinkedIn ? 'Posts checked' : 'Processed', value: String(progress.processed_count || 0), icon: ScanSearch },
    { label: 'Time', value: formatElapsed((progress.elapsed_seconds || 0) + (isFinished ? 0 : tick)), icon: Timer },
  ];

  return (
    <GlassCard className="max-w-3xl mx-auto mt-2 rounded-3xl p-6 md:p-8">
      <div className="flex items-start gap-5">
        <Radar state={radarState} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 mb-1.5">
            <h3 className="text-xl font-bold text-offwhite tracking-tight" style={{ fontFamily: 'var(--font-heading)' }}>
              {!isFinished ? 'Searching' : progress.status === 'completed' ? 'Search complete' : progress.status === 'cancelled' ? 'Search cancelled' : 'Search stopped'}
            </h3>
            <Badge variant={
              progress.status === 'completed' ? 'success' :
              progress.status === 'failed' ? 'error' :
              progress.status === 'cancelled' ? 'outline' : 'info'
            } dot>
              {statusConfig.label}
            </Badge>
            <Badge variant="outline" className="text-[10px] gap-1">
              {isLinkedIn ? <Linkedin className="w-3 h-3 text-steel" /> : <MapPin className="w-3 h-3 text-brand-accent" />}
              {isLinkedIn ? 'LinkedIn' : 'Maps'}
            </Badge>
          </div>
          <p className="text-sm text-ice/65 leading-relaxed" aria-live="polite">{progress.message || 'Starting your search...'}</p>
        </div>
      </div>

      {/* Lit progress bar in a sunken track */}
      <div
        className="well-3d relative mt-7 h-3 rounded-full overflow-hidden"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percentage)}
      >
        <motion.div
          className={`absolute inset-y-0 left-0 rounded-full ${
            progress.status === 'failed' ? 'bg-gradient-to-r from-rose-500 to-rose-400' :
            progress.status === 'cancelled' ? 'bg-ice/25' :
            'bg-gradient-to-r from-teal via-steel to-brand-accent shadow-[0_0_18px_rgba(79,216,195,0.55)]'
          }`}
          initial={{ width: 0 }}
          animate={{ width: `${percentage}%` }}
          transition={{ type: 'spring', stiffness: 60, damping: 18 }}
        >
          {!isFinished && (
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/25 to-transparent animate-shimmer" />
          )}
        </motion.div>
      </div>

      <div className="mt-6 grid grid-cols-3 gap-3">
        {stats.map(({ label, value, icon: Icon }) => (
          <div key={label} className="well-3d rounded-2xl p-4">
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-ice/50">
              <Icon className="h-3.5 w-3.5 text-steel" /> {label}
            </div>
            <p className="mt-1.5 text-2xl md:text-3xl font-bold text-offwhite tracking-tight tabular" style={{ fontFamily: 'var(--font-heading)' }}>
              {value}
            </p>
          </div>
        ))}
      </div>

      {stopHelp && (
        <div className="mt-5 flex items-start gap-3 rounded-2xl bg-brand-accent/[0.07] p-4 ring-1 ring-brand-accent/20">
          <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-brand-accent" />
          <div>
            <p className="text-sm font-semibold text-offwhite">{stopHelp.title}</p>
            <p className="mt-0.5 text-xs text-ice/60 leading-relaxed">{stopHelp.tip}</p>
          </div>
        </div>
      )}

      <div className="mt-6 flex justify-end gap-3">
        {!isFinished ? (
          <LoadingButton
            variant="outline"
            onClick={onCancel}
            isLoading={isCancelling}
            className="border-steel/30 text-ice hover:text-offwhite hover:bg-steel/10"
          >
            Cancel search
          </LoadingButton>
        ) : (
          progress.status === 'completed' && (progress.total_results || 0) > 0 && (
            <Link href="/dashboard/leads" className="btn-3d-gold group inline-flex h-11 items-center gap-2 rounded-xl px-6">
              View leads
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
          )
        )}
      </div>
    </GlassCard>
  );
}
