import { FolderSearch } from 'lucide-react';
import Link from 'next/link';

interface EmptyStateProps {
  title?: string;
  description?: string;
  actionText?: string;
  actionHref?: string;
}

export function EmptyState({
  title = 'No results found',
  description = "Try adjusting your filters or search query to find what you're looking for.",
  actionText,
  actionHref
}: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-4 text-center border-2 border-dashed border-ocean/50 rounded-3xl bg-gradient-to-br from-ocean/20 to-navy">
      <div className="bg-ocean/40 w-16 h-16 rounded-full flex items-center justify-center mb-4">
        <FolderSearch className="w-8 h-8 text-steel" />
      </div>
      <h3 className="text-lg font-bold text-offwhite mb-1">{title}</h3>
      <p className="text-sm text-ice/60 max-w-sm mb-6">
        {description}
      </p>
      {actionText && actionHref && (
        <Link
          href={actionHref}
          className="px-4 py-2 bg-steel/20 border border-steel/30 text-ice text-sm font-semibold rounded-lg hover:bg-steel/30 hover:text-offwhite transition-colors shadow-sm"
        >
          {actionText}
        </Link>
      )}
    </div>
  );
}
