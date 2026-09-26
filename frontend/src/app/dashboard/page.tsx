import { StatsCards } from '@/components/dashboard/StatsCards';
import { GlassCard } from '@/components/shared/GlassCard';
import { HeroScene } from '@/components/dashboard/HeroScene';
import { Search, Target, Kanban, History, ArrowUpRight } from 'lucide-react';
import Link from 'next/link';

export const metadata = {
  title: 'Dashboard | Hyperclients',
};

const QUICK = [
  { href: '/dashboard/leads?category=hot', title: 'Hot leads', body: 'Your highest-intent buyers', icon: Target },
  { href: '/dashboard/pipeline', title: 'Sales pipeline', body: 'Move deals from new to won', icon: Kanban },
  { href: '/dashboard/history', title: 'Search history', body: 'Every search and its results', icon: History },
];

export default function DashboardOverview() {
  return (
    <div className="space-y-8">
      <header className="animate-fade-in-down">
        <p className="text-xs font-semibold text-steel/80 mb-2">Overview</p>
        <h1 className="text-4xl md:text-[2.75rem] font-bold text-offwhite tracking-[-0.02em] leading-[1.05]" style={{ fontFamily: 'var(--font-heading)' }}>
          Dashboard
        </h1>
        <p className="text-ice/60 mt-2 max-w-xl">Find people who need your service, reply first, and track every deal.</p>
      </header>

      <StatsCards />

      <div className="grid gap-5 lg:grid-cols-3">
        <GlassCard className="lg:col-span-2 p-0" delay={0.1}>
          <div className="grid items-center gap-2 md:grid-cols-[1.05fr_1fr]">
            <div className="relative z-10 p-8 md:p-10">
              <span className="tile-3d-amber inline-grid h-11 w-11 place-items-center rounded-xl text-navy">
                <Search className="h-5 w-5" strokeWidth={2.5} />
              </span>
              <h2 className="mt-6 text-3xl font-bold text-offwhite tracking-[-0.02em] leading-tight [text-wrap:balance]" style={{ fontFamily: 'var(--font-heading)' }}>
                Ready to find more clients?
              </h2>
              <p className="mt-3 max-w-md text-ice/70 leading-relaxed">
                Find genuine buyers on LinkedIn or local businesses on Google Maps. Newest buyers arrive first, while the search is still running.
              </p>
              <Link
                href="/dashboard/search"
                className="btn-3d-gold mt-8 inline-flex h-12 items-center gap-2 rounded-xl px-6 text-[15px]"
              >
                <Search className="h-4.5 w-4.5" strokeWidth={2.5} />
                Start a search
              </Link>
            </div>
            <div className="hidden md:block pr-6">
              <HeroScene />
            </div>
          </div>
        </GlassCard>

        <div className="grid gap-4">
          {QUICK.map(({ href, title, body, icon: Icon }, i) => (
            <Link key={href} href={href} className="group block rounded-2xl focus-visible:outline-2 focus-visible:outline-steel">
              <GlassCard className="p-5 h-full flex items-center" hoverEffect tilt={4} delay={0.15 + i * 0.05}>
                <div className="flex items-center gap-4">
                  <span className="tile-3d grid h-11 w-11 shrink-0 place-items-center rounded-xl text-steel transition-transform duration-300 group-hover:-translate-y-0.5">
                    <Icon className="h-5 w-5" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h3 className="font-semibold text-offwhite" style={{ fontFamily: 'var(--font-heading)' }}>{title}</h3>
                    <p className="text-sm text-ice/55">{body}</p>
                  </div>
                  <ArrowUpRight className="h-5 w-5 text-ice/30 transition-all duration-300 group-hover:text-steel group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                </div>
              </GlassCard>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
