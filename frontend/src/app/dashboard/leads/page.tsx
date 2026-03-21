'use client';

import { useEffect } from 'react';
import { useLeads } from '@/hooks/useLeads';
import { FiltersBar } from '@/components/dashboard/FiltersBar';
import { LeadCard } from '@/components/dashboard/LeadCard';
import { EmptyState } from '@/components/dashboard/EmptyState';
import { CardSkeleton } from '@/components/shared/Skeleton';
import { motion } from 'framer-motion';

export default function LeadsPage() {
  const { 
    leads, 
    totalCount, 
    isLoading, 
    fetchLeads, 
    filters,
    setFilters,
    toggleFavorite,
    isUpdating
  } = useLeads();

  // Fetch leads whenever filters change
  useEffect(() => {
    fetchLeads();
  }, [fetchLeads, filters.status, filters.category, filters.isFavorite, filters.page, filters.search]);

  // Debounced search trigger handled by directly typing and wait could be added, 
  // but standard practice is a submit or simple quick API if fast enough.
  // The useEffect triggers it automatically on state change.

  const totalPages = Math.ceil(totalCount / filters.limit);

  return (
    <div className="space-y-6 animate-in fade-in duration-500 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6 relative">
        <div className="absolute -inset-10 bg-gradient-to-r from-indigo-500/10 via-purple-500/5 to-transparent blur-3xl rounded-full pointer-events-none -z-10" />
        
        <div className="relative">
          <h1 className="text-3xl font-extrabold text-white tracking-tight flex items-center gap-3">
            Leads Pipeline
            <span className="flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-3 w-3 rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
            </span>
          </h1>
          <p className="text-slate-400 mt-2 text-sm font-medium">Manage, filter, and review scraped leads from your search campaigns.</p>
        </div>
        <div className="relative">
          <div className="absolute -inset-0.5 bg-gradient-to-r from-indigo-500 to-purple-500 rounded-xl blur opacity-30" />
          <div className="relative flex items-center gap-2 text-sm font-bold text-white bg-slate-900 border border-white/10 px-4 py-2 rounded-xl shadow-2xl">
            <span className="text-indigo-400">{totalCount.toLocaleString()}</span> total found
          </div>
        </div>
      </div>

      <FiltersBar />

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {[1, 2, 3, 4, 5, 6, 7, 8].map(i => <CardSkeleton key={i} />)}
        </div>
      ) : leads.length === 0 ? (
        <div className="relative z-10 p-12 text-center bg-slate-900/50 border border-white/5 rounded-2xl">
          <EmptyState 
            title="No leads match your criteria" 
            description="Try removing some filters, changing your search params, or running a new LeadForge AI search operation altogether."
            actionText="Initialize Search Pipeline"
            actionHref="/dashboard/search"
          />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
            {leads.map((lead, idx) => (
              <motion.div
                key={lead.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: idx * 0.05 }}
              >
                <LeadCard 
                  lead={lead} 
                  onToggleFavorite={toggleFavorite} 
                  isUpdatingFav={isUpdating[`${lead.id}_fav`] || false} 
                />
              </motion.div>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex justify-center items-center gap-3 pt-12 pb-16 relative z-10">
              <button
                disabled={filters.page === 1}
                onClick={() => setFilters({ page: filters.page - 1 })}
                className="px-5 py-2.5 rounded-xl bg-slate-900 border border-white/10 font-semibold text-sm text-slate-300 hover:bg-white/5 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                Previous
              </button>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-slate-500">
                  Page <span className="text-white font-bold">{filters.page}</span> of <span className="text-slate-400">{totalPages}</span>
                </span>
              </div>
              <button
                disabled={filters.page >= totalPages}
                onClick={() => setFilters({ page: filters.page + 1 })}
                className="px-5 py-2.5 rounded-xl bg-slate-900 border border-white/10 font-semibold text-sm text-slate-300 hover:bg-white/5 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
