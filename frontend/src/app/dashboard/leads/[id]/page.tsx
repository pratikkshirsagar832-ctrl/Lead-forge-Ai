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
import { 
  ArrowLeft, MapPin, Phone, Globe, Star, Mail, 
  MessageSquare, FileText, CheckCircle, ExternalLink, Activity
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

  useEffect(() => {
    const fetchLeadDetail = async () => {
      try {
        const { data } = await api.get(API_ROUTES.leads.detail(id as string));
        setLead(data);
        setNotes(data.notes || '');
      } catch (error) {
        showToast('Failed to load lead details', 'error');
        router.push('/dashboard/leads');
      } finally {
        setIsPageLoading(false);
      }
    };
    if (id) fetchLeadDetail();
  }, [id, router, showToast]);

  const handleStatusChange = async (newStatus: string) => {
    await updateLeadStatus(id as string, newStatus);
    if (lead) setLead({ ...lead, status: newStatus });
  };

  const handleSaveNotes = async () => {
    await updateLeadNotes(id as string, notes);
    if (lead) setLead({ ...lead, notes });
  };

  const handleGeneratePitch = async () => {
    try {
      setIsGeneratingPitch(true);
      const { data } = await api.post(API_ROUTES.ai.pitch(id as string));
      setLead({ ...lead, ai_pitch: data.pitch });
      showToast('AI Pitch generated successfully!', 'success');
    } catch (error: any) {
      showToast(error.response?.data?.detail || 'Failed to generate pitch', 'error');
    } finally {
      setIsGeneratingPitch(false);
    }
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

  if (!lead) return null;

  const leadCatKey = lead.lead_category || 'warm';
  const categoryConfig = LEAD_CATEGORIES[leadCatKey as keyof typeof LEAD_CATEGORIES] 
    || { label: leadCatKey, color: '#94a3b8', bg: '#f1f5f9' };

  return (
    <div className="space-y-6 animate-in fade-in duration-500 pb-12">
      <button 
        onClick={() => router.back()} 
        className="flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-slate-900 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back to Leads
      </button>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Main Info Column */}
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
                  {lead.is_favorite && (
                    <Badge variant="outline" className="border-rose-200 text-rose-600 bg-rose-50">
                      Favorited
                    </Badge>
                  )}
                </div>
                <h1 className="text-3xl font-bold text-slate-900 mb-2">{lead.business_name}</h1>
                <div className="flex items-center gap-4 text-slate-600">
                  <div className="flex items-center gap-1.5">
                    <Star className="w-5 h-5 fill-amber-400 text-amber-400" />
                    <span className="font-semibold text-slate-700">{lead.rating != null ? lead.rating : 'N/A'}</span>
                    <span className="text-sm">({formatNumber(lead.total_reviews || 0)} reviews)</span>
                  </div>
                  {lead.category && (
                    <span className="text-sm px-2 py-0.5 rounded-md bg-slate-100 italic">
                      {lead.category}
                    </span>
                  )}
                </div>
              </div>

              {/* Status Selector */}
              <div className="shrink-0">
                <label className="block text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2 md:text-right">
                  Pipeline Status
                </label>
                <div className="flex gap-2 p-1 bg-slate-100 rounded-xl overflow-x-auto">
                  {Object.entries(USER_STATUSES).map(([key, config]) => (
                    <button
                      key={key}
                      disabled={isUpdating[`${lead.id}_status`]}
                      onClick={() => handleStatusChange(key)}
                      className={`px-4 py-2 rounded-lg text-sm font-medium transition-all whitespace-nowrap ${
                        lead.status === key 
                          ? 'bg-white shadow-sm ring-1 ring-slate-200/50 text-slate-900' 
                          : 'text-slate-500 hover:text-slate-700'
                      }`}
                      style={lead.status === key ? { color: config.color } : {}}
                    >
                      {config.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Contact Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 py-6 border-y border-slate-100">
              <div className="flex items-start gap-3">
                <div className="p-2.5 rounded-lg bg-indigo-50 text-indigo-600 shrink-0">
                  <MapPin className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500 mb-0.5">Address</p>
                  <p className="text-slate-900">{lead.full_address || 'No address provided'}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="p-2.5 rounded-lg bg-indigo-50 text-indigo-600 shrink-0">
                  <Phone className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500 mb-0.5">Phone</p>
                  <p className="text-slate-900">{lead.phone || 'No phone provided'}</p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="p-2.5 rounded-lg bg-indigo-50 text-indigo-600 shrink-0">
                  <Globe className="w-5 h-5" />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-500 mb-0.5">Website</p>
                  {lead.website_url ? (
                    <a href={lead.website_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline flex items-center gap-1 group">
                      {lead.website_url.replace(/^https?:\/\/(www\.)?/, '')}
                      <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                    </a>
                  ) : (
                    <p className="text-slate-900">No website provided</p>
                  )}
                </div>
              </div>
            </div>

            {/* AI Pitch Section */}
            <div className="mt-8">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2">
                  <MessageSquare className="w-5 h-5 text-indigo-600" />
                  AI Outreach Pitch
                </h3>
                {!lead.ai_pitch && (
                  <LoadingButton 
                    size="sm" 
                    onClick={handleGeneratePitch} 
                    isLoading={isGeneratingPitch}
                    disabled={!lead.website_url}
                    title={!lead.website_url ? "Website required for Pitch generation" : ""}
                  >
                    Generate Pitch
                  </LoadingButton>
                )}
              </div>
              
              <div className="bg-white rounded-2xl border border-slate-200 p-6 min-h-[200px] shadow-sm">
                {lead.ai_pitch ? (
                  <div className="prose prose-sm max-w-none text-slate-800 [&_h1]:text-slate-900 [&_h2]:text-slate-900 [&_h3]:text-slate-900 [&_p]:text-slate-700 [&_li]:text-slate-700 [&_strong]:text-slate-900">
                     <ReactMarkdown>{lead.ai_pitch}</ReactMarkdown>
                  </div>
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center py-8">
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

        {/* Sidebar Column */}
        <div className="space-y-6">
          {/* Notes Card */}
          <GlassCard className="p-6">
            <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-4">
              <FileText className="w-5 h-5 text-slate-400" />
              Your Notes
            </h3>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add details from calls, specific contacts, or next steps..."
              className="w-full h-32 p-3 rounded-xl border border-slate-200 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 transition-all text-sm text-slate-900 resize-none mb-4"
            />
            <LoadingButton 
              fullWidth 
              variant="outline"
              onClick={handleSaveNotes}
              isLoading={isUpdating[`${lead.id}_notes`]}
              disabled={notes === (lead.notes || '')}
            >
              Save Notes
            </LoadingButton>
          </GlassCard>

          {/* Website Analysis Card */}
          {lead.website_analyses && lead.website_analyses.length > 0 && (
            <GlassCard className="p-6">
              <h3 className="text-lg font-bold text-slate-900 flex items-center gap-2 mb-4">
                <Activity className="w-5 h-5 text-slate-400" />
                Website Analysis
              </h3>
              
              {lead.website_analyses.map((analysis: any, idx: number) => (
                <div key={idx} className="space-y-4">
                  <div className="flex justify-between items-center mb-2">
                    <span className="text-sm font-medium text-slate-600">Health Score</span>
                    <span className={`text-lg font-bold ${analysis.score >= 70 ? 'text-emerald-600' : analysis.score >= 40 ? 'text-amber-600' : 'text-rose-600'}`}>
                      {analysis.score}/100
                    </span>
                  </div>
                  
                  {analysis.issues && analysis.issues.length > 0 && (
                    <div className="space-y-2">
                      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Identified Issues</p>
                      <ul className="space-y-2">
                        {analysis.issues.map((issue: string, i: number) => (
                          <li key={i} className="flex gap-2 text-sm text-slate-700 bg-rose-50/50 p-2 rounded-lg border border-rose-100/50">
                            <span className="text-rose-500 shrink-0 mt-0.5">•</span>
                            <span className="leading-tight">{issue}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </GlassCard>
          )}
        </div>
      </div>
    </div>
  );
}
