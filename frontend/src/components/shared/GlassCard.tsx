'use client';

import { HTMLAttributes, forwardRef, ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { motion, HTMLMotionProps } from 'framer-motion';

interface GlassCardProps extends HTMLMotionProps<'div'> {
  hoverEffect?: boolean;
  children?: ReactNode;
}

export const GlassCard = forwardRef<HTMLDivElement, GlassCardProps>(
  ({ className, hoverEffect = false, children, ...props }, ref) => {
    return (
      <motion.div
        ref={ref}
        whileHover={hoverEffect ? { y: -2, boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01)' } : undefined}
        className={cn(
          'relative overflow-hidden rounded-2xl bg-white/80 backdrop-blur-xl border border-white/40 shadow-sm transition-all duration-300',
          className
        )}
        {...props}
      >
        {/* Subtle top glare effect */}
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/50 to-transparent pointer-events-none" />
        
        {children}
      </motion.div>
    );
  }
);

GlassCard.displayName = 'GlassCard';
