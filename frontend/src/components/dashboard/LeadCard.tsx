import { GlassCard } from '@/components/shared/GlassCard';
import { Badge } from '@/components/shared/Badge';
import { LEAD_CATEGORIES, USER_STATUSES } from '@/lib/constants';
import { formatNumber, truncate } from '@/lib/utils';
import { MapPin, Globe, Star, Phone, ChevronRight, Heart, Linkedin, Mail, Clock, ExternalLink, Users } from 'lucide-react';
import Link from 'next/link';

import type { LeadListItem } from '@/lib/types';

interface LeadCardProps {
  lead: LeadListItem;
  onToggleFavorite: (id: string, current: boolean) => void;
  isUpdatingFav: boolean;
}

export function LeadCard({ lead, onToggleFavorite, isUpdatingFav }: LeadCardProps) {
  const leadCatKey = lead.lead_category || 'warm';
  const categoryConfig = LEAD_CATEGORIES[leadCatKey as keyof typeof LEAD_CATEGORIES]
    || { label: leadCatKey, color: '#94a3b8', bg: '#f1f5f9' };

  const statusConfig = lead.user_status
    ? USER_STATUSES[lead.user_status as keyof typeof USER_STATUSES]
    : USER_STATUSES.new;

  const scoreColor = lead.website_health_score != null
    ? lead.website_health_score >= 70 ? 'text-emerald-400'
      : lead.website_health_score >= 40 ? 'text-amber-400'
      : 'text-rose-400'
    : 'text-ice/40';

  return (
    <GlassCard hoverEffect className="flex flex-col group transition-all overflow-hidden relative">
      <div className="absolute inset-0 bg-gradient-to-br from-steel/[0.02] to-transparent pointer-events-none" />
      <div className="p-5 flex-1 cursor-default relative z-10">
        <div className="flex justify-between items-start mb-3">
          <div className="flex gap-1.5 items-center flex-wrap">
            <Badge
              style={{ backgroundColor: (categoryConfig as any).bg, color: categoryConfig.color }}
              className="font-bold border-0 shadow-sm text-[11px] px-2.5 py-1"
            >
              {categoryConfig.label}
            </Badge>
            {lead.website_health_score != null && (
              <span className={`text-[11px] font-bold px-2 py-1 rounded-md bg-navy/60 border border-ocean/30 ${scoreColor}`}>
                {lead.website_health_score}
              </span>
            )}
            {lead.source === 'linkedin' ? (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-400 font-semibold flex items-center gap-0.5 border border-sky-500/20">
                <Linkedin className="w-2.5 h-2.5" />
                LinkedIn
              </span>
            ) : (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-semibold flex items-center gap-0.5 border border-emerald-500/20">
                <MapPin className="w-2.5 h-2.5" />
                Maps
              </span>
            )}
          </div>
          <button
            onClick={(e) => {
              e.preventDefault();
              onToggleFavorite(lead.id, lead.is_favorite);
            }}
            disabled={isUpdatingFav}
            className="p-1.5 -mr-1.5 rounded-full hover:bg-steel/15 transition-colors text-ice/30 hover:text-rose-400 disabled:opacity-50"
          >
            <Heart
              className={`w-4.5 h-4.5 transition-all ${lead.is_favorite ? 'fill-rose-500 text-rose-500 scale-110' : ''} ${isUpdatingFav ? 'scale-90 opacity-50' : 'active:scale-75'}`}
            />
          </button>
        </div>

        <h3 className="text-base font-bold text-offwhite mb-2.5 leading-snug line-clamp-2 tracking-tight" title={lead.business_name}>
          {lead.business_name || 'Unknown Business'}
        </h3>

        <div className="flex items-center gap-2 mb-4">
          {lead.source === 'linkedin' ? (
            <div className="flex items-center gap-2 bg-ocean/25 px-2 py-1 rounded-md border border-ocean/20">
              <Users className="w-3 h-3 text-steel/70" />
              <span className="font-semibold text-[11px] text-ice/80">{lead.connections_count != null ? `${formatNumber(lead.connections_count)} connections` : '—'}</span>
            </div>
          ) : (
          <div className="flex items-center gap-1 bg-ocean/25 px-2 py-1 rounded-md border border-ocean/20">
            <Star className="w-3 h-3 fill-amber-400 text-amber-400" />
            <span className="font-semibold text-[11px] text-ice/80">{lead.rating != null ? lead.rating : '—'}</span>
            {lead.total_reviews > 0 && (
              <span className="text-[10px] text-ice/50">({formatNumber(lead.total_reviews)})</span>
            )}
          </div>
          )}
          <span className="text-[10px] px-2 py-1 bg-steel/10 text-ice/60 border border-steel/15 rounded-md font-medium truncate max-w-[130px]" title={lead.category || 'Unknown'}>
            {lead.category || 'Unknown'}
          </span>
        </div>

        <div className="space-y-2.5">
          {lead.source === 'linkedin' ? (
            <>
              {lead.email_found && (
                <div className="flex items-center gap-2.5 text-sm text-ice/70 group/item">
                  <div className="p-1.5 shrink-0 rounded-lg bg-ocean/25 text-steel/70 group-hover/item:text-ice transition-colors">
                    <Mail className="w-3.5 h-3.5" />
                  </div>
                  <span onClick={(e) => { e.stopPropagation(); window.open(`mailto:${lead.email_found}`); }} className="cursor-pointer font-medium tracking-wide text-[13px] text-emerald-400 hover:text-emerald-300 transition-colors truncate">{lead.email_found}</span>
                </div>
              )}
              {lead.headline && (
                <div className="flex items-start gap-2.5 text-sm text-ice/50 group/item">
                  <div className="p-1.5 shrink-0 rounded-lg bg-ocean/25 text-steel/50 group-hover/item:text-ice transition-colors mt-0.5">
                    <Linkedin className="w-3.5 h-3.5" />
                  </div>
                  <span className="line-clamp-2 leading-snug text-[13px]">{lead.headline}</span>
                </div>
              )}
              {lead.post_url && (
                <div className="flex items-center gap-2.5 text-sm group/item">
                  <div className="p-1.5 shrink-0 rounded-lg bg-ocean/25 text-steel/70 group-hover/item:text-ice transition-colors">
                    <ExternalLink className="w-3.5 h-3.5" />
                  </div>
                  <a href={lead.post_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} className="text-steel hover:text-ice hover:underline truncate font-medium text-[13px]">
                    View post on LinkedIn
                  </a>
                </div>
              )}
              {lead.posted_at && (
                <div className="flex items-center gap-2.5 text-sm text-ice/40">
                  <div className="p-1.5 shrink-0 rounded-lg bg-ocean/25 text-steel/50 transition-colors">
                    <Clock className="w-3.5 h-3.5" />
                  </div>
                  <span className="text-[13px]">Posted {new Date(lead.posted_at).toLocaleDateString()}</span>
                </div>
              )}
            </>
          ) : (
            <>
          {lead.phone && (
            <div className="flex items-center gap-2.5 text-sm text-ice/70 group/item">
              <div className="p-1.5 shrink-0 rounded-lg bg-ocean/25 text-steel/70 group-hover/item:text-ice transition-colors">
                <Phone className="w-3.5 h-3.5" />
              </div>
              <span onClick={(e) => { e.stopPropagation(); window.open(`tel:${lead.phone}`); }} className="cursor-pointer font-medium tracking-wide text-[13px] hover:text-ice transition-colors">{lead.phone}</span>
            </div>
          )}

          <div className="flex items-center gap-2.5 text-sm group/item">
            <div className="p-1.5 shrink-0 rounded-lg bg-ocean/25 text-steel/70 group-hover/item:text-ice transition-colors">
              <Globe className="w-3.5 h-3.5" />
            </div>
            {lead.website_url ? (
              <span onClick={(e) => { e.stopPropagation(); window.open(lead.website_url!, '_blank', 'noreferrer'); }} className="cursor-pointer text-steel hover:text-ice hover:underline truncate font-medium text-[13px]">
                {truncate(lead.website_url!.replace(/^https?:\/\/(www\.)?/, ''), 22)}
              </span>
            ) : (
              <span className="text-ice/30 italic text-[13px]">No website</span>
            )}
          </div>

          {lead.full_address && (
            <div className="flex items-start gap-2.5 text-sm text-ice/50 group/item">
              <div className="p-1.5 shrink-0 rounded-lg bg-ocean/25 text-steel/50 group-hover/item:text-ice transition-colors mt-0.5">
                <MapPin className="w-3.5 h-3.5" />
              </div>
              <span className="line-clamp-2 leading-snug text-[13px]">{lead.full_address}</span>
            </div>
          )}
            </>
          )}
        </div>
      </div>

      <Link
        href={`/dashboard/leads/${lead.id}`}
        className="relative z-10 px-5 py-3 border-t border-ocean/20 bg-navy/40 hover:bg-steel/10 flex items-center justify-between text-xs font-semibold text-steel hover:text-ice transition-all duration-300 group/link"
      >
        <span>View Full Profile</span>
        <ChevronRight className="w-3.5 h-3.5 transition-transform duration-300 group-hover/link:translate-x-1" />
      </Link>
    </GlassCard>
  );
}
