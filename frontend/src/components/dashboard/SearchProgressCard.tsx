'use client';

import { useState, useEffect } from 'react';

import { useSearchStore } from '@/stores/searchStore';
import { GlassCard } from '@/components/shared/GlassCard';
import { Badge } from '@/components/shared/Badge';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { formatDuration } from '@/lib/utils';
import { SEARCH_STATUSES } from '@/lib/constants';
import { motion } from 'framer-motion';
import { Loader2, CheckCircle, XCircle, Clock, Search, MapPin } from 'lucide-react';
import Link from 'next/link';

interface SearchProgressCardProps {
  onCancel: () => void;
  isCancelling: boolean;
}

export function SearchProgressCard({ onCancel, isCancelling }: SearchProgressCardProps) {
  const { progress } = useSearchStore();

  if (!progress) return null;

  const statusConfig = SEARCH_STATUSES[progress.status as keyof typeof SEARCH_STATUSES] || SEARCH_STATUSES.queued;
  const isFinished = ['completed', 'failed', 'cancelled'].includes(progress.status);
  
  const totalStages = 5; // queued, scraping, parsing, analyzing, completed
  const currentStage = progress.stage || 0;
  const percentage = isFinished ? 100 : Math.max(5, (currentStage / totalStages) * 100);

  const [localElapsed, setLocalElapsed] = useState(progress.elapsed_seconds || 0);

  useEffect(() => {
    if (isFinished) {
      setLocalElapsed(progress.elapsed_seconds || 0);
      return;
    }

    setLocalElapsed(progress.elapsed_seconds || 0);

    const interval = setInterval(() => {
      setLocalElapsed((prev) => {
        if (progress.started_at) {
          const start = new Date(progress.started_at).getTime();
          const now = Date.now();
          return Math.max(0, Math.floor((now - start) / 1000));
        }
        return prev + 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [progress.started_at, progress.elapsed_seconds, isFinished]);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, y: 10 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      className="max-w-3xl mx-auto mt-8 relative"
    >
      <div className="absolute -inset-0.5 bg-gradient-to-r from-indigo-500 to-purple-500 rounded-2xl blur opacity-20 animate-pulse" />
      <div className="relative bg-slate-900 rounded-2xl p-8 border border-white/10 shadow-2xl overflow-hidden">
        
        {/* Decorative Background Elements */}
        <div className="absolute top-0 right-0 -mr-20 -mt-20 w-64 h-64 rounded-full bg-indigo-500/10 blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 left-0 -ml-20 -mb-20 w-80 h-80 rounded-full bg-purple-500/10 blur-3xl pointer-events-none" />

        <div className="relative z-10">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-8 gap-4">
            <div>
              <div className="flex items-center gap-3 mb-1.5">
                <h3 className="text-xl font-bold text-white tracking-tight">
                  Search Progress
                </h3>
                <Badge variant={
                  progress.status === 'completed' ? 'success' :
                  progress.status === 'failed' ? 'error' :
                  progress.status === 'cancelled' ? 'outline' : 'info'
                } dot className="scale-90 origin-left">
                  {statusConfig.label}
                </Badge>
              </div>
              <p className="text-sm text-slate-400 font-medium">{progress.message || 'Initializing pipeline...'}</p>
            </div>
            
            <div className="flex items-center gap-2.5 text-sm font-semibold text-slate-300 bg-white/5 border border-white/10 px-4 py-2 rounded-xl backdrop-blur-md shadow-inner">
              <Clock className="w-4 h-4 text-indigo-400" />
              <span className="tabular-nums tracking-wider">{formatDuration(localElapsed)}</span>
            </div>
          </div>

          {/* Progress Bar */}
          <div className="relative h-2 bg-slate-800 rounded-full overflow-hidden mb-8 shadow-inner border border-white/5">
            <motion.div
              className={`absolute top-0 left-0 h-full rounded-full ${
                progress.status === 'failed' ? 'bg-rose-500' :
                progress.status === 'cancelled' ? 'bg-slate-600' :
                'bg-gradient-to-r from-indigo-500 to-purple-500'
              }`}
              initial={{ width: 0 }}
              animate={{ width: `${percentage}%` }}
              transition={{ duration: 0.8, ease: 'easeOut' }}
            >
              {!isFinished && (
                <div className="absolute top-0 right-0 bottom-0 w-20 bg-gradient-to-r from-transparent via-white/30 to-transparent animate-shimmer" />
              )}
            </motion.div>
          </div>

          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div className="bg-white/[0.03] rounded-xl p-5 border border-white-[0.05] hover:bg-white/[0.05] transition-colors relative overflow-hidden group">
              <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="relative z-10">
                <div className="flex items-center gap-2 mb-2 opacity-80">
                  <Search className="w-4 h-4 text-indigo-400" />
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Total Found</p>
                </div>
                <p className="text-3xl font-bold text-white tracking-tight">{progress.total_results || 0}</p>
              </div>
            </div>
            
            <div className="bg-white/[0.03] rounded-xl p-5 border border-white-[0.05] hover:bg-white/[0.05] transition-colors relative overflow-hidden group">
              <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="relative z-10">
                <div className="flex items-center gap-2 mb-2 opacity-80">
                  <CheckCircle className="w-4 h-4 text-emerald-400" />
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Processed</p>
                </div>
                <p className="text-3xl font-bold text-white tracking-tight">{progress.processed_count || 0}</p>
              </div>
            </div>

            <div className="bg-white/[0.03] rounded-xl p-5 border border-white-[0.05] md:col-span-2 flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold text-slate-400 mb-1.5 uppercase tracking-wider">Current Action</p>
                <p className="text-sm font-medium text-slate-200 pr-2">
                  {isFinished ? (progress.status === 'completed' ? 'Operations concluded successfully.' : 'Operations halted.') : progress.message || 'Initializing...'}
                </p>
              </div>
              <div className="shrink-0 p-3 rounded-full bg-white/5 border border-white/5">
                {!isFinished ? (
                  <Loader2 className="w-5 h-5 text-indigo-400 animate-spin" />
                ) : progress.status === 'completed' ? (
                  <CheckCircle className="w-6 h-6 text-emerald-400" />
                ) : (
                  <XCircle className="w-6 h-6 text-rose-400" />
                )}
              </div>
            </div>
          </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-6 border-t border-white/10 relative z-10">
          {!isFinished ? (
            <>
              {localElapsed > 120 && (
                <p className="mr-auto text-sm text-amber-400 flex items-center font-medium">
                  Search operation is processing extensive data...
                </p>
              )}
              <LoadingButton 
                variant="outline" 
                onClick={onCancel} 
                isLoading={isCancelling}
                className="border-white/20 text-slate-300 hover:text-white hover:bg-white/10"
              >
                Cancel Process
              </LoadingButton>
            </>
          ) : (
            <>
              {progress.status === 'completed' && (progress.total_results || 0) > 0 && (
                <Link
                  href="/dashboard/leads"
                  className="inline-flex items-center justify-center px-6 py-2.5 font-semibold rounded-xl text-white bg-indigo-600 hover:bg-indigo-500 transition-colors shadow-[0_0_20px_rgba(79,70,229,0.4)] hover:shadow-[0_0_30px_rgba(79,70,229,0.6)]"
                >
                  View Leads Dashboard
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
