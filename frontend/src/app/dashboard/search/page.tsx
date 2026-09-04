'use client';

import { useState, useEffect, useMemo, useRef } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';
import { useSearch } from '@/hooks/useSearch';
import api from '@/lib/api';
import type { SubscriptionInfo } from '@/lib/types';
import { Badge } from '@/components/shared/Badge';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { SearchProgressCard } from '@/components/dashboard/SearchProgressCard';
import { UpgradeModal } from '@/components/shared/UpgradeModal';
import { API_ROUTES } from '@/lib/constants';
import { useSearchStore } from '@/stores/searchStore';
import { MapPin, Briefcase, SearchIcon, Sparkles, Globe, Star, Phone, ChevronRight, Users, AlertCircle, Search, Linkedin, Mail, Clock, ExternalLink, Unlock } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import { LEAD_CATEGORIES } from '@/lib/constants';

const mapsSchema = z.object({
  niche: z.string().min(2, 'Niche must be at least 2 characters'),
  location: z.string().min(2, 'Location must be at least 2 characters'),
});

const linkedinSchema = z.object({
  niche: z.string().min(2, 'Enter what people are asking for, e.g. I need SEO'),
  location: z.string().optional(),
});

function SourceBadge({ source }: { source?: string }) {
  const isLinkedIn = source === 'linkedin';
  return (
    <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold flex items-center gap-0.5 border ${
      isLinkedIn
        ? 'bg-sky-500/10 text-sky-400 border-sky-500/20'
        : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
    }`}>
      {isLinkedIn ? <Linkedin className="w-2.5 h-2.5" /> : <MapPin className="w-2.5 h-2.5" />}
      {isLinkedIn ? 'LinkedIn' : 'Maps'}
    </span>
  );
}

function LiveResultCard({ lead, index }: { lead: any; index: number }) {
  const catKey = lead.lead_category || 'warm';
  const catCfg = LEAD_CATEGORIES[catKey as keyof typeof LEAD_CATEGORIES] || { label: catKey, color: '#94a3b8', bg: '#f1f5f9' };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.4, delay: index * 0.08, ease: 'easeOut' }}
    >
      <Link href={`/dashboard/leads/${lead.id}`} className="block group">
        <div className="glass-card-premium rounded-xl hover:border-steel/30 transition-colors duration-300">
          <div className="p-4">
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Badge
                    style={{ backgroundColor: (catCfg as any).bg, color: catCfg.color }}
                    className="font-bold border-0 text-[10px] px-2 py-0.5"
                  >
                    {catCfg.label}
                  </Badge>
                  <SourceBadge source={lead.source} />
                  {lead.source === 'linkedin' && (
                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold border ${
                      lead.post_type === 'buyer' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                      : lead.post_type === 'hiring' ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                      : lead.post_type === 'agency_wanted' ? 'bg-violet-500/10 text-violet-400 border-violet-500/20'
                      : 'bg-white/5 text-ice/50 border-white/10'
                    }`}>
                      {lead.post_type === 'buyer' ? 'Freelancer Needed'
                        : lead.post_type === 'hiring' ? 'Hiring'
                        : lead.post_type === 'agency_wanted' ? 'Agency Wanted' : 'Post'}
                    </span>
                  )}
                  {lead.headline && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/5 text-ice/50 font-medium border border-white/10 max-w-[140px] truncate">
                      {lead.headline}
                    </span>
                  )}
                {lead.website_health_score != null && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                    lead.website_health_score >= 70 ? 'text-emerald-400 bg-emerald-500/10' :
                    lead.website_health_score >= 40 ? 'text-amber-400 bg-amber-500/10' :
                    'text-rose-400 bg-rose-500/10'
                  }`}>
                    {lead.website_health_score}
                  </span>
                )}
              </div>
              <span className="text-[10px] text-ice/30 font-mono">#{index + 1}</span>
            </div>
            <h4 className="text-sm font-bold text-offwhite mb-1.5 truncate group-hover:text-steel transition-colors">
              {lead.business_name || 'Unknown Business'}
            </h4>
            <div className="flex items-center gap-2 text-[11px] text-ice/50 mb-1">
              {lead.rating != null && (
                <span className="flex items-center gap-0.5">
                  <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
                  {lead.rating}
                  {lead.total_reviews > 0 && (
                    <span className="text-[10px] text-ice/50">({lead.total_reviews})</span>
                  )}
                </span>
              )}
              {lead.category && <span className="text-ice/40">{lead.category}</span>}
            </div>
            <div className="space-y-1 text-[11px] text-ice/60">
              {lead.source === 'linkedin' ? (
                <>
                  {lead.email_found && (
                    <div className="flex items-center gap-1.5">
                      <Mail className="w-3 h-3 text-steel/60" />
                      <span className="truncate text-emerald-400">{lead.email_found}</span>
                    </div>
                  )}
                  {lead.full_address && (
                    <div className="flex items-center gap-1.5 text-ice/50">
                      <MapPin className="w-3 h-3 text-steel/60 shrink-0" />
                      <span className="truncate">{lead.full_address}</span>
                    </div>
                  )}
                  {lead.post_text && (
                    <p className="line-clamp-2 italic text-ice/50 border-l-2 border-steel/30 pl-2">
                      {lead.post_text}
                    </p>
                  )}
                  {lead.posted_at && (
                    <div className="flex items-center gap-1.5 text-ice/40">
                      <Clock className="w-3 h-3" />
                      <span>posted {new Date(lead.posted_at).toLocaleDateString()}</span>
                    </div>
                  )}
                  {lead.post_url && (
                    <div className="flex items-center gap-1.5 text-sky-400">
                      <ExternalLink className="w-3 h-3" />
                      <a href={lead.post_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="truncate hover:underline">
                        View post on LinkedIn
                      </a>
                    </div>
                  )}
                </>
              ) : (
                <>
              {lead.phone && (
                <div className="flex items-center gap-1.5">
                  <Phone className="w-3 h-3 text-steel/60" />
                  <span>{lead.phone}</span>
                </div>
              )}
              <div className="flex items-center gap-1.5">
                <Globe className="w-3 h-3 text-steel/60 shrink-0" />
                {lead.website_url ? (
                  <span className="truncate">{lead.website_url.replace(/^https?:\/\/(www\.)?/, '')}</span>
                ) : (
                  <span className="text-ice/30 italic">No website</span>
                )}
              </div>
                </>
              )}
            </div>
          </div>
          <div className="px-4 py-2 border-t border-white/5 flex items-center justify-between text-[10px] font-semibold text-steel/60 group-hover:text-steel transition-colors">
            <span>View Profile</span>
            <ChevronRight className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
          </div>
        </div>
      </Link>
    </motion.div>
  );
}

export default function SearchPage() {
  const {
    activeSearchId,
    progress,
    results,
    resultsTotal,
    isStarting,
    isCancelling,
    startSearch,
    cancelSearch,
    resumePollingIfActive,
    clearActiveSearch,
  } = useSearch();

  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [reviewFilter, setReviewFilter] = useState<'all' | { min: number; max: number | null }>('all');
  const [source, setSource] = useState<'google_maps' | 'linkedin'>('google_maps');
  const sourceRef = useRef<'google_maps' | 'linkedin'>('google_maps');
  const [maxResults, setMaxResults] = useState(10);
  const [leadTypes, setLeadTypes] = useState<('buyer' | 'hiring' | 'agency_wanted')[]>(['buyer']);
  const requestedCount = useSearchStore((s) => s.requestedCount);
  const isUnlocked = useSearchStore((s) => s.unlocked);
  const unlockResults = useSearchStore((s) => s.unlockResults);
  const limitHit = useSearchStore((s) => s.limitHit);
  const setLimitHit = useSearchStore((s) => s.setLimitHit);

  const REVIEW_RANGES = [
    { key: 'all', label: 'All' },
    { key: '0-5', label: '0–5 Reviews', min: 0, max: 5 },
    { key: '5-30', label: '5–30 Reviews', min: 5, max: 30 },
    { key: '30+', label: '30+ Reviews', min: 30, max: null },
  ] as const;

  const filteredResults = useMemo(() => {
    if (reviewFilter === 'all') return results;
    return results.filter(l =>
      l.total_reviews >= reviewFilter.min &&
      (reviewFilter.max === null || l.total_reviews <= reviewFilter.max)
    );
  }, [results, reviewFilter]);

  // LinkedIn: show only the requested count until the user clicks
  // "Get More" — over-delivered extras stay hidden behind the button.
  const isLocked = requestedCount !== null && !isUnlocked;
  const visibleLeads = isLocked ? filteredResults.slice(0, requestedCount) : filteredResults;
  const hiddenCount = Math.max(0, filteredResults.length - (requestedCount ?? 0));

  const mapsForm = useForm<{ niche: string; location?: string }>({
    resolver: ((values: { niche: string; location?: string }) => {
      const schema = sourceRef.current === 'linkedin' ? linkedinSchema : mapsSchema;
      const parsed = schema.safeParse(values);
      if (parsed.success) {
        return { values: parsed.data as { niche: string; location?: string }, errors: {} };
      }
      const errors: Record<string, { type: string; message: string }> = {};
      for (const issue of parsed.error.issues) {
        const field = String(issue.path[0] ?? '');
        errors[field] = { type: issue.code, message: issue.message };
      }
      return { values: {} as { niche: string; location?: string }, errors };
    }) as any,
  });

  const changeSource = (next: 'google_maps' | 'linkedin') => {
    sourceRef.current = next;
    setSource(next);
    mapsForm.clearErrors();
  };

  useEffect(() => {
    resumePollingIfActive();
    api.get('/api/auth/me').then(r => setSubscription(r.data?.subscription)).catch(() => {});
  }, [resumePollingIfActive]);

  useEffect(() => {
    if (typeof window !== 'undefined' && window.location.search.includes('source=linkedin')) {
      sourceRef.current = 'linkedin';
      setSource('linkedin');
    }
  }, []);

  const remaining = subscription?.remaining_searches ?? 1;
  const searchesPerDay = subscription?.searches_per_day ?? 1;
  const isAtLimit = remaining <= 0;

  const onSubmitMaps = async (data: { niche: string; location?: string }) => {
    if (isAtLimit) { setShowUpgradeModal(true); return; }
    try {
      if (source === 'linkedin') {
        await startSearch(data.niche, data.location ?? '', { source: 'linkedin', enrichEmails: false, maxResults, leadTypes });
      } else {
        await startSearch(data.niche, data.location ?? '');
      }
    } catch (e: any) {
      if (e.response?.status === 429) setShowUpgradeModal(true);
    }
  };

  const handleLoadMore = async () => {
    if (!activeSearchId || isLoadingMore) return;
    setIsLoadingMore(true);
    try {
      const { data } = await api.post(API_ROUTES.searches.loadMore(activeSearchId), {});
      if (data.new_leads > 0) {
        const { data: newResults } = await api.get(`${API_ROUTES.searches.detail(activeSearchId)}/results?page=1&per_page=50`);
        if (newResults.items) {
          useSearchStore.getState().appendResults(newResults.items);
        }
      }
    } catch (e: any) {
      console.error('Load more failed:', e);
    } finally {
      setIsLoadingMore(false);
    }
  };

  const isSearchActive = activeSearchId && progress && !['completed', 'failed', 'cancelled'].includes(progress.status ?? '');

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-offwhite tracking-tight">
            <span className="gradient-text">Finding hot leads</span>
          </h1>
          <p className="text-ice/50 mt-2 text-sm">
            {source === 'linkedin'
              ? 'Find people on LinkedIn who are asking for your service.'
              : 'Find and qualify leads from Google Maps in seconds.'}
          </p>
        </div>
      </div>

      <AnimatePresence mode="wait">
        {!isSearchActive && !progress ? (
          <motion.div
            key="maps"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.3 }}
          >
            <div className="glass-card-premium rounded-2xl p-8 max-w-3xl mx-auto border-ocean/20">
              <div className="grid grid-cols-2 gap-3 mb-6">
                <button
                  type="button"
                  onClick={() => changeSource('google_maps')}
                  className={`flex items-center justify-center gap-2 px-4 py-3 rounded-xl border transition-all ${
                    source === 'google_maps'
                      ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-400'
                      : 'bg-navy/40 border-ocean/20 text-ice/50 hover:border-ocean/40'
                  }`}
                >
                  <MapPin className="w-4 h-4" />
                  <span className="font-semibold">Google Maps</span>
                </button>
                <button
                  type="button"
                  onClick={() => changeSource('linkedin')}
                  className={`flex items-center justify-center gap-2 px-4 py-3 rounded-xl border transition-all ${
                    source === 'linkedin'
                      ? 'bg-sky-500/10 border-sky-500/40 text-sky-400'
                      : 'bg-navy/40 border-ocean/20 text-ice/50 hover:border-ocean/40'
                  }`}
                >
                  <Linkedin className="w-4 h-4" />
                  <span className="font-semibold">LinkedIn Posts</span>
                </button>
              </div>
              <form onSubmit={mapsForm.handleSubmit(onSubmitMaps)} className="space-y-6">
                <div className={source === 'linkedin' ? '' : 'grid grid-cols-1 md:grid-cols-2 gap-6'}>
                  <div>
                    <label className="block text-sm font-medium text-ice/70 mb-2 flex items-center gap-2">
                      <TargetIcon className="w-4 h-4 text-steel" />
                      {source === 'linkedin' ? 'What are people asking for?' : 'Target Niche'}
                    </label>
                    <div className="relative group">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Briefcase className="h-5 w-5 text-steel/60 group-focus-within:text-steel transition-colors" />
                      </div>
                      <input
                        {...mapsForm.register('niche')}
                        type="text"
                        placeholder={source === 'linkedin' ? 'e.g. I need website help' : 'e.g. Plumbers, Dentists'}
                        className="w-full pl-10 pr-4 py-3 rounded-xl border border-ocean/30 bg-navy/60 focus:bg-navy/80 focus:ring-2 focus:ring-steel/40 focus:border-steel/50 transition-all text-offwhite text-lg placeholder-ice/30 outline-none"
                      />
                    </div>
                    {mapsForm.formState.errors.niche && (
                      <p className="text-red-400 text-sm mt-1.5">{mapsForm.formState.errors.niche.message}</p>
                    )}
                  </div>
                  {source === 'google_maps' && (
                  <div>
                    <label className="block text-sm font-medium text-ice/70 mb-2 flex items-center gap-2">
                      <MapPin className="w-4 h-4 text-steel" />
                      Location
                    </label>
                    <div className="relative group">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Globe className="h-5 w-5 text-steel/60 group-focus-within:text-steel transition-colors" />
                      </div>
                      <input
                        {...mapsForm.register('location')}
                        type="text"
                        placeholder="e.g. Dallas TX, London UK"
                        className="w-full pl-10 pr-4 py-3 rounded-xl border border-ocean/30 bg-navy/60 focus:bg-navy/80 focus:ring-2 focus:ring-steel/40 focus:border-steel/50 transition-all text-offwhite text-lg placeholder-ice/30 outline-none"
                      />
                    </div>
                    {mapsForm.formState.errors.location && (
                      <p className="text-red-400 text-sm mt-1.5">{mapsForm.formState.errors.location.message}</p>
                    )}
                  </div>
                  )}
                  {source === 'linkedin' && (
                  <>
                  <div>
                    <label className="block text-sm font-medium text-ice/70 mb-2 flex items-center gap-2">
                      <MapPin className="w-4 h-4 text-steel" />
                      Country / Location
                    </label>
                    <div className="relative group">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Globe className="h-5 w-5 text-steel/60 group-focus-within:text-steel transition-colors" />
                      </div>
                      <input
                        {...mapsForm.register('location')}
                        type="text"
                        placeholder="e.g. India, US, UK, Europe, Mumbai"
                        className="w-full pl-10 pr-4 py-3 rounded-xl border border-ocean/30 bg-navy/60 focus:bg-navy/80 focus:ring-2 focus:ring-steel/40 focus:border-steel/50 transition-all text-offwhite text-lg placeholder-ice/30 outline-none"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-ice/70 mb-2 flex items-center gap-2">
                      <Users className="w-4 h-4 text-steel" />
                      Max Leads
                    </label>
                    <select
                      value={maxResults}
                      onChange={(e) => setMaxResults(Number(e.target.value))}
                      className="w-full px-3 py-3 rounded-xl border border-ocean/30 bg-navy/60 text-offwhite outline-none focus:ring-2 focus:ring-steel/40"
                    >
                      {[3, 5, 10, 20, 50].map(n => (
                        <option key={n} value={n}>{n} leads</option>
                      ))}
                    </select>
                  </div>
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium text-ice/70 mb-2 flex items-center gap-2">
                      <Briefcase className="w-4 h-4 text-steel" />
                      Lead Type
                    </label>
                    <div className="grid grid-cols-1 gap-3">
                      {([
                        { id: 'buyer', label: 'Freelancer Needed', desc: 'People/companies looking for freelancers/contractors' },
                      ] as { id: 'buyer' | 'hiring' | 'agency_wanted'; label: string; desc: string }[]).map(opt => {
                        const checked = leadTypes.includes(opt.id);
                        return (
                          <button
                            key={opt.id}
                            type="button"
                            onClick={() => {
                              if (opt.id !== 'buyer') return; // buyers only — hiring/agency removed
                            }}
                            className={`p-3 rounded-xl border text-left transition-all ${
                              checked
                                ? 'bg-sky-500/10 border-sky-500/40'
                                : 'bg-navy/40 border-ocean/20 hover:border-ocean/40'
                            }`}
                          >
                            <div className="flex items-center gap-2">
                              <div className={`w-4 h-4 shrink-0 rounded border-2 flex items-center justify-center transition-colors ${
                                checked ? 'border-sky-400 bg-sky-400' : 'border-steel/50'
                              }`}>
                                {checked && <svg className="w-3 h-3 text-navy" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="4"><path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                              </div>
                              <span className="text-sm font-semibold text-offwhite">{opt.label}</span>
                            </div>
                            <p className="text-[10px] text-ice/50 mt-1.5">{opt.desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div className="md:col-span-2">
                    <p className="text-xs text-ice/60 leading-relaxed">
                      We search LinkedIn posts for people & companies looking for freelancers — genuine
                      buyers of your service — filtered to your country, and
                      deliver exactly the number of leads you ask for.
                    </p>
                  </div>
                  </>
                  )}
                </div>
                <SearchInfoSection isAtLimit={isAtLimit} remaining={remaining} searchesPerDay={searchesPerDay} isStarting={isStarting} />
              </form>
            </div>
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

      {(progress || results.length > 0) && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2 }}
          key="live-results"
        >
          {results.length > 0 && (
            <>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-steel/20 to-ocean/20 flex items-center justify-center">
                    <Users className="w-4 h-4 text-steel" />
                  </div>
                  <h2 className="text-lg font-bold text-offwhite tracking-tight">Live Results</h2>
                </div>
                <span className="text-sm text-ice/40 font-mono">
                  {visibleLeads.length}{resultsTotal > results.length ? ' / ' + resultsTotal : ''} found
                </span>
              </div>

              {progress?.source !== 'linkedin' && (
              <div className="flex items-center gap-2 mb-4 flex-wrap">
                {REVIEW_RANGES.map((range) => {
                  const isActive = range.key === 'all'
                    ? reviewFilter === 'all'
                    : (reviewFilter !== 'all' && reviewFilter.min === range.min && reviewFilter.max === range.max);
                  return (
                    <button
                      key={range.key}
                      onClick={() => {
                        if (range.key === 'all') setReviewFilter('all');
                        else setReviewFilter({ min: range.min!, max: range.max ?? null });
                      }}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all border ${
                        isActive
                          ? 'bg-steel/20 border-steel/50 text-offwhite'
                          : 'bg-navy/60 border-ocean/25 text-ice/60 hover:text-offwhite hover:border-steel/40'
                      }`}
                    >
                      {range.label}
                    </button>
                  );
                })}
              </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                {visibleLeads.map((lead, idx) => (
                  <LiveResultCard key={lead.id} lead={lead} index={idx} />
                ))}
              </div>
              {!isSearchActive && isLocked && hiddenCount > 0 && (
                <div className="flex justify-center mt-6">
                  <button
                    onClick={unlockResults}
                    className="btn-gradient-cyan inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm transition-opacity"
                  >
                    <Unlock className="w-4 h-4" />
                    Get More Leads (+{hiddenCount})
                  </button>
                </div>
              )}
              {!isSearchActive && resultsTotal > 0 && (
                <div className="flex justify-center mt-6 gap-4 flex-wrap">
                  <Link href="/dashboard/leads"
                    className="btn-gradient-cyan inline-flex items-center justify-center px-6 py-2.5 rounded-xl text-sm transition-opacity"
                  >
                    View All Leads in Dashboard
                  </Link>
                  {progress?.source !== 'linkedin' && results.length >= 10 && (
                    <LoadingButton
                      onClick={handleLoadMore}
                      isLoading={isLoadingMore}
                      variant="glass"
                      size="md"
                    >
                      <Search className="w-4 h-4 mr-1.5" />
                      Load 10 More
                    </LoadingButton>
                  )}
                  <LoadingButton
                    onClick={() => { clearActiveSearch(); }}
                    variant="glass"
                    size="md"
                  >
                    New Search
                  </LoadingButton>
                </div>
              )}
            </>
          )}
        </motion.div>
      )}

      {/* Failed / cancelled search → let the user start over immediately */}
      {(progress?.status === 'failed' || progress?.status === 'cancelled') && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="flex flex-col items-center gap-4 mt-8"
        >
          <p className="text-sm text-ice/50">
            {progress?.status === 'failed'
              ? 'Something went wrong with this search.'
              : 'This search was cancelled.'}
          </p>
          <LoadingButton
            onClick={() => { clearActiveSearch(); }}
            variant="gradient-cyan"
            size="md"
            className="px-6 py-3"
          >
            <Search className="w-4 h-4 mr-1.5" />
            Start New Search
          </LoadingButton>
        </motion.div>
      )}

      <UpgradeModal
        isOpen={showUpgradeModal || limitHit}
        onClose={() => { setShowUpgradeModal(false); setLimitHit(false); }}
        type="limit"
      />
    </div>
  );
}

function TargetIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <circle cx="12" cy="12" r="6" />
      <circle cx="12" cy="12" r="2" />
    </svg>
  );
}

function SearchInfoSection({ isAtLimit, remaining, searchesPerDay, isStarting }: { isAtLimit: boolean; remaining: number; searchesPerDay: number; isStarting: boolean }) {
  return (
    <>
      {isAtLimit ? (
        <div className="bg-rose-500/10 p-4 rounded-xl border border-rose-500/30 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-rose-300 font-semibold">Search limit reached</p>
            <p className="text-xs text-rose-400/80 mt-1">You&apos;ve used all {searchesPerDay} searches. Upgrade your plan for more.</p>
            <Link href="/dashboard/billing" className="text-xs text-steel hover:underline mt-2 inline-block">Upgrade Plan &rarr;</Link>
          </div>
        </div>
      ) : (
        <div className="bg-steel/10 p-4 rounded-xl border border-steel/20 flex items-start gap-3">
          <Sparkles className="w-5 h-5 text-steel shrink-0 mt-0.5" />
          <p className="text-sm text-ice/70 leading-relaxed">
            Hyperclients will search for targeted results, extract data, and run AI analysis. The process usually takes 2-10 minutes.
          </p>
        </div>
      )}

      <div className="flex items-center justify-between">
        <span className="text-xs text-ice/40">
          {remaining}/{searchesPerDay} searches remaining
        </span>
        <LoadingButton
          type="submit"
          isLoading={isStarting}
          size="lg"
          fullWidth={false}
          variant={isAtLimit ? 'outline' : 'gradient-cyan'}
          className="text-lg py-4 px-8"
          disabled={isAtLimit}
        >
          <SearchIcon className="w-5 h-5" />
          Start Search
        </LoadingButton>
      </div>
    </>
  );
}
