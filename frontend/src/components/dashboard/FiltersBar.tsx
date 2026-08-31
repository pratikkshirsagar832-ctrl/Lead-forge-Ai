'use client';

import { Search, Filter, SlidersHorizontal, Download } from 'lucide-react';
import { useLeads } from '@/hooks/useLeads';
import { LEAD_CATEGORIES, USER_STATUSES } from '@/lib/constants';
import { LoadingButton } from '@/components/shared/LoadingButton';

export function FiltersBar() {
  const { filters, setFilters, exportCsv, isExporting } = useLeads();

  return (
    <div className="rounded-2xl border border-ocean/25 bg-gradient-to-br from-ocean/20 to-navy/60 shadow-lg shadow-navy/20 backdrop-blur-sm">
      <div className="flex flex-col md:flex-row gap-4 p-4">
        <div className="flex-1 relative group">
          <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none">
            <Search className="h-4 w-4 text-steel/60 group-focus-within:text-ice transition-colors" />
          </div>
          <input
            type="text"
            placeholder="Search business name..."
            value={filters.search}
            onChange={(e) => setFilters({ search: e.target.value })}
            className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-ocean/30 bg-navy/60 text-sm text-ice placeholder-ice/30 focus:bg-navy/90 focus:border-steel/60 focus:ring-2 focus:ring-steel/20 outline-none transition-all"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <div className="flex items-center gap-1.5 bg-navy/50 rounded-lg border border-ocean/25 px-2 py-1">
            <Filter className="w-3.5 h-3.5 text-steel/60 shrink-0" />
            <select
              value={filters.category}
              onChange={(e) => setFilters({ category: e.target.value })}
              aria-label="Filter by category"
              className="bg-transparent border-0 text-xs font-semibold text-offwhite focus:ring-0 py-1 pl-1 pr-5 cursor-pointer outline-none appearance-none"
            >
              <option value="" style={{ color: '#cbd5e1', background: '#1e293b' }}>All Categories</option>
              {Object.entries(LEAD_CATEGORIES).map(([key, { label }]) => (
                <option key={key} value={key} style={{ color: '#cbd5e1', background: '#1e293b' }}>{label}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1.5 bg-navy/50 rounded-lg border border-ocean/25 px-2 py-1">
            <Filter className="w-3.5 h-3.5 text-steel/60 shrink-0" />
            <select
              value={filters.source}
              onChange={(e) => setFilters({ source: e.target.value })}
              aria-label="Filter by source"
              className="bg-transparent border-0 text-xs font-semibold text-offwhite focus:ring-0 py-1 pl-1 pr-5 cursor-pointer outline-none appearance-none"
            >
              <option value="" style={{ color: '#cbd5e1', background: '#1e293b' }}>All Sources</option>
              <option value="google_maps" style={{ color: '#cbd5e1', background: '#1e293b' }}>Google Maps</option>
              <option value="linkedin" style={{ color: '#cbd5e1', background: '#1e293b' }}>LinkedIn</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5 bg-navy/50 rounded-lg border border-ocean/25 px-2 py-1">
            <Filter className="w-3.5 h-3.5 text-steel/60 shrink-0" />
            <select
              value={filters.postType}
              onChange={(e) => setFilters({ postType: e.target.value })}
              aria-label="Filter by lead type"
              className="bg-transparent border-0 text-xs font-semibold text-offwhite focus:ring-0 py-1 pl-1 pr-5 cursor-pointer outline-none appearance-none"
            >
              <option value="" style={{ color: '#cbd5e1', background: '#1e293b' }}>All Types</option>
              <option value="buyer" style={{ color: '#cbd5e1', background: '#1e293b' }}>Needs Service</option>
              <option value="agency" style={{ color: '#cbd5e1', background: '#1e293b' }}>Agency</option>
              <option value="hiring" style={{ color: '#cbd5e1', background: '#1e293b' }}>Hiring</option>
            </select>
          </div>

          <div className="flex items-center gap-1.5 bg-navy/50 rounded-lg border border-ocean/25 px-2 py-1">
            <SlidersHorizontal className="w-3.5 h-3.5 text-steel/60 shrink-0" />
            <select
              value={filters.status}
              onChange={(e) => setFilters({ status: e.target.value })}
              aria-label="Filter by status"
              className="bg-transparent border-0 text-xs font-semibold text-offwhite focus:ring-0 py-1 pl-1 pr-5 cursor-pointer outline-none appearance-none"
            >
              <option value="" style={{ color: '#cbd5e1', background: '#1e293b' }}>All Statuses</option>
              {Object.entries(USER_STATUSES).map(([key, { label }]) => (
                <option key={key} value={key} style={{ color: '#cbd5e1', background: '#1e293b' }}>{label}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-1.5 bg-navy/50 rounded-lg border border-ocean/25 px-3 py-1">
            <select
              value={filters.isFavorite === null ? '' : String(filters.isFavorite)}
              onChange={(e) => setFilters({ isFavorite: e.target.value === '' ? null : e.target.value === 'true' })}
              aria-label="Filter by favorites"
              className="bg-transparent border-0 text-xs font-semibold text-offwhite focus:ring-0 py-1 cursor-pointer outline-none appearance-none"
            >
              <option value="" style={{ color: '#cbd5e1', background: '#1e293b' }}>All Leads</option>
              <option value="true" style={{ color: '#cbd5e1', background: '#1e293b' }}>Favorites Only</option>
            </select>
          </div>

          <LoadingButton
            variant="outline"
            size="sm"
            onClick={exportCsv}
            isLoading={isExporting}
            className="gap-1.5 border-steel/30 text-offwhite hover:bg-steel/10"
          >
            <Download className="w-3.5 h-3.5" />
            Export
          </LoadingButton>
        </div>
      </div>
    </div>
  );
}
