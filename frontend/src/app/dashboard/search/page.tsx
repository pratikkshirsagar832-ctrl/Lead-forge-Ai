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
import { PostTypeBadge } from '@/components/dashboard/PostTypeBadge';
import { FreshnessChip, UrgencyChip } from '@/components/dashboard/LeadChips';
import { GlassCard } from '@/components/shared/GlassCard';
import { API_ROUTES } from '@/lib/constants';
import { useSearchStore } from '@/stores/searchStore';
import { MapPin, Briefcase, SearchIcon, Sparkles, Globe, Star, Phone, ChevronRight, Users, AlertCircle, Search, Linkedin, Mail, Clock, ExternalLink, Unlock, Check, BadgeCheck, Lock } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';
import { LEAD_CATEGORIES } from '@/lib/constants';
import { formatPostedAgo, serviceLabel } from '@/lib/utils';

const mapsSchema = z.object({
  niche: z.string().min(2, 'Niche must be at least 2 characters'),
  location: z.string().min(2, 'Location must be at least 2 characters'),
});

const linkedinSchema = z.object({
  niche: z.string().trim().min(2, 'Tell us the service you offer, e.g. video editing or interior design').max(200, 'Keep it under 200 characters'),
  location: z.string().optional(),
});

function SourceBadge({ source }: { source?: string }) {
  const isLinkedIn = source === 'linkedin';
  return (
    <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold flex items-center gap-0.5 border ${
      isLinkedIn
        ? 'bg-steel/10 text-steel border-steel/25'
        : 'bg-brand-accent/10 text-brand-accent border-brand-accent/25'
    }`}>
      {isLinkedIn ? <Linkedin className="w-2.5 h-2.5" /> : <MapPin className="w-2.5 h-2.5" />}
      {isLinkedIn ? 'LinkedIn' : 'Maps'}
    </span>
  );
}

function LiveResultCard({ lead, index }: { lead: any; index: number }) {
  const catKey = lead.lead_category || 'warm';
  const catCfg = LEAD_CATEGORIES[catKey as keyof typeof LEAD_CATEGORIES] || { label: catKey, color: '#94a3b8', bg: '#f1f5f9' };

  // LinkedIn cards open the live post directly from the search results (the
  // internal detail page also supports LinkedIn leads for pipeline management).
  const isLinkedIn = lead.source === 'linkedin';
  const cardHref = isLinkedIn ? (lead.post_url || '#') : `/dashboard/leads/${lead.id}`;
  const cardTarget = isLinkedIn ? '_blank' : undefined;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 24, rotateX: -12 }}
      animate={{ opacity: 1, y: 0, rotateX: 0 }}
      transition={{ type: 'spring', stiffness: 260, damping: 24, delay: Math.min(index, 8) * 0.06 }}
      style={{ transformPerspective: 900 }}
    >
      <Link href={cardHref} target={cardTarget} rel={isLinkedIn ? 'noopener noreferrer' : undefined} className="block group h-full rounded-2xl focus-visible:outline-2 focus-visible:outline-steel">
        <GlassCard tilt={5} hoverEffect className="rounded-2xl h-full">
          <div className="p-4">
              <div className="flex items-start justify-between mb-2">
                <div className="flex items-center gap-2">
                  {lead.source !== 'linkedin' && (
                    <Badge
                      style={{ backgroundColor: (catCfg as any).bg, color: catCfg.color }}
                      className="font-bold border-0 text-[10px] px-2 py-0.5"
                    >
                      {catCfg.label}
                    </Badge>
                  )}
                  <SourceBadge source={lead.source} />
                  {lead.source === 'linkedin' && <PostTypeBadge postType={lead.post_type} />}
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
                  {(lead.posted_at || lead.urgency != null) && (
                    <div className="flex items-center gap-1.5 pt-1">
                      <FreshnessChip postedAt={lead.posted_at} />
                      <UrgencyChip urgency={lead.urgency} />
                    </div>
                  )}
                  {lead.post_url && (
                    <div className="flex items-center gap-1.5 text-steel">
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
            <span>{isLinkedIn ? 'Open LinkedIn Post' : 'View Profile'}</span>
            <ChevronRight className="w-3 h-3 transition-transform group-hover:translate-x-0.5" />
          </div>
        </GlassCard>
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
    fetchAllResults,
  } = useSearch();

  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [reviewFilter, setReviewFilter] = useState<'all' | { min: number; max: number | null }>('all');
  const [source, setSource] = useState<'google_maps' | 'linkedin'>('google_maps');
  const sourceRef = useRef<'google_maps' | 'linkedin'>('google_maps');
  // LinkedIn role lane: STRICT single-type — freelancer XOR agency, never mixed.
  const [linkedinRole, setLinkedinRole] = useState<'freelancer' | 'agency'>(() => {
    try {
      const saved = typeof window !== 'undefined' ? window.localStorage.getItem('hyperclients_linkedin_role') : null;
      return saved === 'agency' ? 'agency' : 'freelancer';
    } catch { return 'freelancer'; }
  });
  const setRole = (r: 'freelancer' | 'agency') => {
    setLinkedinRole(r);
    try { window.localStorage.setItem('hyperclients_linkedin_role', r); } catch {}
  };
  const [maxResults, setMaxResults] = useState<number>(() => {
    try {
      const saved = typeof window !== 'undefined' ? window.localStorage.getItem('hyperclients_maps_count') : null;
      const n = saved ? parseInt(saved, 10) : 20;
      return [20, 50, 80, 100].includes(n) ? n : 20;
    } catch { return 20; }
  });
  const MAPS_ETA: Record<number, string> = { 20: '~25s', 50: '~50s', 80: '~75s', 100: '~90s' };
  const setMapsCount = (n: number) => {
    setMaxResults(n);
    try { window.localStorage.setItem('hyperclients_maps_count', String(n)); } catch {}
  };
  // LinkedIn has its own count (3/5/10): sharing the Maps value sent 20 on a
  // LinkedIn search while the dropdown showed "3 leads".
  const LINKEDIN_COUNTS = [3, 5, 10];
  const MAPS_COUNTS = [20, 50, 80, 100];
  const [linkedinCount, setLinkedinCountState] = useState<number>(() => {
    try {
      const saved = typeof window !== 'undefined' ? window.localStorage.getItem('hyperclients_linkedin_count') : null;
      const n = saved ? parseInt(saved, 10) : 3;
      return [3, 5, 10].includes(n) ? n : 3;
    } catch { return 3; }
  });
  const setLinkedinCount = (n: number) => {
    setLinkedinCountState(n);
    try { window.localStorage.setItem('hyperclients_linkedin_count', String(n)); } catch {}
  };
  const [upgradeReason, setUpgradeReason] = useState<{ title: string; description: string } | null>(null);
  // LinkedIn discovery targets genuine service buyers — freelancer-needed
  // (buyer). Hiring/job-ads are excluded.
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
    // LinkedIn leads stream in as they are found: always show the NEWEST first.
    if (progress?.source === 'linkedin') {
      const ts = (l: (typeof results)[number]) => Date.parse(l.posted_at || '') || 0;
      return [...results].sort((a, b) => ts(b) - ts(a));
    }
    if (reviewFilter === 'all') return results;
    return results.filter(l =>
      l.total_reviews >= reviewFilter.min &&
      (reviewFilter.max === null || l.total_reviews <= reviewFilter.max)
    );
  }, [results, reviewFilter, progress?.source]);

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
    // Each source has its own count picker — reset so a Maps value never
    // leaks into the LinkedIn run (and vice versa).
    if (next === 'linkedin') setMaxResults(10);
    else setMapsCount(20);
    mapsForm.clearErrors();
  };

  useEffect(() => {
    resumePollingIfActive();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Refresh quota/subscription once when this page mounts (moved out of the
  // resume effect so status ticks never re-fetch it).
  useEffect(() => {
    api.get('/api/auth/me').then(r => setSubscription(r.data?.subscription)).catch(() => {});
  }, []);

  useEffect(() => {
    if (typeof window !== 'undefined' && window.location.search.includes('source=linkedin')) {
      sourceRef.current = 'linkedin';
      setSource('linkedin');
    }
  }, []);

  // Header reflects the service + the exact lead count the user selected
  // (from the active search when one is running, else the live form value).
  const selectedService = progress?.service || mapsForm.watch('niche') || '';
  const selectedCount = progress?.requested_count || (source === 'linkedin' ? linkedinCount : maxResults);
  // Any input ("I'm a freelance video editor for YouTubers", a long pitch,
  // Hinglish...) is reduced to a short display name; long descriptions fall
  // back to a generic header instead of echoing the whole sentence.
  const serviceCap = serviceLabel(selectedService);
  const leadsWord = `${selectedCount} High-quality ${selectedCount === 1 ? 'Lead' : 'Leads'}`;
  const headerLabel = serviceCap
    ? `Finding ${leadsWord} for your ${serviceCap} Service`
    : selectedService.trim()
      ? `Finding ${leadsWord} for your Service`
      : 'Finding hot leads';

  const remaining = subscription?.remaining_searches ?? 1;
  const searchesPerDay = subscription?.searches_per_day ?? 1;
  const isAtLimit = remaining <= 0;

  // Plan cap per option: an option above what the plan has left this month
  // is LOCKED (lock icon + upgrade popup) instead of silently running a
  // smaller search. The smallest option always stays usable - it delivers
  // whatever is left.
  const isTrial = subscription?.status === 'trial';
  const leadsLeft = (src: 'google_maps' | 'linkedin') => {
    const v = src === 'linkedin' ? subscription?.linkedin_hq_leads_remaining : subscription?.gmb_leads_remaining;
    return typeof v === 'number' ? Math.max(0, v) : null;
  };
  const isCountLocked = (src: 'google_maps' | 'linkedin', n: number) => {
    const left = leadsLeft(src);
    const options = src === 'linkedin' ? LINKEDIN_COUNTS : MAPS_COUNTS;
    return left !== null && n > left && n !== options[0];
  };
  const showCountLocked = (src: 'google_maps' | 'linkedin', n: number) => {
    const left = leadsLeft(src) ?? 0;
    const kind = src === 'linkedin' ? 'LinkedIn' : 'Google Maps';
    const monthly = src === 'linkedin' ? subscription?.linkedin_hq_leads_monthly : subscription?.gmb_leads_monthly;
    setUpgradeReason(isTrial
      ? {
          title: "You're on the free trial",
          description: `Your free trial includes ${monthly ?? left} ${kind} leads, so you can't get ${n} leads in one search`
            + (left > 0 ? ` (you have ${left} left).` : '.') + ` Upgrade your plan to unlock ${n}-lead searches.`,
        }
      : {
          title: `Only ${left} ${kind} leads left`,
          description: `You have ${left} ${kind} leads left this month, so a ${n}-lead search isn't available. `
            + 'Your quota resets on the 1st - or upgrade your plan for more leads.',
        });
  };

  const onSubmitMaps = async (data: { niche: string; location?: string }) => {
    if (isAtLimit) { setShowUpgradeModal(true); return; }
    const count = source === 'linkedin' ? linkedinCount : maxResults;
    if (isCountLocked(source, count)) { showCountLocked(source, count); return; }
    try {
      if (source === 'linkedin') {
        await startSearch(data.niche, data.location ?? '', {
          source: 'linkedin', enrichEmails: false, maxResults: linkedinCount,
          leadTypes: [linkedinRole],
        });
      } else {
        await startSearch(data.niche, data.location ?? '', { source: 'google_maps', enrichEmails: false, maxResults });
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
        // Reload the full (paginated) result set so leads beyond the first 50
        // remain visible after a load-more.
        await fetchAllResults(activeSearchId);
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
          <p className="text-xs font-semibold text-steel/80 mb-2">{source === 'linkedin' ? 'LinkedIn buyers' : 'Google Maps'}</p>
          <h1 className="text-3xl md:text-[2.5rem] font-bold text-offwhite tracking-[-0.02em] leading-[1.08] [text-wrap:balance]" style={{ fontFamily: 'var(--font-heading)' }}>
            {headerLabel}
          </h1>
          <p className="text-ice/55 mt-2 text-sm max-w-2xl">
            {source === 'linkedin'
              ? (linkedinRole === 'agency'
                ? 'Clients on LinkedIn actively seeking an agency — exact count, newest first.'
                : 'Genuine buyers of your service on LinkedIn — exact count, newest first.')
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
            <GlassCard className="rounded-3xl p-6 md:p-9 max-w-3xl mx-auto">
              <div className="well-3d grid grid-cols-2 gap-1.5 mb-7 p-1.5 rounded-2xl">
                <button
                  type="button"
                  onClick={() => changeSource('google_maps')}
                  aria-pressed={source === 'google_maps'}
                  className={`flex items-center justify-center gap-2 px-4 py-3 rounded-xl transition-all ${
                    source === 'google_maps'
                      ? 'key-3d is-active text-steel'
                      : 'text-ice/55 hover:text-offwhite hover:bg-white/[0.03]'
                  }`}
                >
                  <MapPin className="w-4 h-4" />
                  <span className="font-semibold">Google Maps</span>
                </button>
                <button
                  type="button"
                  onClick={() => changeSource('linkedin')}
                  aria-pressed={source === 'linkedin'}
                  className={`flex items-center justify-center gap-2 px-4 py-3 rounded-xl transition-all ${
                    source === 'linkedin'
                      ? 'key-3d is-active text-steel'
                      : 'text-ice/55 hover:text-offwhite hover:bg-white/[0.03]'
                  }`}
                >
                  <Linkedin className="w-4 h-4" />
                  <span className="font-semibold">LinkedIn Posts</span>
                </button>
              </div>
              <form onSubmit={mapsForm.handleSubmit(onSubmitMaps)} className="space-y-6">
                <div className={source === 'linkedin' ? 'grid grid-cols-1 sm:grid-cols-2 gap-6' : 'grid grid-cols-1 md:grid-cols-2 gap-6'}>
                  <div className={source === 'linkedin' ? 'sm:col-span-2' : ''}>
                    <label className="block text-sm font-medium text-ice/70 mb-2 flex items-center gap-2">
                      <TargetIcon className="w-4 h-4 text-steel" />
                      {source === 'linkedin' ? 'What service do you offer?' : 'Target Niche'}
                    </label>
                    <div className="relative group">
                      <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                        <Briefcase className="h-5 w-5 text-steel/60 group-focus-within:text-steel transition-colors" />
                      </div>
                      <input
                        {...mapsForm.register('niche')}
                        type="text"
                        placeholder={source === 'linkedin' ? 'Any service, any industry — e.g. video editing, interior design, bookkeeping' : 'e.g. Plumbers, Dentists'}
                        className="w-full pl-10 pr-4 py-3 rounded-xl well-3d border border-transparent focus:border-steel/50 focus:ring-2 focus:ring-steel/25 transition-all text-offwhite text-lg placeholder-ice/30 outline-none"
                      />
                    </div>
                    {mapsForm.formState.errors.niche && (
                      <p className="text-red-400 text-sm mt-1.5">{mapsForm.formState.errors.niche.message}</p>
                    )}
                    {source === 'linkedin' && (
                      <div className="mt-2 space-y-1.5">
                        <p className="text-[11px] text-ice/40">
                          Type it any way you like — &ldquo;I&apos;m a wedding photographer&rdquo;, &ldquo;SEO + web design&rdquo;, even Hinglish. We work out how buyers ask for it.
                        </p>
                        <div className="flex items-center gap-1.5 flex-wrap">
                          {['Video editing', 'Interior design', 'Bookkeeping', 'Wedding photography', 'Web development', 'Plumbing'].map((ex) => (
                            <button
                              key={ex}
                              type="button"
                              onClick={() => mapsForm.setValue('niche', ex, { shouldValidate: true })}
                              className="text-[10px] font-medium px-2 py-1 rounded-full bg-navy/60 text-ice/60 border border-ocean/25 hover:text-offwhite hover:border-steel/40 transition-colors"
                            >
                              {ex}
                            </button>
                          ))}
                        </div>
                      </div>
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
                        placeholder="e.g. Dallas TX, London UK, Mumbai"
                        className="w-full pl-10 pr-4 py-3 rounded-xl well-3d border border-transparent focus:border-steel/50 focus:ring-2 focus:ring-steel/25 transition-all text-offwhite text-lg placeholder-ice/30 outline-none"
                      />
                    </div>
                    {mapsForm.formState.errors.location && (
                      <p className="text-red-400 text-sm mt-1.5">{mapsForm.formState.errors.location.message}</p>
                    )}
                  </div>
                  )}
                  {source === 'google_maps' && (
                  <div className="md:col-span-2">
                    <label className="block text-sm font-medium text-ice/70 mb-2 flex items-center gap-2">
                      <Users className="w-4 h-4 text-steel" />
                      Leads Needed
                      <span className="ml-auto text-[11px] font-mono text-emerald-400/80">
                        {MAPS_ETA[maxResults] ?? '~60s'} • parallel fast scrape
                      </span>
                    </label>
                    <div className="grid grid-cols-4 gap-2">
                      {MAPS_COUNTS.map(n => {
                        const disabled = isStarting || !!isSearchActive;
                        const locked = isCountLocked('google_maps', n);
                        return (
                        <button
                          key={n}
                          type="button"
                          disabled={disabled}
                          onClick={() => (locked ? showCountLocked('google_maps', n) : setMapsCount(n))}
                          title={locked ? 'Upgrade to unlock' : `${n} leads ${MAPS_ETA[n] ?? ''}`}
                          className={`px-3 py-3 rounded-xl border text-sm font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center justify-center gap-1.5 ${
                            locked
                              ? 'well-3d border-transparent text-ice/35 hover:text-brand-accent'
                              : maxResults === n
                                ? 'key-3d is-active border-transparent text-steel'
                                : 'key-3d border-transparent text-ice/65 hover:text-offwhite'
                          }`}
                        >
                          {locked && <Lock className="w-3.5 h-3.5" />}
                          {n}
                        </button>
                        );
                      })}
                    </div>
                    {(() => {
                      const gmbLeft = subscription?.gmb_leads_remaining;
                      if (typeof gmbLeft === 'number' && gmbLeft < maxResults) {
                        return (
                          <p className="text-[11px] text-amber-400/90 mt-1.5">
                            Needs {maxResults}, you have {Math.max(0, gmbLeft)} Maps leads left this month — will deliver partial. Upgrade for full {maxResults}.
                          </p>
                        );
                      }
                      return (
                        <p className="text-[11px] text-ice/40 mt-1.5">
                          Up to {maxResults} leads {MAPS_ETA[maxResults] ?? ''}. Website + email analysis on demand from the lead page (not blocking).
                        </p>
                      );
                    })()}
                  </div>
                  )}
                  {source === 'linkedin' && (
                  <>
                  <div>
                    <label className="block text-sm font-medium text-ice/70 mb-2 flex items-center gap-2">
                      <Users className="w-4 h-4 text-steel" />
                      Leads Needed
                    </label>
                    <div className="grid grid-cols-3 gap-2">
                      {LINKEDIN_COUNTS.map(n => {
                        const locked = isCountLocked('linkedin', n);
                        return (
                          <button
                            key={n}
                            type="button"
                            disabled={isStarting || !!isSearchActive}
                            onClick={() => (locked ? showCountLocked('linkedin', n) : setLinkedinCount(n))}
                            title={locked ? 'Upgrade to unlock' : `${n} leads`}
                            className={`px-3 py-3 rounded-xl border text-sm font-semibold transition-all disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center justify-center gap-1.5 ${
                              locked
                                ? 'well-3d border-transparent text-ice/35 hover:text-brand-accent'
                                : linkedinCount === n
                                  ? 'key-3d is-active border-transparent text-steel'
                                  : 'key-3d border-transparent text-ice/65 hover:text-offwhite'
                            }`}
                          >
                            {locked && <Lock className="w-3.5 h-3.5" />}
                            {n} leads
                          </button>
                        );
                      })}
                    </div>
                    {(() => {
                      // Exact count: the search delivers exactly this many - unless the
                      // monthly quota is smaller, so say that BEFORE the search runs.
                      const liLeft = leadsLeft('linkedin');
                      if (liLeft !== null && liLeft < linkedinCount) {
                        return (
                          <p className="text-[11px] text-amber-400/90 mt-1.5">
                            You have {liLeft} LinkedIn leads left this month - this search will deliver {liLeft}. Upgrade for the full {linkedinCount}.
                          </p>
                        );
                      }
                      if (isTrial && LINKEDIN_COUNTS.some(n => isCountLocked('linkedin', n))) {
                        return (
                          <p className="text-[11px] text-ice/40 mt-1.5 flex items-center gap-1">
                            <Lock className="w-3 h-3" /> Free trial: up to {liLeft} leads per search. Upgrade to unlock more.
                          </p>
                        );
                      }
                      return (
                        <p className="text-[11px] text-ice/40 mt-1.5">
                          Exactly {linkedinCount} verified leads - never more, newest first.
                        </p>
                      );
                    })()}
                  </div>
                  <div className="grid grid-cols-2 gap-2 self-end w-full">
                    {([
                      { key: 'freelancer', title: 'Freelancer', desc: 'Posts needing a freelancer', icon: Briefcase },
                      { key: 'agency', title: 'Agency', desc: 'Clients seeking an agency', icon: Users },
                    ] as const).map((r) => (
                      <button
                        key={r.key}
                        type="button"
                        onClick={() => setRole(r.key)}
                        aria-pressed={linkedinRole === r.key}
                        className={`flex items-center gap-2.5 px-3 py-2.5 rounded-xl border border-transparent text-left ${
                          linkedinRole === r.key ? 'key-3d is-active' : 'key-3d'
                        }`}
                      >
                        <div className={`p-1.5 rounded-lg shrink-0 ${linkedinRole === r.key ? 'tile-3d' : 'bg-steel/10'}`}>
                          <r.icon className="w-4 h-4 text-steel" />
                        </div>
                        <div className="min-w-0">
                          <p className={`text-xs font-bold leading-tight ${linkedinRole === r.key ? 'text-steel' : 'text-offwhite'}`}>I&apos;m {r.key === 'freelancer' ? 'a Freelancer' : 'an Agency'}</p>
                          <p className="text-[10px] text-ice/50 leading-tight mt-0.5 truncate">{r.desc}</p>
                        </div>
                        {linkedinRole === r.key && <BadgeCheck className="w-4 h-4 text-steel ml-auto shrink-0" />}
                      </button>
                    ))}
                  </div>
                  <div className="sm:col-span-2 grid grid-cols-1 sm:grid-cols-3 gap-2">
                    {[
                      { icon: Search, title: 'Scan', desc: 'Latest LinkedIn posts worldwide' },
                      { icon: Sparkles, title: 'AI verify', desc: 'Every buyer checked for real intent' },
                      { icon: Check, title: 'Deliver', desc: 'Exact lead count, newest first' },
                    ].map((s) => (
                      <div key={s.title} className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl well-3d">
                        <div className="p-1.5 rounded-lg tile-3d shrink-0">
                          <s.icon className="w-3.5 h-3.5 text-steel" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-xs font-bold text-offwhite leading-tight">{s.title}</p>
                          <p className="text-[10px] text-ice/50 leading-tight mt-0.5 truncate">{s.desc}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="sm:col-span-2 flex items-center gap-1.5 flex-wrap">
                    {['AI-verified', 'Newest first', 'Exact count', 'No sellers or job ads'].map((t) => (
                      <span key={t} className="text-[10px] font-semibold px-2 py-1 rounded-full bg-steel/10 text-steel border border-steel/25">
                        {t}
                      </span>
                    ))}
                  </div>
                  </>
                  )}
                </div>
                <SearchInfoSection isAtLimit={isAtLimit} remaining={remaining} searchesPerDay={searchesPerDay} isStarting={isStarting} source={source} />
              </form>
            </GlassCard>
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
                  <div className="w-8 h-8 rounded-lg tile-3d flex items-center justify-center">
                    <Users className="w-4 h-4 text-steel" />
                  </div>
                  <h2 className="text-lg font-bold text-offwhite tracking-tight" style={{ fontFamily: 'var(--font-heading)' }}>
                    {isSearchActive ? 'Arriving live' : 'Results'}
                  </h2>
                  {isSearchActive && (
                    <span className="relative flex h-2 w-2" aria-hidden="true">
                      <span className="absolute inline-flex h-full w-full rounded-full bg-steel opacity-70 motion-safe:animate-ping" />
                      <span className="relative inline-flex h-2 w-2 rounded-full bg-steel" />
                    </span>
                  )}
                </div>
                <span className="text-sm text-ice/45 tabular">
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
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold border border-transparent ${
                        isActive ? 'key-3d is-active text-steel' : 'key-3d text-ice/65 hover:text-offwhite'
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
                    className="btn-3d-gold inline-flex items-center gap-2 px-6 py-2.5 rounded-xl text-sm"
                  >
                    <Unlock className="w-4 h-4" />
                    Get More Leads (+{hiddenCount})
                  </button>
                </div>
              )}
            </>
          )}

          {(!isSearchActive && (
            resultsTotal > 0 || progress?.status === 'completed'
          )) && (
            <div className="flex justify-center mt-6 gap-4 flex-wrap">
              {resultsTotal > 0 && (
                <Link href="/dashboard/leads"
                  className="btn-3d-gold inline-flex items-center justify-center px-6 py-2.5 rounded-xl text-sm"
                >
                  View All Leads in Dashboard
                </Link>
              )}
              {resultsTotal > 0 && progress?.source !== 'linkedin' && results.length >= 10 && (
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
        isOpen={showUpgradeModal || limitHit || upgradeReason !== null}
        onClose={() => { setShowUpgradeModal(false); setLimitHit(false); setUpgradeReason(null); }}
        type="limit"
        title={upgradeReason?.title}
        description={upgradeReason?.description}
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

function SearchInfoSection({ isAtLimit, remaining, searchesPerDay, isStarting, source }: { isAtLimit: boolean; remaining: number; searchesPerDay: number; isStarting: boolean; source: 'google_maps' | 'linkedin' }) {
  const isLinkedIn = source === 'linkedin';
  return (
    <>
      {isAtLimit ? (
        <div className="bg-rose-500/10 p-4 rounded-xl border border-rose-500/30 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-rose-300 font-semibold">Search limit reached</p>
            <p className="text-xs text-rose-400/80 mt-1">You&apos;ve used all {searchesPerDay} searches this month. Resets on the 1st. Upgrade your plan for more.</p>
            <Link href="/dashboard/billing" className="text-xs text-steel hover:underline mt-2 inline-block">Upgrade Plan &rarr;</Link>
          </div>
        </div>
      ) : (
        <div className="well-3d p-4 rounded-xl flex items-start gap-3">
          <span className="tile-3d grid h-8 w-8 shrink-0 place-items-center rounded-lg"><Sparkles className="w-4 h-4 text-steel" /></span>
          <p className="text-sm text-ice/70 leading-relaxed">
            {isLinkedIn
              ? 'Hyperclients will scan the latest LinkedIn posts, verify every buyer with AI, and deliver your exact lead count. Usually takes 1-5 minutes.'
              : 'Fast scrape streams leads live — first results in ~20s, up to 100 in ~90s. Website + email analysis runs on demand from the lead page.'}
          </p>
        </div>
      )}

      <div className="flex items-center justify-between">
        <span className="text-xs text-ice/45 tabular">
          {remaining}/{searchesPerDay} searches remaining this month
        </span>
        <LoadingButton
          type="submit"
          isLoading={isStarting}
          size="lg"
          fullWidth={false}
          variant={isAtLimit ? 'outline' : 'gold'}
          className="text-lg h-14 px-8"
          disabled={isAtLimit}
        >
          <SearchIcon className="w-5 h-5" />
          Start Search
        </LoadingButton>
      </div>
    </>
  );
}
