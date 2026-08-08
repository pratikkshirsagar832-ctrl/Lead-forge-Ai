'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { API_ROUTES } from '@/lib/constants';
import { GlassCard } from '@/components/shared/GlassCard';
import { Skeleton } from '@/components/shared/Skeleton';
import { Search, Users, Flame, TrendingUp, Sparkles } from 'lucide-react';
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
    {
      title: 'Total Searches',
      value: stats?.total_searches || 0,
      icon: Search,
      gradient: 'from-steel/20 via-ocean/15 to-transparent',
      iconBg: 'bg-steel/20',
      iconColor: 'text-steel',
    },
    {
      title: 'Total Leads Found',
      value: stats?.total_leads || 0,
      icon: Users,
      gradient: 'from-violet/15 via-steel/10 to-transparent',
      iconBg: 'bg-violet/20',
      iconColor: 'text-violet-400',
    },
    {
      title: 'Hot Leads',
      value: stats?.hot_leads || 0,
      icon: Flame,
      gradient: 'from-rose-500/12 via-rose-500/5 to-transparent',
      iconBg: 'bg-rose-500/20',
      iconColor: 'text-rose-400',
    },
    {
      title: 'Warm Leads',
      value: stats?.warm_leads || 0,
      icon: TrendingUp,
      gradient: 'from-amber-500/12 via-amber-500/5 to-transparent',
      iconBg: 'bg-amber-500/20',
      iconColor: 'text-amber-400',
    },
  ];

  if (error) {
    return (
      <div className="p-6 bg-ocean/20 border border-steel/20 rounded-2xl flex items-center justify-center">
        <p className="text-ice/50 text-sm">Unable to load stats right now.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="rounded-2xl bg-gradient-to-br from-sapphire/30 to-navy/85 border border-steel/15 p-6">
            <div className="flex items-center justify-between">
              <Skeleton className="h-12 w-12 rounded-xl bg-steel/10" />
              <div className="space-y-2 text-right">
                <Skeleton className="h-3.5 w-24 ml-auto bg-steel/10" />
                <Skeleton className="h-8 w-16 ml-auto bg-steel/10" />
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
      {cards.map((card, idx) => (
        <motion.div
          key={card.title}
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: idx * 0.1, ease: [0.25, 0.1, 0.25, 1] }}
        >
          <GlassCard hoverEffect delay={idx * 0.08} className="relative overflow-hidden">
            <div className={`absolute inset-0 bg-gradient-to-br ${card.gradient} pointer-events-none`} />
            <div className="absolute left-0 top-0 bottom-0 w-0.5 bg-gradient-to-b from-transparent via-steel/30 to-transparent opacity-60" />

            {/* Premium corner accent */}
            <div className="absolute top-0 right-0 w-16 h-16">
              <div className="absolute top-0 right-0 w-8 h-8 bg-gradient-to-bl from-steel/5 to-transparent rounded-bl-full" />
            </div>

            <div className="relative p-6">
              <div className="flex items-center justify-between">
                <div className={`w-12 h-12 rounded-xl ${card.iconBg} flex items-center justify-center ring-1 ring-white/5 backdrop-blur-sm`}>
                  <card.icon className={`w-5.5 h-5.5 ${card.iconColor}`} />
                </div>
                <div className="text-right">
                  <p className="text-xs font-semibold text-ice/40 uppercase tracking-widest mb-1.5">{card.title}</p>
                  <motion.p
                    className="text-3xl font-extrabold text-offwhite leading-none tracking-tight"
                    initial={{ opacity: 0, scale: 0.5 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ duration: 0.5, delay: 0.2 + idx * 0.1, ease: [0.25, 0.1, 0.25, 1] }}
                  >
                    {card.value.toLocaleString()}
                  </motion.p>
                </div>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      ))}
    </div>
  );
}
