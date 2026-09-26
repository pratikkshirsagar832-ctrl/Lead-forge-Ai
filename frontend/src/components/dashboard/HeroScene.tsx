'use client';

import { motion } from 'framer-motion';
import { usePointer3D } from '@/hooks/usePointer3D';

// Illustrative buyer posts (roles only, no real people).
const CARDS = [
  { who: 'Founder, D2C brand', ago: '4 min ago', text: 'Can anyone recommend a video editor for our weekly reels?', urgent: true },
  { who: 'Marketing head, SaaS', ago: '18 min ago', text: 'Looking for an SEO agency for our relaunch. Recommendations?', urgent: false },
  { who: 'COO, fintech', ago: '1 h ago', text: 'We need a UI/UX designer for a 6-week project.', urgent: false },
];

/**
 * A stack of floating "buyer lead" cards in real CSS 3D (preserve-3d +
 * translateZ layers) that leans toward the cursor. Decorative only.
 */
export function HeroScene() {
  const p3d = usePointer3D(9);

  return (
    <div
      aria-hidden="true"
      className="stage-3d relative h-[300px] w-full select-none"
      {...p3d.handlers}
    >
      {/* Fixed three-quarter view; the inner layer adds the cursor lean
          (framer's inline transform would otherwise replace this one). */}
      <div className="preserve-3d absolute inset-0 [transform:rotateX(14deg)_rotateY(-18deg)]">
      <motion.div style={p3d.style} className="preserve-3d absolute inset-0">
        {CARDS.map((c, i) => (
          <div
            key={c.who}
            className="preserve-3d absolute left-1/2 top-1/2 w-[290px]"
            style={{
              transform: `translate3d(${-120 + i * 26}px, ${-128 + i * 74}px, ${-i * 70}px)`,
              zIndex: 3 - i,
            }}
          >
            <div
              className="float-3d motion-reduce:animate-none rounded-2xl p-4 bg-[linear-gradient(160deg,#145c54_0%,#0E3A33_45%,#0A2B26_100%)] shadow-[inset_0_1px_0_rgba(255,255,255,0.08),inset_0_0_0_1px_rgba(79,216,195,0.14),0_18px_40px_-16px_rgba(1,12,10,0.95)]"
              style={{ animationDelay: `${i * -2.2}s`, filter: `brightness(${1 - i * 0.18})` }}
            >
              <div className="flex items-center gap-2.5">
                <span className="tile-3d grid h-8 w-8 place-items-center rounded-lg text-xs font-bold text-steel">
                  {c.who.charAt(0)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs font-semibold text-offwhite">{c.who}</p>
                  <p className="text-[10px] text-ice/45">{c.ago}</p>
                </div>
                {c.urgent && (
                  <span className="rounded-md bg-brand-accent/15 px-1.5 py-0.5 text-[10px] font-bold text-brand-accent ring-1 ring-brand-accent/30">
                    Urgent
                  </span>
                )}
              </div>
              <p className="mt-2.5 text-[13px] leading-snug text-ice/80">{c.text}</p>
              <div className="mt-3 flex items-center gap-1.5 text-[10px] font-semibold text-steel">
                <span className="h-1.5 w-1.5 rounded-full bg-steel shadow-[0_0_8px_rgba(79,216,195,0.9)]" /> Genuine buyer
              </div>
            </div>
          </div>
        ))}
        {/* Soft floor shadow grounds the stack in space */}
        <div className="absolute left-1/2 top-[88%] h-10 w-[70%] -translate-x-1/2 rounded-[50%] bg-[#010c0a]/70 blur-2xl [transform:translateZ(-60px)]" />
      </motion.div>
      </div>
    </div>
  );
}
