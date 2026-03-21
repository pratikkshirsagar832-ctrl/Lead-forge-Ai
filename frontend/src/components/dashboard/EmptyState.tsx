import { FolderSearch } from 'lucide-react';
import Link from 'next/link';

interface EmptyStateProps {
  title?: string;
  description?: string;
  actionText?: string;
  actionHref?: string;
}

export function EmptyState({ 
  title = "No results found", 
  description = "Try adjusting your filters or search query to find what you're looking for.",
  actionText,
  actionHref
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-4 text-center border-2 border-dashed border-slate-200 rounded-3xl bg-slate-50\50">
      <div className="bg-slate-100 w-16 h-16 rounded-full flex items-center justify-center mb-4">
        <FolderSearch className="w-8 h-8 text-slate-400" />
      </div>
      <h3 className="text-lg font-bold text-slate-900 mb-1">{title}</h3>
      <p className="text-sm text-slate-500 max-w-sm mb-6">
        {description}
      </p>
      {actionText && actionHref && (
        <Link 
          href={actionHref}
          className="px-4 py-2 bg-white border border-slate-200 text-slate-700 text-sm font-semibold rounded-lg hover:bg-slate-50 hover:text-slate-900 transition-colors shadow-sm"
        >
          {actionText}
        </Link>
      )}
    </div>
  );
}
