import { StatsCards } from '@/components/dashboard/StatsCards';
import { GlassCard } from '@/components/shared/GlassCard';
import { Rocket, Target, Users, TrendingUp, Sparkles } from 'lucide-react';
import Link from 'next/link';

export const metadata = {
  title: 'Dashboard | Hyperclients',
};

export default function DashboardOverview() {
  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="animate-fade-in-down">
        <h1 className="text-3xl font-bold text-offwhite tracking-tight" style={{ fontFamily: 'var(--font-heading)' }}>
          Dashboard
        </h1>
        <p className="text-ice/60 mt-2">Welcome to Hyperclients.</p>
      </div>

      <StatsCards />

      <div className="bento-grid lg:grid-cols-3">
        <GlassCard className="col-span-1 lg:col-span-2 p-0 overflow-hidden bg-gradient-to-br from-steel/30 via-ocean/20 to-navy/80 border border-ocean/30 elevation-2" delay={0.1}>
          <div className="p-8 relative">
            <div className="absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl from-violet/10 to-transparent rounded-full blur-3xl pointer-events-none" />
            <div className="relative z-10">
              <Sparkles className="w-5 h-5 text-amber mb-4" />
              <h2 className="text-2xl font-bold text-offwhite mb-3" style={{ fontFamily: 'var(--font-heading)' }}>
                Ready to find more clients?
              </h2>
              <p className="text-ice/70 mb-8 max-w-md leading-relaxed">
                Start a new search to find leads on Google Maps, analyze websites, and identify your hottest prospects in minutes.
              </p>
              <Link
                href="/dashboard/search"
                className="inline-flex items-center justify-center px-6 py-3 rounded-xl bg-gradient-to-r from-cta to-cta-light text-white font-semibold hover:opacity-90 transition-opacity duration-200"
              >
                <Rocket className="w-5 h-5 mr-2" />
                Start a Search
              </Link>
            </div>
          </div>
        </GlassCard>

        <div className="space-y-4">
          <GlassCard className="p-6" hoverEffect delay={0.15}>
            <div className="flex items-center gap-4 mb-4">
              <div className="p-3 rounded-xl bg-emerald-500/10 text-emerald-400">
                <Target className="w-6 h-6" />
              </div>
              <div>
                <h3 className="font-semibold text-offwhite" style={{ fontFamily: 'var(--font-heading)' }}>Hot Leads</h3>
                <p className="text-sm text-ice/60">Highest opportunity</p>
              </div>
            </div>
            <Link
              href="/dashboard/leads?category=hot"
              className="mt-4 block w-full text-center py-2.5 rounded-xl border border-steel/30 text-ice/80 font-medium hover:bg-steel/10 hover:text-offwhite hover:border-steel/50 transition-all duration-200"
            >
              View Hot Leads
            </Link>
          </GlassCard>

          <GlassCard className="p-6" hoverEffect delay={0.2}>
            <div className="flex items-center gap-4 mb-4">
              <div className="p-3 rounded-xl bg-amber-500/10 text-amber-400">
                <Users className="w-6 h-6" />
              </div>
              <div>
                <h3 className="font-semibold text-offwhite" style={{ fontFamily: 'var(--font-heading)' }}>Pipeline</h3>
                <p className="text-sm text-ice/60">Manage your contacts</p>
              </div>
            </div>
            <Link
              href="/dashboard/leads?status=new"
              className="mt-4 block w-full text-center py-2.5 rounded-xl border border-steel/30 text-ice/80 font-medium hover:bg-steel/10 hover:text-offwhite hover:border-steel/50 transition-all duration-200"
            >
              View Pipeline
            </Link>
          </GlassCard>

          <GlassCard className="p-6" hoverEffect delay={0.25}>
            <div className="flex items-center gap-4 mb-4">
              <div className="p-3 rounded-xl bg-violet-500/10 text-violet-400">
                <TrendingUp className="w-6 h-6" />
              </div>
              <div>
                <h3 className="font-semibold text-offwhite" style={{ fontFamily: 'var(--font-heading)' }}>Analytics</h3>
                <p className="text-sm text-ice/60">Track your growth</p>
              </div>
            </div>
            <Link
              href="/dashboard/history"
              className="mt-4 block w-full text-center py-2.5 rounded-xl border border-steel/30 text-ice/80 font-medium hover:bg-steel/10 hover:text-offwhite hover:border-steel/50 transition-all duration-200"
            >
              View History
            </Link>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
