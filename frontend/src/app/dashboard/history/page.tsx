'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { API_ROUTES } from '@/lib/constants';
import { GlassCard } from '@/components/shared/GlassCard';
import { Badge } from '@/components/shared/Badge';
import { Skeleton } from '@/components/shared/Skeleton';
import { EmptyState } from '@/components/dashboard/EmptyState';
import { formatDistanceToNow } from 'date-fns';
import { Search, MapPin, ChevronRight, Linkedin } from 'lucide-react';
import Link from 'next/link';
import { motion } from 'framer-motion';

function safeFormatDistance(date: string | undefined): string {
  if (!date) return 'Unknown date';
  try {
    return formatDistanceToNow(new Date(date), { addSuffix: true });
  } catch {
    return 'Unknown date';
  }
}

export default function HistoryPage() {
  const [history, setHistory] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);

  const fetchHistory = async () => {
    try {
      setHasError(false);
      const { data } = await api.get(API_ROUTES.searches.list);
      setHistory(data.items || []);
    } catch (error) {
      console.error('Failed to fetch history', error);
      setHasError(true);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory();
  }, []);

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold text-offwhite tracking-tight">Search History</h1>
        <p className="text-ice/60 mt-2">View logs of all your past searches.</p>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-24 w-full rounded-2xl" />)}
        </div>
      ) : hasError ? (
        <GlassCard className="p-8 text-center">
          <p className="text-rose-400 mb-4">Failed to load search history. Please try again.</p>
          <button onClick={fetchHistory} className="text-steel hover:text-ice underline text-sm">Retry</button>
        </GlassCard>
      ) : history.length === 0 ? (
        <EmptyState
          title="No history yet"
          description="You haven't run any searches yet. Start your first search to see it here."
          actionText="Start Search"
          actionHref="/dashboard/search"
        />
      ) : (
        <div className="space-y-4">
          {history.map((item, idx) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: idx * 0.05 }}
            >
              <GlassCard className="p-0 overflow-hidden group border-ocean/40 bg-gradient-to-br from-ocean/30 to-navy">
                <Link
                  href={`/dashboard/leads?search_id=${item.id}`}
                  className="flex flex-col sm:flex-row items-start sm:items-center justify-between p-6 hover:bg-steel/5 transition-colors gap-6"
                >
                  <div className="flex gap-4 items-start">
                    <div className="w-12 h-12 rounded-xl bg-steel/10 flex items-center justify-center shrink-0">
                      <Search className="w-5 h-5 text-steel" />
                    </div>
                    <div>
                      <div className="flex gap-3 items-center mb-1">
                        <h3 className="font-bold text-offwhite text-lg flex items-center gap-2">
                          {item.niche}
                        </h3>
                        <Badge variant={
                          item.status === 'completed' ? 'success' :
                          item.status === 'failed' ? 'error' :
                          item.status === 'cancelled' ? 'outline' : 'info'
                        } className="capitalize text-xs">
                          {item.status}
                        </Badge>
                        <Badge variant="outline" className="text-[10px] gap-1">
                          {item.source === 'linkedin' ? <Linkedin className="w-3 h-3 text-sky-400" /> : <MapPin className="w-3 h-3 text-emerald-400" />}
                          {item.source === 'linkedin' ? 'LinkedIn' : 'Maps'}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-4 text-sm text-ice/60">
                        <span className="flex items-center gap-1.5"><MapPin className="w-4 h-4" /> {item.location}</span>
                        <span>•</span>
                        <span>{safeFormatDistance(item.created_at)}</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-8 w-full sm:w-auto mt-4 sm:mt-0 pt-4 sm:pt-0 border-t sm:border-0 border-ocean/30">
                    <div className="text-center sm:text-right flex-1 sm:flex-none">
                      <p className="text-xs font-medium text-ice/60 uppercase tracking-wider mb-1">Found</p>
                      <p className="text-xl font-bold text-offwhite">{item.total_results}</p>
                      {item.emails_found ? (
                        <p className="text-[11px] text-emerald-400 mt-0.5">{item.emails_found} emails</p>
                      ) : null}
                    </div>
                    <div className="text-center sm:text-right flex-1 sm:flex-none">
                      <p className="text-xs font-medium text-ice/60 uppercase tracking-wider mb-1">Processed</p>
                      <p className="text-xl font-bold text-offwhite">{(item.hot_leads || 0) + (item.warm_leads || 0)}</p>
                    </div>
                    <ChevronRight className="w-5 h-5 text-ice/40 group-hover:text-steel group-hover:translate-x-1 transition-all shrink-0 hidden sm:block" />
                  </div>
                </Link>
              </GlassCard>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
