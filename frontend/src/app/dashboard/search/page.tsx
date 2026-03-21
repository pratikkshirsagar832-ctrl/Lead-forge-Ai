'use client';

import { useState, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useSearch } from '@/hooks/useSearch';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { SearchProgressCard } from '@/components/dashboard/SearchProgressCard';
import { MapPin, Briefcase, SearchIcon, AlertCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const searchSchema = z.object({
  niche: z.string().min(2, 'Niche must be at least 2 characters'),
  location: z.string().min(2, 'Location must be at least 2 characters'),
});

type SearchSchema = z.infer<typeof searchSchema>;

export default function SearchPage() {
  const { 
    activeSearchId, 
    progress, 
    isStarting, 
    isCancelling, 
    startSearch, 
    cancelSearch,
    resumePollingIfActive
  } = useSearch();

  const { register, handleSubmit, formState: { errors } } = useForm<SearchSchema>({
    resolver: zodResolver(searchSchema),
  });

  // Resume polling on mount if there's an active ID in store
  useEffect(() => {
    resumePollingIfActive();
  }, [resumePollingIfActive]);

  const onSubmit = async (data: SearchSchema) => {
    await startSearch(data.niche, data.location);
  };

  const isSearchActive = activeSearchId && progress && !['completed', 'failed', 'cancelled'].includes(progress.status);

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold text-white tracking-tight">New Search</h1>
        <p className="text-slate-400 mt-2">Find and qualify leads instantly from Google Maps.</p>
      </div>

      <AnimatePresence mode="wait">
        {!isSearchActive ? (
          <motion.div
            key="form"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.3 }}
          >
            <GlassCard className="p-8 max-w-3xl mx-auto border-slate-800 bg-slate-900/50">
              <form onSubmit={handleSubmit(onSubmit)} className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">
                      Target Niche
                    </label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Briefcase className="h-5 w-5 text-slate-400" />
                      </div>
                      <input
                        {...register('niche')}
                        type="text"
                        placeholder="e.g. Plumbers, Dentists"
                        className="w-full pl-10 pr-4 py-3 rounded-xl border border-slate-700 bg-slate-800/50 focus:bg-slate-800 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all text-white text-lg placeholder-slate-500"
                      />
                    </div>
                    {errors.niche && <p className="text-red-500 text-sm mt-1.5">{errors.niche.message}</p>}
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">
                      Location
                    </label>
                    <div className="relative">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <MapPin className="h-5 w-5 text-slate-400" />
                      </div>
                      <input
                        {...register('location')}
                        type="text"
                        placeholder="e.g. Dallas TX, London UK"
                        className="w-full pl-10 pr-4 py-3 rounded-xl border border-slate-700 bg-slate-800/50 focus:bg-slate-800 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all text-white text-lg placeholder-slate-500"
                      />
                    </div>
                    {errors.location && <p className="text-red-500 text-sm mt-1.5">{errors.location.message}</p>}
                  </div>
                </div>

                <div className="bg-indigo-500/10 p-4 rounded-xl border border-indigo-500/20 flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
                  <p className="text-sm text-indigo-200 leading-relaxed">
                    LeadForge will scrape Google Maps for <span className="font-semibold px-1 text-indigo-100">up to 50 targeted</span> results, extract websites, and run them through our AI analyzer. The process usually takes 2-10 minutes depending on the city.
                  </p>
                </div>

                <div className="pt-2">
                  <LoadingButton
                    type="submit"
                    isLoading={isStarting}
                    size="lg"
                    fullWidth
                    className="text-lg py-4 shadow-xl shadow-indigo-600/20"
                  >
                    <SearchIcon className="w-5 h-5" />
                    Start Search Pipeline
                  </LoadingButton>
                </div>
              </form>
            </GlassCard>
            
            {/* Show recent completed/failed search progress if just finished */}
            {progress && (
              <SearchProgressCard onCancel={cancelSearch} isCancelling={isCancelling} />
            )}
          </motion.div>
        ) : (
          <motion.div
            key="progress"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
          >
            <SearchProgressCard onCancel={cancelSearch} isCancelling={isCancelling} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
