'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { API_ROUTES } from '@/lib/constants';
import { GlassCard } from '@/components/shared/GlassCard';
import { Skeleton } from '@/components/shared/Skeleton';
import { Search, Users, Flame, TrendingUp } from 'lucide-react';
import { motion } from 'framer-motion';

interface DashboardStats {
  total_searches: number;
  total_leads: number;
  hot_leads: number;
  warm_leads: number;
}

export function StatsCards() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let mounted = true;
    const fetchStats = async () => {
      try {
        const { data } = await api.get(API_ROUTES.dashboard.stats);
        if (mounted) setStats(data);
      } catch (err) {
        console.error('Failed to fetch stats', err);
        if (mounted) setError(true);
      } finally {
        if (mounted) setIsLoading(false);
      }
    };
    fetchStats();
    return () => { mounted = false; };
  }, []);

  const cards = [
    { title: 'Searches', value: stats?.total_searches || 0, icon: Search, tile: 'tile-3d text-steel' },
    { title: 'Leads found', value: stats?.total_leads || 0, icon: Users, tile: 'tile-3d text-steel' },
    { title: 'Hot leads', value: stats?.hot_leads || 0, icon: Flame, tile: 'tile-3d-amber text-navy' },
    { title: 'Warm leads', value: stats?.warm_leads || 0, icon: TrendingUp, tile: 'tile-3d text-brand-accent' },
  ];

  if (error) {
    return (
      <div className="surface-3d rounded-2xl px-6 py-5 flex items-center gap-4">
        <span className="tile-3d grid h-10 w-10 place-items-center rounded-xl text-steel"><TrendingUp className="h-5 w-5" /></span>
        <div>
          <p className="text-sm font-semibold text-offwhite">Stats are unavailable right now</p>
          <p className="text-xs text-ice/50">Your searches and leads are safe. Refresh in a moment to see the numbers.</p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 md:gap-5">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="surface-3d rounded-2xl p-5">
            <Skeleton className="h-11 w-11 rounded-xl bg-steel/10" />
            <Skeleton className="mt-5 h-8 w-16 bg-steel/10" />
            <Skeleton className="mt-2 h-3 w-24 bg-steel/10" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 md:gap-5">
      {cards.map((card, idx) => (
        <GlassCard key={card.title} hoverEffect tilt={6} delay={idx * 0.06} className="p-5">
          <span className={`${card.tile} grid h-11 w-11 place-items-center rounded-xl`}>
            <card.icon className="h-5 w-5" />
          </span>
          <motion.p
            className="mt-5 text-3xl md:text-4xl font-bold text-offwhite leading-none tracking-[-0.02em] tabular"
            style={{ fontFamily: 'var(--font-heading)' }}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.15 + idx * 0.08, ease: [0.25, 0.1, 0.25, 1] }}
          >
            {card.value.toLocaleString()}
          </motion.p>
          <p className="mt-2 text-xs font-medium text-ice/50">{card.title}</p>
        </GlassCard>
      ))}
    </div>
  );
}
