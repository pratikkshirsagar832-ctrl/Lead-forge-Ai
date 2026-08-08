'use client';

import { useSearchStore } from '@/stores/searchStore';
import { Badge } from '@/components/shared/Badge';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { SEARCH_STATUSES } from '@/lib/constants';
import { motion } from 'framer-motion';
import { Loader2, CheckCircle, XCircle, Search, Sparkles } from 'lucide-react';
import Link from 'next/link';

interface SearchProgressCardProps {
  onCancel: () => void;
  isCancelling: boolean;
}

export function SearchProgressCard({ onCancel, isCancelling }: SearchProgressCardProps) {
  const { progress } = useSearchStore();

  const isFinished = progress ? ['completed', 'failed', 'cancelled'].includes(progress.status ?? '') : false;
  const statusConfig = progress
    ? SEARCH_STATUSES[(progress.status ?? 'queued') as keyof typeof SEARCH_STATUSES] || SEARCH_STATUSES.queued
    : SEARCH_STATUSES.queued;
  const percentage = progress ? (isFinished ? 100 : Math.max(5, progress.progress_percent || 0)) : 0;

  if (!progress) return null;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, y: 10 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      className="max-w-3xl mx-auto mt-8 relative"
    >
      {/* Premium glow border */}
      <div className="absolute -inset-[1px] bg-gradient-to-r from-steel/30 via-violet/20 to-teal/20 rounded-2xl blur opacity-30 animate-pulse-slow" />
      <div className="relative bg-gradient-to-br from-sapphire/50 to-navy/90 rounded-2xl p-8 border border-steel/25 shadow-2xl shadow-black/40 overflow-hidden">

        {/* Ambient glow */}
        <div className="absolute top-0 right-0 -mr-20 -mt-20 w-64 h-64 rounded-full bg-steel/10 blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 left-0 -ml-20 -mb-20 w-80 h-80 rounded-full bg-violet/10 blur-3xl pointer-events-none" />

        <div className="relative z-10">
              <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-8 gap-4">
            <div>
              <div className="flex items-center gap-3 mb-1.5">
                <h3 className="text-xl font-bold text-offwhite tracking-tight" style={{ fontFamily: 'var(--font-heading)' }}>
                  Search Progress
                </h3>
                <Badge variant={
                  progress.status === 'completed' ? 'success' :
                  progress.status === 'failed' ? 'error' :
                  progress.status === 'cancelled' ? 'outline' : 'info'
                } dot>
                  {statusConfig.label}
                </Badge>
              </div>
              <p className="text-sm text-ice/60 font-medium">{progress.message || 'Initializing pipeline...'}</p>
            </div>
          </div>

          {/* Premium progress bar */}
          <div className="relative h-2.5 bg-navy/60 rounded-full overflow-hidden mb-8 shadow-inner border border-steel/15">
            <motion.div
              className={`absolute top-0 left-0 h-full rounded-full ${
                progress.status === 'failed' ? 'bg-gradient-to-r from-rose-500 to-rose-400' :
                progress.status === 'cancelled' ? 'bg-gradient-to-r from-ice/30 to-ice/20' :
                'bg-gradient-to-r from-steel via-violet to-teal'
              }`}
              initial={{ width: 0 }}
              animate={{ width: `${percentage}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            >
              {!isFinished && (
                <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-shimmer" />
              )}
            </motion.div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-8">
            <div className="bg-steel/[0.03] rounded-xl p-5 border border-steel/10 hover:bg-steel/[0.05] transition-colors relative overflow-hidden group">
              <div className="absolute inset-0 bg-gradient-to-br from-steel/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="relative z-10">
                <div className="flex items-center gap-2 mb-2">
                  <Search className="w-4 h-4 text-steel" />
                  <p className="text-xs font-semibold text-ice/60 uppercase tracking-wider">Total Found</p>
                </div>
                <p className="text-3xl font-bold text-offwhite tracking-tight">{progress.total_results || 0}</p>
              </div>
            </div>

            <div className="bg-steel/[0.03] rounded-xl p-5 border border-steel/10 hover:bg-steel/[0.05] transition-colors relative overflow-hidden group">
              <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="relative z-10">
                <div className="flex items-center gap-2 mb-2">
                  <CheckCircle className="w-4 h-4 text-emerald-400" />
                  <p className="text-xs font-semibold text-ice/60 uppercase tracking-wider">Processed</p>
                </div>
                <p className="text-3xl font-bold text-offwhite tracking-tight">{progress.processed_count || 0}</p>
              </div>
            </div>

            <div className="bg-steel/[0.03] rounded-xl p-5 border border-steel/10 md:col-span-1 flex items-center justify-center">
              <div className="shrink-0 p-3 rounded-full bg-steel/10 border border-steel/20">
                {!isFinished ? (
                  <Loader2 className="w-5 h-5 text-steel animate-spin" />
                ) : progress.status === 'completed' ? (
                  <CheckCircle className="w-6 h-6 text-emerald-400" />
                ) : (
                  <XCircle className="w-6 h-6 text-rose-400" />
                )}
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-6 border-t border-steel/15 relative z-10">
            {!isFinished ? (
              <>
                <LoadingButton
                  variant="outline"
                  onClick={onCancel}
                  isLoading={isCancelling}
                  className="border-steel/30 text-ice hover:text-offwhite hover:bg-steel/10"
                >
                  Cancel Process
                </LoadingButton>
              </>
            ) : (
              <>
                {progress.status === 'completed' && (progress.total_results || 0) > 0 && (
                  <Link
                    href="/dashboard/leads"
                    className="inline-flex items-center justify-center px-6 py-2.5 font-semibold rounded-xl text-offwhite bg-gradient-to-r from-steel to-violet hover:from-steel/90 hover:to-violet/90 transition-all shadow-lg shadow-steel/20 hover:shadow-xl hover:shadow-violet/30 group"
                  >
                    <span>View Leads Dashboard</span>
                    <svg className="w-4 h-4 ml-2 group-hover:translate-x-1 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path d="M5 12h14m-6-6 6 6-6 6" />
                    </svg>
                  </Link>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
