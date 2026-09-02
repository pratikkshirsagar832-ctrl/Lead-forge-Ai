import { Badge } from '@/components/shared/Badge';

const POST_TYPE_CONFIG: Record<string, { label: string; className: string }> = {
  buyer: { label: 'Needs Service', className: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
  hiring: { label: 'Hiring', className: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  job_seeker: { label: 'Job Seeker', className: 'bg-zinc-500/15 text-zinc-400 border-zinc-500/30' },
  unknown: { label: 'Post', className: 'bg-white/5 text-ice/50 border-white/10' },
};

export const WORK_TYPE_CONFIG: Record<string, { label: string; className: string }> = {
  remote: { label: '🌍 Remote', className: 'bg-sky-500/15 text-sky-400 border-sky-500/30' },
  contract: { label: '📄 Contract', className: 'bg-violet-500/15 text-violet-400 border-violet-500/30' },
  part_time: { label: '⏱️ Part-time', className: 'bg-teal-500/15 text-teal-400 border-teal-500/30' },
  full_time_onsite: { label: '🏢 On-site', className: 'bg-rose-500/15 text-rose-400 border-rose-500/30' },
  unknown: { label: '—', className: 'bg-white/5 text-ice/40 border-white/10' },
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

export function WorkTypeBadge({ workType, className = '' }: { workType?: string | null; className?: string }) {
  if (!workType) return null;
  const key = workType.toLowerCase() as keyof typeof WORK_TYPE_CONFIG;
  const config = WORK_TYPE_CONFIG[key] || WORK_TYPE_CONFIG.unknown;
  return (
    <Badge variant="outline" className={`${config.className} text-[10px] px-1.5 py-0.5 font-semibold ${className}`}>
      {config.label}
    </Badge>
  );
}