'use client';

import { ButtonHTMLAttributes, forwardRef } from 'react';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { motion } from 'framer-motion';

interface LoadingButtonProps extends Omit<React.ComponentPropsWithoutRef<typeof motion.button>, 'onDrag' | 'onDragStart' | 'onDragEnd' | 'children'> {
  children?: React.ReactNode;
  isLoading?: boolean;
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost' | 'outline';
  size?: 'sm' | 'md' | 'lg';
  fullWidth?: boolean;
}

export const LoadingButton = forwardRef<HTMLButtonElement, LoadingButtonProps>(
  (
    {
      children,
      isLoading = false,
      variant = 'primary',
      size = 'md',
      fullWidth = false,
      className,
      disabled,
      ...props
    },
    ref
  ) => {
    const baseStyles = 'relative inline-flex items-center justify-center font-medium transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-60 disabled:cursor-not-allowed overflow-hidden rounded-xl';
    
    const variants = {
      primary: 'bg-indigo-600 text-white hover:bg-indigo-700 focus:ring-indigo-500 shadow-sm hover:shadow active:scale-[0.98]',
      secondary: 'bg-white text-slate-700 border border-slate-200 hover:border-slate-300 hover:bg-slate-50 focus:ring-slate-200 shadow-sm active:scale-[0.98]',
      danger: 'bg-red-500 text-white hover:bg-red-600 focus:ring-red-500 shadow-sm active:scale-[0.98]',
      ghost: 'bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900 active:scale-[0.98]',
      outline: 'border-2 border-indigo-600 text-indigo-600 hover:bg-indigo-50 focus:ring-indigo-500 active:scale-[0.98]',
    };

    const sizes = {
      sm: 'text-xs px-3 py-1.5',
      md: 'text-sm px-4 py-2',
      lg: 'text-base px-6 py-3',
    };

    return (
      <motion.button
        ref={ref}
        whileTap={{ scale: disabled || isLoading ? 1 : 0.98 }}
        className={cn(
          baseStyles,
          variants[variant],
          sizes[size],
          fullWidth && 'w-full',
          className
        )}
        disabled={disabled || isLoading}
        {...props}
      >
        <span className={cn('flex items-center justify-center gap-2', isLoading && 'opacity-0')}>
          {children}
        </span>
        
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center bg-inherit">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        )}
      </motion.button>
    );
  }
);

LoadingButton.displayName = 'LoadingButton';
