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
    <div className="surface-3d flex flex-col items-center justify-center py-20 px-4 text-center rounded-3xl">
      <div className="stage-3d mb-6">
        <div className="float-3d motion-reduce:animate-none tile-3d w-16 h-16 rounded-2xl flex items-center justify-center [transform:rotateX(12deg)]">
          <FolderSearch className="w-8 h-8 text-steel" />
        </div>
        <div className="mx-auto mt-3 h-2 w-12 rounded-full bg-[#010c0a]/70 blur-md" />
      </div>
      <h3 className="text-lg font-bold text-offwhite mb-1 [text-wrap:balance]" style={{ fontFamily: 'var(--font-heading)' }}>{title}</h3>
      <p className="text-sm text-ice/60 max-w-sm mb-7 [text-wrap:pretty]">
        {description}
      </p>
      {actionText && actionHref && (
        <Link
          href={actionHref}
          className="btn-3d-teal inline-flex h-11 items-center px-5 text-sm rounded-xl"
        >
          {actionText}
        </Link>
      )}
    </div>
  );
}
