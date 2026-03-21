export function FullPageLoader() {
  return (
    <div className="fixed inset-0 flex flex-col items-center justify-center bg-[#09090B] z-[9999]">
      <div className="relative">
        {/* Outer spinning ring */}
        <div className="w-16 h-16 border-4 border-indigo-500/20 border-t-indigo-500 rounded-full animate-spin"></div>
        {/* Inner pulsing core */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-8 h-8 bg-indigo-500/30 rounded-full animate-pulse"></div>
      </div>
      <h2 className="mt-6 text-xl font-bold tracking-tight text-white animate-pulse">
        LeadForge <span className="text-indigo-500">AI</span>
      </h2>
      <p className="mt-2 text-sm text-slate-400">Loading your workspace...</p>
    </div>
  );
}
