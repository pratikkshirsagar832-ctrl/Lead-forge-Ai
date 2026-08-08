import { cn } from '@/lib/utils';

export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('animate-pulse rounded-md bg-steel/10', className)}
      {...props}
    />
  );
}

export function CardSkeleton() {
  return (
    <div className="p-6 rounded-2xl border border-steel/20 bg-gradient-to-br from-sapphire/30 to-navy/85 shadow-sm space-y-4">
      <div className="flex items-center justify-between">
        <Skeleton className="h-6 w-1/3 bg-steel/10" />
        <Skeleton className="h-6 w-16 rounded-full bg-steel/10" />
      </div>
      <div className="space-y-2">
        <Skeleton className="h-4 w-full bg-steel/10" />
        <Skeleton className="h-4 w-5/6 bg-steel/10" />
      </div>
      <div className="pt-4 flex gap-2">
        <Skeleton className="h-9 w-24 rounded-lg bg-steel/10" />
        <Skeleton className="h-9 w-24 rounded-lg bg-steel/10" />
      </div>
    </div>
  );
}
