/**
 * Fixed, non-interactive 3D scene behind the dashboard: brand-coloured light
 * blooms (mint from the top-left light source, a faint amber counter-light)
 * over a receding perspective grid floor. Pure CSS - no JS, no layout cost.
 */
export function AmbientBackdrop() {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-0 overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(1200px_700px_at_12%_-10%,rgba(79,216,195,0.13),transparent_60%)]" />
      <div className="absolute inset-0 bg-[radial-gradient(900px_600px_at_100%_110%,rgba(255,176,32,0.07),transparent_60%)]" />
      <div className="absolute inset-0 bg-[radial-gradient(700px_500px_at_60%_40%,rgba(13,79,74,0.35),transparent_70%)]" />
      <div className="scene-floor motion-reduce:animate-none opacity-70" />
      {/* Vignette keeps focus in the content column */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_55%,rgba(3,18,15,0.65))]" />
    </div>
  );
}
