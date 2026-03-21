import { Search, Filter, SlidersHorizontal, Download } from 'lucide-react';
import { useLeads } from '@/hooks/useLeads';
import { LEAD_CATEGORIES, USER_STATUSES } from '@/lib/constants';
import { LoadingButton } from '@/components/shared/LoadingButton';

export function FiltersBar() {
  const { filters, setFilters, exportCsv, isExporting } = useLeads();

  return (
    <div className="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm space-y-4">
      <div className="flex flex-col md:flex-row gap-4">
        {/* Search Input */}
        <div className="flex-1 relative">
          <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
            <Search className="h-4 w-4 text-slate-400" />
          </div>
          <input
            type="text"
            placeholder="Search business name..."
            value={filters.search}
            onChange={(e) => setFilters({ search: e.target.value })}
            className="w-full pl-9 pr-4 py-2 rounded-xl border border-slate-200 bg-slate-50 focus:bg-white focus:ring-2 focus:ring-indigo-500 transition-all text-sm"
          />
        </div>

        {/* Filters Grid */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 bg-slate-50 rounded-lg p-1 border border-slate-200">
            <Filter className="w-4 h-4 text-slate-400 ml-2" />
            <select
              value={filters.category}
              onChange={(e) => setFilters({ category: e.target.value })}
              className="bg-transparent border-0 text-sm font-medium text-slate-700 focus:ring-0 py-1 pl-1 pr-6 cursor-pointer"
            >
              <option value="">All Categories</option>
              {Object.entries(LEAD_CATEGORIES).map(([key, { label }]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2 bg-slate-50 rounded-lg p-1 border border-slate-200">
            <SlidersHorizontal className="w-4 h-4 text-slate-400 ml-2" />
            <select
              value={filters.status}
              onChange={(e) => setFilters({ status: e.target.value })}
              className="bg-transparent border-0 text-sm font-medium text-slate-700 focus:ring-0 py-1 pl-1 pr-6 cursor-pointer"
            >
              <option value="">All Statuses</option>
              {Object.entries(USER_STATUSES).map(([key, { label }]) => (
                <option key={key} value={key}>{label}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2 bg-slate-50 rounded-lg p-1 border border-slate-200">
            <select
              value={filters.isFavorite === null ? '' : String(filters.isFavorite)}
              onChange={(e) => setFilters({ isFavorite: e.target.value === '' ? null : e.target.value === 'true' })}
              className="bg-transparent border-0 text-sm font-medium text-slate-700 focus:ring-0 py-1 px-3 cursor-pointer"
            >
              <option value="">All Leads</option>
              <option value="true">Favorites Only</option>
            </select>
          </div>
          
          <div className="ml-auto">
             <LoadingButton 
                variant="outline" 
                size="sm" 
                onClick={exportCsv} 
                isLoading={isExporting}
                className="gap-2"
              >
                <Download className="w-4 h-4" />
                Export CSV
              </LoadingButton>
          </div>
        </div>
      </div>
    </div>
  );
}
