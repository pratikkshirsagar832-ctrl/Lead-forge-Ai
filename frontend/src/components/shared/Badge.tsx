import { HTMLAttributes } from 'react';
import { cn } from '@/lib/utils';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info' | 'outline' | 'premium';
  dot?: boolean;
}

export function Badge({
  children,
  variant = 'default',
  dot = false,
  className,
  ...props
}: BadgeProps) {
  const variants = {
    default: 'bg-steel/15 text-ice border border-steel/10',
    success: 'bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/20',
    warning: 'bg-amber-500/10 text-amber-400 ring-1 ring-inset ring-amber-500/20',
    error: 'bg-red-500/10 text-red-400 ring-1 ring-inset ring-red-500/20',
    info: 'bg-steel/20 text-ice ring-1 ring-inset ring-steel/30',
    outline: 'bg-transparent text-ice/60 border border-steel/30',
    premium: 'bg-gradient-to-r from-violet/20 to-steel/20 text-offwhite border border-violet/30 shadow-sm',
  };

  const dotColors = {
    default: 'bg-steel',
    success: 'bg-emerald-400',
    warning: 'bg-amber-400',
    error: 'bg-red-400',
    info: 'bg-steel',
    outline: 'bg-ice/40',
    premium: 'bg-violet-400',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors',
        variants[variant],
        className
      )}
      {...props}
    >
      {dot && (
        <span className={cn('w-1.5 h-1.5 rounded-full', dotColors[variant])} />
      )}
      {children}
    </span>
  );
}
