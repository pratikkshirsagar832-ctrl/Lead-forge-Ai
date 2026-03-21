'use client';

import { useLeads } from '@/hooks/useLeads';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { Download, FileSpreadsheet, ShieldAlert } from 'lucide-react';

export default function ExportPage() {
  const { exportCsv, isExporting, totalCount } = useLeads();

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold text-slate-900 tracking-tight">Export Data</h1>
        <p className="text-slate-500 mt-2">Download your leads for use in other CRM platforms or cold email tools.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <GlassCard className="p-8">
          <div className="w-16 h-16 rounded-2xl bg-indigo-50 flex items-center justify-center mb-6">
            <FileSpreadsheet className="w-8 h-8 text-indigo-600" />
          </div>
          
          <h2 className="text-xl font-bold text-slate-900 mb-2">Export to CSV</h2>
          <p className="text-slate-600 mb-8 leading-relaxed">
            Download the current filtered view of your leads as a CSV file. This includes all lead details, website analysis scores, and any AI-generated pitches.
          </p>

          <div className="bg-slate-50 rounded-xl p-4 mb-8 border border-slate-100 flex items-start gap-3">
            <ShieldAlert className="w-5 h-5 text-slate-400 shrink-0 mt-0.5" />
            <p className="text-sm text-slate-600">
              The export will respect your current filters set on the Leads page. If you want to export all {totalCount} leads, ensure all filters are cleared first.
            </p>
          </div>

          <LoadingButton 
            size="lg" 
            onClick={exportCsv} 
            isLoading={isExporting}
            className="w-full sm:w-auto"
          >
            <Download className="w-5 h-5 mr-2" />
            Download CSV Format
          </LoadingButton>
        </GlassCard>

        {/* Placeholder for future integrations */}
        <div className="opacity-50 pointer-events-none">
          <GlassCard className="p-8 h-full">
            <div className="w-16 h-16 rounded-2xl bg-rose-50 flex items-center justify-center mb-6">
              <Download className="w-8 h-8 text-rose-600" />
            </div>
            
            <h2 className="text-xl font-bold text-slate-900 mb-2">Instantly Integration</h2>
            <div className="inline-block px-2 py-1 bg-slate-200 text-slate-700 text-xs font-bold rounded mb-4">COMING SOON</div>
            
            <p className="text-slate-600 leading-relaxed">
              Push approved active leads directly into an Instantly.ai campaign via their API without needing manual CSV upload.
            </p>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
