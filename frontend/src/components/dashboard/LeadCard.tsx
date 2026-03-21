import { GlassCard } from '@/components/shared/GlassCard';
import { Badge } from '@/components/shared/Badge';
import { LEAD_CATEGORIES, USER_STATUSES } from '@/lib/constants';
import { formatNumber, truncate } from '@/lib/utils';
import { MapPin, Globe, Star, Users, Phone, ChevronRight, Heart } from 'lucide-react';
import Link from 'next/link';

interface LeadCardProps {
  lead: any;
  onToggleFavorite: (id: string, current: boolean) => void;
  isUpdatingFav: boolean;
}

export function LeadCard({ lead, onToggleFavorite, isUpdatingFav }: LeadCardProps) {
  const leadCatKey = lead.lead_category || 'warm';
  const categoryConfig = LEAD_CATEGORIES[leadCatKey as keyof typeof LEAD_CATEGORIES] 
    || { label: leadCatKey, color: '#94a3b8', bg: '#f1f5f9' };
    
  const statusConfig = lead.status
    ? USER_STATUSES[lead.status as keyof typeof USER_STATUSES]
    : USER_STATUSES.new;

  return (
    <GlassCard hoverEffect className="flex flex-col group transition-all bg-slate-900 border-white/10 shadow-lg hover:shadow-xl hover:shadow-indigo-500/10 overflow-hidden relative">
      <div className="absolute inset-0 bg-gradient-to-br from-white/[0.02] to-transparent pointer-events-none" />
      <div className="p-5 flex-1 cursor-default relative z-10">
        <div className="flex justify-between items-start mb-4">
          <div className="flex gap-2 items-center flex-wrap">
            {categoryConfig && (
              <Badge 
                style={{ backgroundColor: (categoryConfig as any).bg, color: categoryConfig.color }}
                className="font-bold border-0 shadow-sm"
              >
                {categoryConfig.label}
              </Badge>
            )}
            <Badge variant="outline" dot style={{ color: statusConfig.color, borderColor: 'rgba(255,255,255,0.1)' }}>
              <span style={{ color: statusConfig.color }}>{statusConfig.label}</span>
            </Badge>
          </div>
          <button 
            onClick={(e) => {
              e.preventDefault();
              onToggleFavorite(lead.id, lead.is_favorite);
            }}
            disabled={isUpdatingFav}
            className="p-1.5 -mr-1.5 rounded-full hover:bg-white/10 transition-colors text-slate-500 hover:text-rose-400 disabled:opacity-50"
          >
            <Heart 
              className={`w-5 h-5 transition-transform ${lead.is_favorite ? 'fill-rose-500 text-rose-500' : ''} ${isUpdatingFav ? 'scale-90' : 'active:scale-75'}`} 
            />
          </button>
        </div>

        <h3 className="text-lg font-bold text-white mb-2 leading-tight line-clamp-2" title={lead.business_name}>
          {lead.business_name || 'Unknown Business'}
        </h3>
        
        {/* Rating and Niche */}
        <div className="flex items-center gap-2 mb-5">
          <div className="flex items-center gap-1.5 bg-slate-800/50 px-2 py-1 rounded-md border border-white/5">
            <Star className="w-3.5 h-3.5 fill-amber-400 text-amber-400" />
            <span className="font-semibold text-xs text-slate-200">{lead.rating != null ? lead.rating : 'No rating'}</span>
            {lead.total_reviews > 0 && (
              <span className="text-[10px] text-slate-400">({formatNumber(lead.total_reviews)})</span>
            )}
          </div>
          <span className="text-[11px] px-2.5 py-1 bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 rounded-md font-medium truncate max-w-[140px]" title={lead.category || 'Unknown'}>
            {lead.category || 'Unknown'}
          </span>
        </div>

        <div className="space-y-3">
          {lead.phone && (
            <div className="flex items-center gap-3 text-sm text-slate-300 group/item">
              <div className="p-1.5 shrink-0 rounded-md bg-white/5 text-slate-400 group-hover/item:text-indigo-400 transition-colors">
                <Phone className="w-3.5 h-3.5" />
              </div>
              <span className="font-medium tracking-wide">{lead.phone}</span>
            </div>
          )}
          
          <div className="flex items-center gap-3 text-sm group/item">
            <div className="p-1.5 shrink-0 rounded-md bg-white/5 text-slate-400 group-hover/item:text-indigo-400 transition-colors">
              <Globe className="w-3.5 h-3.5" />
            </div>
            {lead.website_url ? (
              <a href={lead.website_url} target="_blank" rel="noreferrer" className="text-indigo-400 hover:text-indigo-300 hover:underline truncate font-medium" onClick={(e) => e.stopPropagation()}>
                {truncate(lead.website_url.replace(/^https?:\/\/(www\.)?/, ''), 25)}
              </a>
            ) : (
              <span className="text-slate-500 italic text-sm">No website available</span>
            )}
          </div>

          {lead.full_address && (
            <div className="flex items-start gap-3 text-sm text-slate-400 group/item pt-1">
              <div className="p-1.5 shrink-0 rounded-md bg-white/5 text-slate-400 group-hover/item:text-indigo-400 transition-colors mt-0.5">
                <MapPin className="w-3.5 h-3.5" />
              </div>
              <span className="line-clamp-2 leading-snug">{lead.full_address}</span>
            </div>
          )}
        </div>
      </div>
      
      <Link 
        href={`/dashboard/leads/${lead.id}`}
        className="relative z-10 px-5 py-3.5 border-t border-white/5 bg-slate-900 border-b border-transparent hover:bg-indigo-500/5 flex items-center justify-between text-sm font-semibold text-indigo-400 hover:text-indigo-300 transition-all duration-300"
      >
        View Full Profile
        <ChevronRight className="w-4 h-4 transition-transform group-hover:translate-x-1" />
      </Link>
    </GlassCard>
  );
}
