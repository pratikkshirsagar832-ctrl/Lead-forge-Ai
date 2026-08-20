import { Badge } from '@/components/shared/Badge';

const POST_TYPE_CONFIG: Record<string, { label: string; className: string }> = {
  buyer: { label: 'Needs Service', className: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
  agency: { label: 'Agency', className: 'bg-violet-500/15 text-violet-400 border-violet-500/30' },
  hiring: { label: 'Hiring', className: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  job_seeker: { label: 'Job Seeker', className: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30' },
  unknown: { label: 'Post', className: 'bg-white/5 text-ice/50 border-white/10' },
};

export function PostTypeBadge({ postType, className = '' }: { postType?: string | null; className?: string }) {
  if (!postType) return null;
  const config = POST_TYPE_CONFIG[postType] || POST_TYPE_CONFIG.unknown;
  return (
    <Badge variant="outline" className={`${config.className} text-[10px] px-1.5 py-0.5 font-semibold ${className}`}>
      {config.label}
    </Badge>
  );
}