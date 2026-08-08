'use client';

import { motion } from 'framer-motion';
import { ArrowRight, Zap, Target, Sparkles, BarChart3, Globe } from 'lucide-react';
import Link from 'next/link';
import { staggerContainer, fadeInUp } from '@/lib/animations';

export function Hero() {
  return (
    <div className="relative overflow-hidden bg-navy min-h-screen pt-[120px]">
      {/* Premium ambient light effects */}
      <div className="absolute top-1/4 -left-32 w-[500px] h-[500px] bg-violet/8 rounded-full blur-[120px] pointer-events-none animate-breathing" />
      <div className="absolute bottom-1/4 -right-32 w-[500px] h-[500px] bg-teal/6 rounded-full blur-[120px] pointer-events-none animate-float-delayed" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-steel/4 rounded-full blur-[150px] pointer-events-none" />

      {/* Grid overlay */}
      <div
        className="absolute inset-0 opacity-[0.03] pointer-events-none"
        style={{
          backgroundImage: `linear-gradient(rgba(59, 130, 196, 0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(59, 130, 196, 0.3) 1px, transparent 1px)`,
          backgroundSize: '60px 60px',
        }}
      />

      <div className="container relative z-10 mx-auto px-6 lg:px-8">
        <motion.div
          className="mx-auto max-w-4xl text-center"
          variants={staggerContainer}
          initial="hidden"
          animate="visible"
        >
          <motion.div variants={fadeInUp}>
            <span className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-gradient-to-r from-violet/20 to-steel/20 text-ice text-sm font-semibold mb-6 border border-violet/30 shadow-lg shadow-violet/5 group">
              <Sparkles className="w-4 h-4 text-violet-400" />
              AI-Powered Lead Engine
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            </span>
          </motion.div>

          <motion.h1
            variants={fadeInUp}
            className="text-5xl md:text-7xl lg:text-8xl font-extrabold tracking-tight text-offwhite mb-8 leading-[1.05]"
            style={{ fontFamily: 'var(--font-heading)' }}
          >
            Find High-intent Clients on{' '}
            <span className="gradient-text">
              Auto-pilot
            </span>
          </motion.h1>

          <motion.p
            variants={fadeInUp}
            className="text-xl md:text-2xl text-ice/60 mb-10 max-w-3xl mx-auto leading-relaxed"
          >
            Stop wasting hours manually searching. Hyperclients automatically extracts businesses,
            analyzes their websites, and drafts personalized pitches —{' '}
            <span className="text-ice/90 font-semibold">all in one click</span>.
          </motion.p>

          <motion.div
            variants={fadeInUp}
            className="flex flex-col sm:flex-row items-center justify-center gap-4"
          >
            <Link
              href="/login"
              className="group relative w-full sm:w-auto px-8 py-4 bg-gradient-to-r from-cta to-cta-light text-white rounded-xl font-semibold text-lg overflow-hidden transition-all duration-300"
            >
              <span className="absolute inset-0 bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
              <span className="relative flex items-center justify-center gap-2">
                Get Started Free
                <ArrowRight className="w-5 h-5 group-hover:translate-x-1.5 transition-transform duration-200" />
              </span>
              <span className="absolute -top-1 -right-1 w-3 h-3 bg-white/30 rounded-full blur-sm group-hover:bg-white/50 transition-all duration-500" />
            </Link>
            <Link
              href="#features"
              className="group w-full sm:w-auto px-8 py-4 bg-gradient-to-r from-ocean/40 to-navy/80 text-ice border border-steel/30 rounded-xl font-semibold text-lg hover:bg-ocean/60 hover:border-steel/50 active:scale-[0.97] transition-all duration-200 flex items-center justify-center gap-2"
            >
              How it works
              <BarChart3 className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
            </Link>
          </motion.div>

          {/* Trust indicators - premium conversion copy */}
          <motion.div
            variants={fadeInUp}
            className="flex flex-wrap items-center justify-center gap-8 mt-12 text-ice/40 text-sm"
          >
            <span className="flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-emerald-400/60" />
              No credit card required
            </span>
            <span className="flex items-center gap-1.5">
              <Target className="w-3.5 h-3.5 text-steel/60" />
              AI-powered analysis
            </span>
            <span className="flex items-center gap-1.5">
              <Globe className="w-3.5 h-3.5 text-violet-400/60" />
              Global coverage
            </span>
            <span className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-amber-400/60" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
              </svg>
              4.9/5 from 2,400+ users
            </span>
            <span className="flex items-center gap-1.5">
              <svg className="w-3.5 h-3.5 text-emerald-400/60" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              10,000+ leads generated
            </span>
          </motion.div>
        </motion.div>

        {/* Dashboard mockup */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.6, ease: [0.25, 0.1, 0.25, 1] }}
          className="mt-16 mx-auto max-w-6xl relative"
        >
          {/* Glow behind mockup */}
          <div className="absolute -inset-8 bg-gradient-to-r from-steel/5 via-violet/5 to-teal/5 rounded-[32px] blur-[40px] pointer-events-none" />

          <div className="relative rounded-2xl border border-steel/30 bg-navy/60 p-2 shadow-2xl shadow-black/40 backdrop-blur-sm overflow-hidden ring-1 ring-steel/10">
            <div className="rounded-xl border border-steel/20 bg-navy/90 p-4 shadow-sm overflow-hidden h-[400px] md:h-[600px] relative">
              {/* Mockup header */}
              <div className="flex items-center justify-between border-b border-steel/20 pb-4 mb-6">
                <div className="flex items-center gap-4">
                  <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet/40 to-steel/30 flex items-center justify-center shadow-lg shadow-violet/10">
                    <Target className="w-4 h-4 text-offwhite" />
                  </div>
                  <div className="h-5 w-40 bg-gradient-to-r from-steel/40 to-steel/20 rounded" />
                </div>
                <div className="flex gap-2">
                  <div className="h-8 w-24 bg-ocean/50 rounded-md border border-steel/10" />
                  <div className="h-8 w-8 bg-gradient-to-br from-violet/30 to-steel/20 rounded-md border border-steel/10" />
                </div>
              </div>

              {/* Mockup stat cards — real-looking metrics */}
              <div className="grid grid-cols-3 gap-3 mb-5">
                <div className="bg-gradient-to-br from-violet/20 to-steel/10 rounded-lg p-3.5 border border-steel/10">
                  <div className="text-[10px] text-violet-400/70 font-semibold uppercase tracking-wider mb-1">Leads Found</div>
                  <div className="flex items-baseline gap-1">
                    <span className="text-2xl font-extrabold text-offwhite">247</span>
                    <span className="text-[10px] text-emerald-400 font-medium">+12%</span>
                  </div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-navy/50 overflow-hidden">
                    <div className="h-full w-4/5 rounded-full bg-gradient-to-r from-violet to-steel" />
                  </div>
                </div>
                <div className="bg-gradient-to-br from-teal/20 to-emerald/10 rounded-lg p-3.5 border border-steel/10">
                  <div className="text-[10px] text-teal-400/70 font-semibold uppercase tracking-wider mb-1">Analyzed</div>
                  <div className="flex items-baseline gap-1">
                    <span className="text-2xl font-extrabold text-offwhite">189</span>
                    <span className="text-[10px] text-emerald-400 font-medium">89%</span>
                  </div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-navy/50 overflow-hidden">
                    <div className="h-full w-[76%] rounded-full bg-gradient-to-r from-teal to-emerald" />
                  </div>
                </div>
                <div className="bg-gradient-to-br from-rose/20 to-amber/10 rounded-lg p-3.5 border border-steel/10">
                  <div className="text-[10px] text-rose-400/70 font-semibold uppercase tracking-wider mb-1">Hot Leads</div>
                  <div className="flex items-baseline gap-1">
                    <span className="text-2xl font-extrabold text-offwhite">42</span>
                    <span className="text-[10px] text-amber-400 font-medium">Ready</span>
                  </div>
                  <div className="mt-1.5 h-1.5 rounded-full bg-navy/50 overflow-hidden">
                    <div className="h-full w-[42%] rounded-full bg-gradient-to-r from-rose to-amber" />
                  </div>
                </div>
              </div>

              {/* Search bar mockup */}
              <div className="flex items-center gap-3 bg-navy/60 rounded-xl px-4 py-3 mb-5 border border-steel/15">
                <svg className="w-4 h-4 text-ice/30 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
                </svg>
                <div className="h-4 flex-1 bg-steel/15 rounded" />
                <div className="h-7 w-20 rounded-lg bg-gradient-to-r from-steel to-violet/70" />
              </div>

              {/* Mockup table — real business names */}
              <div className="space-y-1">
                <div className="flex items-center gap-3 bg-steel/10 rounded-lg px-4 py-2.5 border border-steel/10">
                  <div className="text-[11px] font-semibold text-ice/40 uppercase tracking-wider w-[26%]">Business</div>
                  <div className="text-[11px] font-semibold text-ice/40 uppercase tracking-wider w-[18%]">Category</div>
                  <div className="text-[11px] font-semibold text-ice/40 uppercase tracking-wider w-[12%]">Rating</div>
                  <div className="text-[11px] font-semibold text-ice/40 uppercase tracking-wider w-[14%]">Website</div>
                  <div className="text-[11px] font-semibold text-ice/40 uppercase tracking-wider w-[12%]">Score</div>
                  <div className="text-[11px] font-semibold text-ice/40 uppercase tracking-wider w-[18%]">Status</div>
                </div>
                {[
                  { name: 'Premier Plumbing', cat: 'Plumber', rating: '4.8', web: 'Yes', score: '92', status: 'Hot', statusColor: 'from-rose-500/30 to-rose-500/10 border-rose-500/30 text-rose-300' },
                  { name: 'Elite Dental Care', cat: 'Dentist', rating: '4.6', web: 'Yes', score: '85', status: 'Hot', statusColor: 'from-rose-500/30 to-rose-500/10 border-rose-500/30 text-rose-300' },
                  { name: 'Bright Smiles Clinic', cat: 'Dentist', rating: '4.3', web: 'No', score: '64', status: 'Warm', statusColor: 'from-amber-500/20 to-amber-500/10 border-amber-500/20 text-amber-300' },
                  { name: 'Green Leaf Landscaping', cat: 'Landscaper', rating: '4.9', web: 'Yes', score: '78', status: 'Warm', statusColor: 'from-amber-500/20 to-amber-500/10 border-amber-500/20 text-amber-300' },
                ].map((row, i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-3 border-b border-steel/10 hover:bg-steel/[0.03] transition-colors rounded-lg">
                    <div className="flex items-center gap-2 w-[26%]">
                      <div className="w-5 h-5 rounded-full bg-gradient-to-br from-violet/30 to-steel/20 shrink-0" />
                      <span className="text-[13px] font-medium text-offwhite truncate">{row.name}</span>
                    </div>
                    <div className="w-[18%]">
                      <span className="text-[11px] text-ice/60 bg-steel/10 px-2 py-0.5 rounded-full">{row.cat}</span>
                    </div>
                    <div className="w-[12%] flex items-center gap-1">
                      <svg className="w-3 h-3 fill-amber-400 text-amber-400" viewBox="0 0 24 24"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" /></svg>
                      <span className="text-[12px] text-ice/80 font-medium">{row.rating}</span>
                    </div>
                    <div className="w-[14%]">
                      <span className={`text-[11px] font-medium ${row.web === 'Yes' ? 'text-emerald-400' : 'text-ice/30'}`}>{row.web}</span>
                    </div>
                    <div className="w-[12%]">
                      <span className={`text-[12px] font-bold ${Number(row.score) >= 70 ? 'text-emerald-400' : Number(row.score) >= 40 ? 'text-amber-400' : 'text-rose-400'}`}>{row.score}</span>
                    </div>
                    <div className="w-[18%]">
                      <span className={`text-[11px] font-semibold px-2.5 py-0.5 rounded-full bg-gradient-to-r ${row.statusColor} border`}>{row.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
