'use client';

import { forwardRef, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { motion, type HTMLMotionProps } from 'framer-motion';

interface GlassCardProps extends HTMLMotionProps<'div'> {
  hoverEffect?: boolean;
  glowBorder?: boolean;
  children?: ReactNode;
  elevation?: 1 | 2 | 3 | 4;
  delay?: number;
  gradient?: boolean;
  interactive?: boolean;
}

export const GlassCard = forwardRef<HTMLDivElement, GlassCardProps>(
  ({
    className,
    hoverEffect = false,
    glowBorder = false,
    elevation,
    delay = 0,
    gradient = false,
    interactive = false,
    children,
    ...props
  }, ref) => {
    return (
      <motion.div
        ref={ref}
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay, ease: [0.25, 0.1, 0.25, 1] }}
        whileHover={hoverEffect ? {
          y: -4,
          boxShadow: '0 20px 60px -12px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(59, 130, 196, 0.2)',
          transition: { duration: 0.25, ease: 'easeOut' },
        } : undefined}
        className={cn(
          'relative group overflow-hidden rounded-2xl bg-gradient-to-br from-sapphire/40 to-navy/85 border border-steel/20 shadow-lg shadow-black/30 transition-all duration-300',
          gradient && 'before:absolute before:inset-0 before:bg-gradient-to-br before:from-violet/5 before:via-transparent before:to-teal/5 before:pointer-events-none',
          glowBorder && 'animate-border-glow',
          interactive && 'cursor-pointer',
          elevation === 1 && 'elevation-1',
          elevation === 2 && 'elevation-2',
          elevation === 3 && 'elevation-3',
          elevation === 4 && 'elevation-4',
          className
        )}
        {...props}
      >
        {/* Premium top edge glow */}
        <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-steel/50 to-transparent pointer-events-none" />
        <div className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-steel/10 to-transparent pointer-events-none" />

        {/* Left accent line on hover */}
        <div className="absolute left-0 top-1/3 bottom-1/3 w-0.5 bg-gradient-to-b from-violet/0 via-violet/40 to-violet/0 opacity-0 group-hover:opacity-100 transition-all duration-500 pointer-events-none" />

        {/* Hover overlay */}
        {hoverEffect && (
          <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 bg-gradient-to-br from-steel/[0.04] to-transparent pointer-events-none" />
        )}

        {children}
      </motion.div>
    );
  }
);

GlassCard.displayName = 'GlassCard';
