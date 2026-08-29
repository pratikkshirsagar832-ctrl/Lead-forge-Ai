'use client';

import { forwardRef } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';

interface LoadingButtonProps extends Omit<React.ComponentPropsWithoutRef<typeof motion.button>, 'onDrag' | 'onDragStart' | 'onDragEnd' | 'children'> {
  children?: React.ReactNode;
  isLoading?: boolean;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'outline' | 'gradient' | 'gold' | 'premium' | 'neon' | 'gradient-cyan' | 'gradient-purple' | 'glass';
  size?: 'sm' | 'md' | 'lg';
  fullWidth?: boolean;
  icon?: React.ReactNode;
}

export const LoadingButton = forwardRef<HTMLButtonElement, LoadingButtonProps>(
  (
    {
      children,
      isLoading = false,
      variant = 'primary',
      size = 'md',
      fullWidth = false,
      icon,
      className,
      disabled,
      ...props
    },
    ref
  ) => {
    const baseStyles = 'relative inline-flex items-center justify-center font-semibold tracking-wide transition-all duration-300 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-navy disabled:opacity-50 disabled:cursor-not-allowed overflow-hidden rounded-xl';

    const variants: Record<string, string> = {
      primary:
        'bg-steel text-offwhite hover:bg-steel/80 focus:ring-steel/50',
      secondary:
        'bg-ocean/60 text-ice border border-steel/30 hover:bg-ocean/80 hover:text-offwhite focus:ring-steel/30',
      danger:
        'bg-gradient-to-r from-rose-600 to-red-600 text-white hover:from-rose-500 hover:to-red-500 focus:ring-rose-500/50',
      ghost:
        'bg-transparent text-ice/60 hover:bg-steel/10 hover:text-ice border border-transparent hover:border-steel/20',
      outline:
        'border-2 border-steel/50 text-steel hover:bg-steel/10 hover:text-ice focus:ring-steel/50',
      gradient:
        'bg-gradient-to-r from-steel to-ocean text-offwhite hover:from-steel/90 hover:to-ocean/90 focus:ring-steel/50',
      gold:
        'bg-gradient-to-r from-amber to-amber-dark text-navy font-bold hover:from-amber-dark hover:to-amber focus:ring-amber/50',
      premium:
        'bg-gradient-to-r from-primary to-steel text-offwhite hover:from-primary/90 hover:to-steel/90 focus:ring-steel/50',
      neon:
        'btn-neon text-offwhite focus:ring-accent-cyan/50',
      'gradient-cyan':
        'btn-gradient-cyan text-navy focus:ring-accent-cyan/50',
      'gradient-purple':
        'btn-gradient-purple text-navy focus:ring-violet-500/50',
      glass:
        'btn-glass text-offwhite focus:ring-accent-cyan/30',
    };

    const sizes: Record<string, string> = {
      sm: 'text-xs px-3 py-1.5',
      md: 'text-sm px-5 py-2.5',
      lg: 'text-base px-7 py-3.5',
    };

    return (
      <motion.button
        ref={ref}
        whileTap={{ scale: disabled || isLoading ? 1 : 0.97 }}
        whileHover={disabled || isLoading ? {} : { scale: 1.02 }}
        className={cn(
          baseStyles,
          variants[variant] || variants.primary,
          sizes[size] || sizes.md,
          fullWidth && 'w-full',
          className
        )}
        disabled={disabled || isLoading}
        {...props}
      >
        <span className={cn('flex items-center justify-center gap-2', isLoading && 'opacity-0')}>
          {icon && <span className="w-4 h-4">{icon}</span>}
          {children}
        </span>

        {isLoading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="absolute inset-0 flex items-center justify-center bg-inherit"
          >
            <Loader2 className={cn('w-5 h-5 animate-spin', variant === 'gold' ? 'text-navy' : 'text-current')} />
          </motion.div>
        )}
      </motion.button>
    );
  }
);

LoadingButton.displayName = 'LoadingButton';
