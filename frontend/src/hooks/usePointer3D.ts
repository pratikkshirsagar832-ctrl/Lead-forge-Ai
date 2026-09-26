'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useMotionValue, useSpring, type MotionValue } from 'framer-motion';

/**
 * Pointer-driven 3D: spring-smoothed rotateX/rotateY toward the cursor plus
 * --mx/--my CSS variables for `.spotlight`. Tilt switches itself off on touch
 * devices and for users who prefer reduced motion (the spotlight still works
 * on hover-capable pointers).
 */
export function usePointer3D(maxDeg = 6) {
  const [enabled, setEnabled] = useState(false);
  const rx = useMotionValue(0);
  const ry = useMotionValue(0);
  const rotateX: MotionValue<number> = useSpring(rx, { stiffness: 220, damping: 22, mass: 0.6 });
  const rotateY: MotionValue<number> = useSpring(ry, { stiffness: 220, damping: 22, mass: 0.6 });
  const frame = useRef<number | null>(null);

  useEffect(() => {
    try {
      const fine = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
      const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      setEnabled(fine && !calm && maxDeg > 0);
    } catch {
      setEnabled(false);
    }
  }, [maxDeg]);

  const onPointerMove = useCallback((e: React.PointerEvent<HTMLElement>) => {
    const el = e.currentTarget;
    const { clientX, clientY } = e;
    if (frame.current !== null) return;
    frame.current = requestAnimationFrame(() => {
      frame.current = null;
      const r = el.getBoundingClientRect();
      const x = clientX - r.left;
      const y = clientY - r.top;
      el.style.setProperty('--mx', `${x}px`);
      el.style.setProperty('--my', `${y}px`);
      if (enabled) {
        ry.set(((x / r.width) - 0.5) * 2 * maxDeg);
        rx.set(-((y / r.height) - 0.5) * 2 * maxDeg);
      }
    });
  }, [enabled, maxDeg, rx, ry]);

  const onPointerLeave = useCallback(() => {
    rx.set(0);
    ry.set(0);
  }, [rx, ry]);

  return {
    enabled,
    handlers: { onPointerMove, onPointerLeave },
    style: enabled ? { rotateX, rotateY, transformPerspective: 1100 } : undefined,
  };
}
