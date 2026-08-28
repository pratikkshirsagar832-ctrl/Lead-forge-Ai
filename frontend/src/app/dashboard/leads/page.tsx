'use client';

import { Suspense, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import { useLeads } from '@/hooks/useLeads';
import { useToast } from '@/hooks/useToast';
import { FiltersBar } from '@/components/dashboard/FiltersBar';
import { LeadCard } from '@/components/dashboard/LeadCard';
import { EmptyState } from '@/components/dashboard/EmptyState';
import { CardSkeleton } from '@/components/shared/Skeleton';
import { motion } from 'framer-motion';
import api from '@/lib/api';

function LeadsContent() {
  const searchParams = useSearchParams();
  const { showToast } = useToast();
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

  useEffect(() => {
    const urlSearchId = searchParams.get('search_id');
    if (urlSearchId && urlSearchId !== filters.searchId) {
      setFilters({ searchId: urlSearchId });
    }
  }, [searchParams, filters.searchId, setFilters]);

  useEffect(() => {
    const timer = setTimeout(() => fetchLeads(), 300);
    return () => clearTimeout(timer);
  }, [fetchLeads, filters.status, filters.category, filters.isFavorite, filters.page, filters.search, filters.searchId]);

  const totalPages = filters.limit > 0 ? Math.ceil(totalCount / filters.limit) : 1;

  return (
    <div className="space-y-6 animate-in fade-in duration-500 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6 relative">
        <div className="absolute -inset-10 bg-gradient-to-r from-steel/10 via-ocean/5 to-transparent blur-3xl rounded-full pointer-events-none -z-10" />

        <div className="relative">
          <h1 className="text-3xl font-extrabold text-offwhite tracking-tight flex items-center gap-3">
            Leads Pipeline
          </h1>
          <p className="text-ice/60 mt-2 text-sm font-medium">Manage, filter, and review discovered leads from your search campaigns.</p>
        </div>
        <div className="relative">
          <div className="absolute -inset-0.5 bg-gradient-to-r from-steel to-ice rounded-xl blur opacity-30" />
          <div className="relative flex items-center gap-2 text-sm font-bold text-offwhite bg-navy border border-steel/20 px-4 py-2 rounded-xl">
            <span className="text-steel">{totalCount.toLocaleString()}</span> total found
          </div>
        </div>
      </div>

      <div className="flex justify-end">
        <button
          onClick={async () => {
            try {
              const { data } = await api.post('/api/hyper-agent/backfill-post-urls');
              showToast(`Repaired ${data.updated} post links`, 'success');
              fetchLeads();
            } catch (e: any) {
              showToast(e?.response?.data?.detail || 'Repair failed', 'error');
            }
          }}
          className="text-xs text-violet hover:underline"
          title="Re-scrape LinkedIn to fill missing post URLs on old leads"
        >
          Repair missing LinkedIn post links
        </button>
      </div>

      <FiltersBar />

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {[1, 2, 3, 4, 5, 6, 7, 8].map(i => <CardSkeleton key={i} />)}
        </div>
      ) : leads.length === 0 ? (
        <div className="relative z-10 p-12 text-center bg-gradient-to-br from-ocean/30 to-navy rounded-2xl">
          <EmptyState
            title="No leads match your criteria"
            description="Try removing some filters, changing your search params, or running a new Hyperclients search operation altogether."
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

          {totalPages > 1 && (
            <div className="flex justify-center items-center gap-3 pt-12 pb-16 relative z-10">
              <button
                disabled={filters.page === 1}
                onClick={() => setFilters({ page: filters.page - 1 })}
                className="px-5 py-2.5 rounded-xl bg-navy border border-steel/30 font-semibold text-sm text-ice hover:bg-steel/10 hover:text-offwhite disabled:opacity-40 disabled:cursor-not-allowed transition-all"
              >
                Previous
              </button>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-ice/60">
                  Page <span className="text-offwhite font-bold">{filters.page}</span> of <span className="text-ice/80">{totalPages}</span>
                </span>
              </div>
              <button
                disabled={filters.page >= totalPages}
                onClick={() => setFilters({ page: filters.page + 1 })}
                className="px-5 py-2.5 rounded-xl bg-navy border border-steel/30 font-semibold text-sm text-ice hover:bg-steel/10 hover:text-offwhite disabled:opacity-40 disabled:cursor-not-allowed transition-all"
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

export default function LeadsPage() {
  return (
    <Suspense fallback={
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {[1, 2, 3, 4, 5, 6, 7, 8].map(i => <CardSkeleton key={i} />)}
      </div>
    }>
      <LeadsContent />
    </Suspense>
  );
}
