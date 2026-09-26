'use client';

import { forwardRef, type ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { motion, type HTMLMotionProps } from 'framer-motion';
import { usePointer3D } from '@/hooks/usePointer3D';

interface GlassCardProps extends HTMLMotionProps<'div'> {
  hoverEffect?: boolean;
  glowBorder?: boolean;
  children?: ReactNode;
  elevation?: 1 | 2 | 3 | 4;
  delay?: number;
  gradient?: boolean;
  interactive?: boolean;
  /** Tilt toward the cursor in 3D (degrees; `true` = 5). Off on touch / reduced motion. */
  tilt?: boolean | number;
}

/**
 * The dashboard's base surface: a lit 3D panel (top-edge highlight, mint rim,
 * teal-tinted depth shadow) with a cursor spotlight, optional 3D tilt and a
 * soft lift on hover.
 */
export const GlassCard = forwardRef<HTMLDivElement, GlassCardProps>(
  ({
    className,
    hoverEffect = false,
    glowBorder = false,
    elevation,
    delay = 0,
    gradient = false,
    interactive = false,
    tilt = false,
    children,
    style,
    onPointerMove,
    onPointerLeave,
    ...props
  }, ref) => {
    const maxDeg = tilt === true ? 5 : typeof tilt === 'number' ? tilt : 0;
    const p3d = usePointer3D(maxDeg);

    return (
      <motion.div
        ref={ref}
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.45, delay, ease: [0.25, 0.1, 0.25, 1] }}
        whileHover={hoverEffect ? { y: -3, transition: { type: 'spring', stiffness: 300, damping: 22 } } : undefined}
        onPointerMove={(e) => { p3d.handlers.onPointerMove(e); onPointerMove?.(e); }}
        onPointerLeave={(e) => { p3d.handlers.onPointerLeave(); onPointerLeave?.(e); }}
        style={{ ...(p3d.style || {}), ...(style || {}) }}
        className={cn(
          'surface-3d spotlight relative group overflow-hidden rounded-2xl',
          gradient && 'before:absolute before:inset-0 before:bg-gradient-to-br before:from-violet/5 before:via-transparent before:to-teal/5 before:pointer-events-none',
          glowBorder && 'animate-border-glow',
          interactive && 'cursor-pointer',
          elevation === 3 && 'elevation-3',
          elevation === 4 && 'elevation-4',
          className
        )}
        {...props}
      >
        {/* Lit top edge (light source: top-left) */}
        <div className="absolute inset-x-6 top-0 h-px bg-gradient-to-r from-transparent via-steel/45 to-transparent pointer-events-none" />
        {children}
      </motion.div>
    );
  }
);

GlassCard.displayName = 'GlassCard';
