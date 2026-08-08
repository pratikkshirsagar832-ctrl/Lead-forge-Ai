'use client';

import dynamic from 'next/dynamic';

const ThreeScene = dynamic(
  () => import('./ThreeScene'),
  { ssr: false }
);

export function ThreeBackground() {
  return (
    <div className="fixed inset-0 z-0 pointer-events-none">
      <div className="absolute inset-0 bg-gradient-to-b from-navy/30 via-transparent to-navy/80 z-10" />
      <div className="absolute inset-0 bg-gradient-radial from-transparent via-navy/20 to-navy/60 z-10" />
      <div className="absolute inset-0 opacity-70">
        <ThreeScene />
      </div>
    </div>
  );
}
