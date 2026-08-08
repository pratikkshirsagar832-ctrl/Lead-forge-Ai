export function BlogBackground() {
  return (
    <div className="fixed inset-0 z-0 pointer-events-none overflow-hidden" aria-hidden="true">
      {/* Premium ambient light effects (matches landing) */}
      <div className="absolute top-[15%] -left-32 w-[500px] h-[500px] bg-violet/8 rounded-full blur-[120px] animate-breathing" />
      <div className="absolute bottom-[15%] -right-32 w-[500px] h-[500px] bg-teal/6 rounded-full blur-[120px] animate-float-delayed" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-steel/4 rounded-full blur-[150px]" />

      {/* Grid overlay */}
      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `linear-gradient(rgba(59, 130, 196, 0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(59, 130, 196, 0.3) 1px, transparent 1px)`,
          backgroundSize: '60px 60px',
        }}
      />
    </div>
  );
}