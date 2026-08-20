'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useLeads } from '@/hooks/useLeads';
import { useToast } from '@/hooks/useToast';
import api from '@/lib/api';
import { API_ROUTES, USER_STATUSES, LEAD_CATEGORIES } from '@/lib/constants';
import { GlassCard } from '@/components/shared/GlassCard';
import { Badge } from '@/components/shared/Badge';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { Skeleton } from '@/components/shared/Skeleton';
import { ScoreBreakdown } from '@/components/dashboard/ScoreBreakdown';
import { DeepAnalysisReport } from '@/components/dashboard/DeepAnalysisReport';
import {
  ArrowLeft, MapPin, Phone, Globe, Star,
  MessageSquare, FileText, ExternalLink,
  Loader2, CheckCircle2, Target, Send,
  Linkedin, Mail, Users,
} from 'lucide-react';
import { formatNumber } from '@/lib/utils';
import ReactMarkdown from 'react-markdown';

export default function LeadDetailPage() {
  const { id } = useParams();
  const router = useRouter();
  const { showToast } = useToast();
  const { updateLeadStatus, updateLeadNotes, isUpdating } = useLeads();

  const [lead, setLead] = useState<any>(null);
  const [notes, setNotes] = useState('');
  const [isGeneratingPitch, setIsGeneratingPitch] = useState(false);
  const [isPageLoading, setIsPageLoading] = useState(true);
  const [isAnalyzingWebsite, setIsAnalyzingWebsite] = useState(false);
  const [websiteMessage, setWebsiteMessage] = useState<string | null>(null);
  const [isGeneratingMessage, setIsGeneratingMessage] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const fetchLeadDetail = async () => {
      try {
        const { data } = await api.get(API_ROUTES.leads.detail(id as string));
        if (cancelled) return;
        setLead(data);
        setNotes(data.user_notes || '');
      } catch (error) {
        if (cancelled) return;
        showToast('Failed to load lead details', 'error');
      } finally {
        if (!cancelled) setIsPageLoading(false);
      }
    };
    if (id) fetchLeadDetail();
    return () => { cancelled = true; };
  }, [id, router, showToast]);

  const handleStatusChange = async (newStatus: string) => {
    await updateLeadStatus(id as string, newStatus);
    if (lead) setLead({ ...lead, user_status: newStatus });
  };

  const handleSaveNotes = async () => {
    await updateLeadNotes(id as string, notes);
    if (lead) setLead({ ...lead, user_notes: notes });
  };

  const handleGeneratePitch = async () => {
    try {
      setIsGeneratingPitch(true);
      const { data } = await api.post(API_ROUTES.ai.pitch(id as string));
      setLead({ ...lead, ai_pitch: data.pitch });
      showToast('AI Pitch generated successfully!', 'success');
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      showToast(typeof detail === 'string' ? detail : detail?.message || 'Failed to generate pitch', 'error');
    } finally {
      setIsGeneratingPitch(false);
    }
  };

  const handleAnalyzeWebsite = async () => {
    try {
      setIsAnalyzingWebsite(true);
      const { data } = await api.post(API_ROUTES.leads.analyzeWebsite(id as string));
      setLead((prev: any) => ({
        ...prev,
        website_analyses: [{
          overall_score: data.data.overall_score,
          issues: data.data.issues,
          raw_analysis: data.data.raw_analysis,
        }],
        website_health_score: data.data.overall_score,
        lead_category: data.data.category,
      }));
      showToast('Website analysis complete!', 'success');
      handleGenerateWebsiteMessage();
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      showToast(typeof detail === 'string' ? detail : detail?.message || 'Failed to analyze website', 'error');
    } finally {
      setIsAnalyzingWebsite(false);
    }
  };

  const handleGenerateWebsiteMessage = async () => {
    try {
      setIsGeneratingMessage(true);
      const { data } = await api.post(API_ROUTES.ai.websiteMessage(id as string));
      setWebsiteMessage(data.message);
      showToast('Outreach message generated!', 'success');
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      showToast(typeof detail === 'string' ? detail : detail?.message || 'Failed to generate message', 'error');
    } finally {
      setIsGeneratingMessage(false);
    }
  };

  const handleWhatsAppSend = () => {
    if (!websiteMessage) return;
    const phone = lead?.phone;
    if (!phone) {
      showToast('No phone number available for this lead', 'error');
      return;
    }
    const cleanPhone = phone.replace(/[\s\-\+\(\)]/g, '');
    const url = `https://wa.me/${cleanPhone}?text=${encodeURIComponent(websiteMessage)}`;
    window.open(url, '_blank', 'noopener,noreferrer');
  };

  if (isPageLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-24 mb-4" />
        <GlassCard className="p-8">
          <Skeleton className="h-10 w-1/3 mb-4" />
          <Skeleton className="h-6 w-1/4 mb-8" />
          <div className="space-y-4">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-48 w-full" />
          </div>
        </GlassCard>
      </div>
    );
  }

  if (!lead) {
    return (
      <div className="space-y-6 animate-in fade-in duration-500 pb-12">
        <button
          onClick={() => router.push('/dashboard/leads')}
          className="flex items-center gap-2 text-sm font-medium text-ice/60 hover:text-offwhite transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> Back to Leads
        </button>
        <GlassCard className="p-8 text-center">
          <p className="text-ice/60 mb-4">Failed to load lead. It may have been removed.</p>
          <button onClick={() => window.location.reload()} className="text-steel hover:text-ice underline text-sm">Retry</button>
        </GlassCard>
      </div>
    );
  }

  const leadCatKey = lead.lead_category || 'warm';
  const categoryConfig = LEAD_CATEGORIES[leadCatKey as keyof typeof LEAD_CATEGORIES]
    || { label: leadCatKey, color: '#94a3b8', bg: '#f1f5f9' };

  return (
    <div className="space-y-6 animate-in fade-in duration-500 pb-12">
      <button
        onClick={() => router.back()}
        className="flex items-center gap-2 text-sm font-medium text-ice/60 hover:text-offwhite transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back to Leads
      </button>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 space-y-6">
          <GlassCard className="p-8">
            <div className="flex flex-col md:flex-row md:items-start justify-between gap-6 mb-8">
              <div>
                <div className="flex gap-2 items-center mb-3">
                  <Badge
                    style={{ backgroundColor: (categoryConfig as any).bg, color: categoryConfig.color }}
                    className="font-bold border-0"
                  >
                    {categoryConfig.label}
                  </Badge>
                  {lead.source && (
                    <Badge
                      variant="outline"
                      className={lead.source === 'linkedin'
                        ? 'border-sky-500/30 text-sky-400 bg-sky-500/5'
                        : 'border-emerald-500/30 text-emerald-400 bg-emerald-500/5'}
                    >
                      {lead.source === 'linkedin'
                        ? <><Linkedin className="w-3 h-3 mr-1" />LinkedIn</>
                        : <><MapPin className="w-3 h-3 mr-1" />Google Maps</>}
                    </Badge>
                  )}
                  {lead.is_favorite && (
                    <Badge variant="outline" className="border-rose-500/30 text-rose-400 bg-rose-500/10">
                      Favorited
                    </Badge>
                  )}
                </div>
                <h1 className="text-3xl font-bold text-offwhite mb-2">{lead.business_name}</h1>
                <div className="flex items-center gap-4 text-ice/70">
                  {lead.source === 'linkedin' ? (
                    <div className="flex items-center gap-1.5">
                      <Users className="w-5 h-5 text-steel" />
                      <span className="font-semibold text-offwhite">{formatNumber(lead.connections_count || 0)}</span>
                      <span className="text-sm">connections</span>
                    </div>
                  ) : (
                  <div className="flex items-center gap-1.5">
                    <Star className="w-5 h-5 fill-amber-400 text-amber-400" />
                    <span className="font-semibold text-offwhite">{lead.rating != null ? lead.rating : 'N/A'}</span>
                    <span className="text-sm">({formatNumber(lead.total_reviews || 0)} reviews)</span>
                  </div>
                  )}
                  {lead.category && (
                    <span className="text-sm px-2 py-0.5 rounded-md bg-steel/20 italic text-ice/80">
                      {lead.category}
                    </span>
                  )}
                </div>
              </div>

              <div className="shrink-0">
                <label className="block text-xs font-semibold text-ice/60 uppercase tracking-wider mb-2 md:text-right">
                  Pipeline Status
                </label>
                <div className="flex gap-2 p-1 bg-navy rounded-xl overflow-x-auto border border-ocean/30">
                  {Object.entries(USER_STATUSES).map(([key, config]) => (
                    <button
                      key={key}
                      disabled={isUpdating[lead.id]}
                      onClick={() => handleStatusChange(key)}
                      className={`px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap ${
                        lead.user_status === key
                          ? 'bg-ocean/60 shadow-sm ring-1 ring-steel/30 text-offwhite'
                          : 'text-ice/60 hover:text-offwhite'
                      }`}
                      style={lead.user_status === key ? { color: config.color } : {}}
                    >
                      {config.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 py-6 border-y border-ocean/30">
              {lead.source === 'linkedin' ? (
                <>
                  <div className="flex items-start gap-3">
                    <div className="p-2.5 rounded-lg bg-steel/20 text-steel shrink-0">
                      <Mail className="w-5 h-5" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-ice/60 mb-0.5">Email</p>
                      {lead.email_found ? (
                        <a href={`mailto:${lead.email_found}`} className="text-emerald-400 hover:text-emerald-300 hover:underline">{lead.email_found}</a>
                      ) : (
                        <p className="text-offwhite">No email found</p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="p-2.5 rounded-lg bg-steel/20 text-steel shrink-0">
                      <Linkedin className="w-5 h-5" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-ice/60 mb-0.5">Headline</p>
                      <p className="text-offwhite">{lead.headline || 'No headline'}</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="p-2.5 rounded-lg bg-steel/20 text-steel shrink-0">
                      <MapPin className="w-5 h-5" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-ice/60 mb-0.5">Location</p>
                      <p className="text-offwhite">{lead.full_address || 'No location provided'}</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="p-2.5 rounded-lg bg-steel/20 text-steel shrink-0">
                      <ExternalLink className="w-5 h-5" />
                    </div>
                    <div>
                      <p className="text-sm font-medium text-ice/60 mb-0.5">LinkedIn Post</p>
                      {lead.post_url ? (
                        <a href={lead.post_url} target="_blank" rel="noreferrer" className="text-steel hover:text-ice hover:underline">View post on LinkedIn</a>
                      ) : (
                        <p className="text-offwhite">No post available</p>
                      )}
                    </div>
                  </div>
                  {lead.post_text && (
                    <div className="sm:col-span-2 flex items-start gap-3">
                      <div className="p-2.5 rounded-lg bg-steel/20 text-steel shrink-0">
                        <FileText className="w-5 h-5" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-ice/60 mb-0.5">Post Content</p>
                        <p className="text-offwhite text-sm leading-relaxed italic">{lead.post_text}</p>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <>
              <div className="flex items-start gap-3">
                <div className="p-2.5 rounded-lg bg-steel/20 text-steel shrink-0">
                  <MapPin className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-medium text-ice/60 mb-0.5">Address</p>
                  <p className="text-offwhite">{lead.full_address || 'No address provided'}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="p-2.5 rounded-lg bg-steel/20 text-steel shrink-0">
                  <Phone className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-medium text-ice/60 mb-0.5">Phone</p>
                  <p className="text-offwhite">{lead.phone || 'No phone provided'}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="p-2.5 rounded-lg bg-steel/20 text-steel shrink-0">
                  <Globe className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-medium text-ice/60 mb-0.5">Website</p>
                  {lead.website_url ? (
                    <a href={lead.website_url} target="_blank" rel="noreferrer" className="text-steel hover:text-ice hover:underline flex items-center gap-1 group">
                      {lead.website_url.replace(/^https?:\/\/(www\.)?/, '')}
                      <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </a>
                  ) : (
                    <p className="text-offwhite">No website provided</p>
                  )}
                </div>
              </div>
                </>
              )}
            </div>

            <div className="mt-8">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-bold text-offwhite flex items-center gap-2">
                  <MessageSquare className="w-5 h-5 text-steel" />
                  AI Outreach Pitch
                </h3>
                {!lead.ai_pitch && (
                  <LoadingButton
                    size="sm"
                    onClick={handleGeneratePitch}
                    isLoading={isGeneratingPitch}
                    disabled={!lead.website_url}
                    title={!lead.website_url ? 'Website required for Pitch generation' : ''}
                  >
                    Generate Pitch
                  </LoadingButton>
                )}
              </div>

              <div className="bg-gradient-to-br from-ocean/30 to-navy rounded-2xl border border-ocean/40 p-6 min-h-[200px] shadow-sm">
                {lead.ai_pitch ? (
                  <div className="prose prose-sm max-w-none text-ice [&_h1]:text-offwhite [&_h2]:text-offwhite [&_h3]:text-offwhite [&_p]:text-ice/80 [&_li]:text-ice/80 [&_strong]:text-offwhite">
                    <ReactMarkdown>{lead.ai_pitch}</ReactMarkdown>
                  </div>
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-ice/50 text-center py-8">
                    {!lead.website_url ? (
                      <p>Cannot generate a pitch without a website to analyze.</p>
                    ) : (
                      <p>No pitch generated yet. Click the button above to create a hyper-personalized email.</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </GlassCard>
        </div>

        <div className="space-y-6">
          <GlassCard className="p-6">
            <h3 className="text-lg font-bold text-offwhite flex items-center gap-2 mb-4">
              <FileText className="w-5 h-5 text-steel" />
              Your Notes
            </h3>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add details from calls, specific contacts, or next steps..."
              className="w-full h-32 p-3 rounded-xl border border-ocean/50 bg-navy/80 focus:bg-navy focus:ring-2 focus:ring-steel/50 focus:border-steel transition-all text-sm text-ice placeholder-ice/40 resize-none mb-4"
            />
            <LoadingButton
              fullWidth
              variant="outline"
              onClick={handleSaveNotes}
              isLoading={isUpdating[`${lead.id}_notes`]}
              disabled={notes === (lead.user_notes || '')}
            >
              Save Notes
            </LoadingButton>
          </GlassCard>

          {lead.website_url ? (
            lead.website_analyses && lead.website_analyses.length > 0 ? (
              <>
                {lead.website_analyses.map((analysis: any, idx: number) => {
                  const breakdown = analysis.raw_analysis?.score_breakdown;
                  const raw = analysis.raw_analysis;
                  return (
                    <div key={idx} className="space-y-6">
                      {breakdown && (
                        <ScoreBreakdown
                          score={analysis.overall_score}
                          category={lead.lead_category}
                          breakdown={breakdown}
                        />
                      )}
                      {raw && Object.keys(raw).length > 0 && (
                        <DeepAnalysisReport
                          score={analysis.overall_score}
                          category={lead.lead_category}
                          raw={raw}
                        />
                      )}
                    </div>
                  );
                })}

                <GlassCard className="p-6">
                  <h3 className="text-lg font-bold text-offwhite flex items-center gap-2 mb-4">
                    <MessageSquare className="w-5 h-5 text-steel" />
                    Outreach Message
                  </h3>
                  {websiteMessage ? (
                    <div className="space-y-4">
                      <div className="bg-gradient-to-br from-ocean/30 to-navy rounded-xl border border-ocean/40 p-5 min-h-[100px]">
                        <p className="text-sm text-ice/90 leading-relaxed whitespace-pre-wrap">{websiteMessage}</p>
                      </div>
                      <div className="flex gap-3">
                        <LoadingButton
                          onClick={handleWhatsAppSend}
                          disabled={!lead.phone}
                          title={!lead.phone ? 'No phone number available' : ''}
                          className="flex-1"
                        >
                          <Send className="w-4 h-4" />
                          Send on WhatsApp
                        </LoadingButton>
                        <LoadingButton
                          variant="outline"
                          onClick={handleGenerateWebsiteMessage}
                          isLoading={isGeneratingMessage}
                          className="border-steel/30 text-ice"
                        >
                          Regenerate
                        </LoadingButton>
                      </div>
                    </div>
                  ) : (
                    <div className="text-center py-5">
                      <p className="text-sm text-ice/60 mb-4">
                        Generate a personalized WhatsApp message mentioning specific website issues.
                      </p>
                      <LoadingButton
                        onClick={handleGenerateWebsiteMessage}
                        isLoading={isGeneratingMessage}
                      >
                        <MessageSquare className="w-4 h-4" />
                        Generate Message
                      </LoadingButton>
                    </div>
                  )}
                </GlassCard>
              </>
            ) : (
              <GlassCard className="p-6">
                <div className="flex flex-col items-center text-center py-6">
                  <Target className="w-10 h-10 text-steel/50 mb-3" />
                  <h3 className="text-lg font-bold text-offwhite mb-1">Website Score Not Available</h3>
                  <p className="text-sm text-ice/60 mb-5 max-w-xs">
                    Click below to analyze this lead&apos;s website — we&apos;ll check for SEO, UX,
                    mobile-friendliness, and more.
                  </p>
                  <LoadingButton
                    onClick={handleAnalyzeWebsite}
                    isLoading={isAnalyzingWebsite}
                  >
                    Get Website Score
                  </LoadingButton>
                </div>
              </GlassCard>
            )
          ) : (
            <GlassCard className="p-6">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-full bg-emerald-500/20 text-emerald-400 shrink-0">
                  <CheckCircle2 className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="font-bold text-offwhite">High Opportunity Lead</h3>
                  <p className="text-sm text-ice/60">
                    No website found — this business needs digital presence the most.
                    Reach out with your proposal.
                  </p>
                </div>
              </div>
            </GlassCard>
          )}
        </div>
      </div>
    </div>
  );
}
