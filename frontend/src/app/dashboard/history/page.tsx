'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { API_ROUTES } from '@/lib/constants';
import { GlassCard } from '@/components/shared/GlassCard';
import { Badge } from '@/components/shared/Badge';
import { Skeleton } from '@/components/shared/Skeleton';
import { EmptyState } from '@/components/dashboard/EmptyState';
import { formatDistanceToNow } from 'date-fns';
import { Search, MapPin, Briefcase, ChevronRight } from 'lucide-react';
import Link from 'next/link';
import { motion } from 'framer-motion';

export default function HistoryPage() {
  const [history, setHistory] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchHistory = async () => {
      try {
        const { data } = await api.get(API_ROUTES.searches.list);
        setHistory(data.items || []);
      } catch (error) {
        console.error('Failed to fetch history', error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchHistory();
  }, []);

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold text-white tracking-tight">Search History</h1>
        <p className="text-slate-400 mt-2">View logs of all your past scraping operations.</p>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map(i => <Skeleton key={i} className="h-24 w-full rounded-2xl" />)}
        </div>
      ) : history.length === 0 ? (
        <EmptyState 
          title="No history yet" 
          description="You haven't run any searches yet. Start your first scrape to see it here."
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
              <GlassCard className="p-0 overflow-hidden group border-slate-800 bg-slate-900/50">
                <Link 
                  href="/dashboard/search" // If we wanted a specific result page we could, but typical app links to active search or leads filtered
                  className="flex flex-col sm:flex-row items-start sm:items-center justify-between p-6 hover:bg-slate-800/50 transition-colors gap-6"
                >
                  <div className="flex gap-4 items-start">
                    <div className="w-12 h-12 rounded-xl bg-indigo-500/10 flex items-center justify-center shrink-0">
                      <Search className="w-5 h-5 text-indigo-400" />
                    </div>
                    <div>
                      <div className="flex gap-3 items-center mb-1">
                        <h3 className="font-bold text-slate-100 text-lg flex items-center gap-2">
                          {item.niche}
                        </h3>
                        <Badge variant={
                          item.status === 'completed' ? 'success' :
                          item.status === 'failed' ? 'error' :
                          item.status === 'cancelled' ? 'outline' : 'info'
                        } className="capitalize text-xs">
                          {item.status}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-4 text-sm text-slate-500">
                        <span className="flex items-center gap-1.5"><MapPin className="w-4 h-4" /> {item.location}</span>
                        <span>•</span>
                        <span>{formatDistanceToNow(new Date(item.created_at), { addSuffix: true })}</span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-8 w-full sm:w-auto mt-4 sm:mt-0 pt-4 sm:pt-0 border-t sm:border-0 border-slate-800">
                    <div className="text-center sm:text-right flex-1 sm:flex-none">
                      <p className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Found</p>
                      <p className="text-xl font-bold text-slate-100">{item.total_results}</p>
                    </div>
                    <div className="text-center sm:text-right flex-1 sm:flex-none">
                      <p className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">Processed</p>
                      <p className="text-xl font-bold text-slate-100">{(item.hot_leads || 0) + (item.warm_leads || 0) + (item.skipped || 0)}</p>
                    </div>
                    <ChevronRight className="w-5 h-5 text-slate-500 group-hover:text-indigo-400 group-hover:translate-x-1 transition-all shrink-0 hidden sm:block" />
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
