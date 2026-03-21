'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { API_ROUTES } from '@/lib/constants';
import { GlassCard } from '@/components/shared/GlassCard';
import { Skeleton } from '@/components/shared/Skeleton';
import { Search, Users, Activity, Target } from 'lucide-react';
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
      color: 'text-indigo-400',
      bg: 'bg-indigo-500/10',
    },
    {
      title: 'Total Leads Found',
      value: stats?.total_leads || 0,
      icon: Users,
      color: 'text-blue-400',
      bg: 'bg-blue-500/10',
    },
    {
      title: 'Hot Leads',
      value: stats?.hot_leads || 0,
      icon: Target,
      color: 'text-rose-500',
      bg: 'bg-rose-500/10',
    },
    {
      title: 'Warm Leads',
      value: stats?.warm_leads || 0,
      icon: Activity,
      color: 'text-amber-500',
      bg: 'bg-amber-500/10',
    },
  ];

  if (error) {
    return (
      <div className="p-6 bg-slate-900 border border-slate-800 rounded-xl flex items-center justify-center">
        <p className="text-slate-400 text-sm">Unable to load stats right now.</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        {[1, 2, 3, 4].map((i) => (
          <GlassCard key={i} className="p-6">
            <div className="flex items-center justify-between">
              <Skeleton className="h-12 w-12 rounded-xl" />
              <div className="space-y-2 text-right">
                <Skeleton className="h-4 w-24 ml-auto" />
                <Skeleton className="h-8 w-16 ml-auto" />
              </div>
            </div>
          </GlassCard>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
      {cards.map((card, idx) => (
        <motion.div
          key={card.title}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: idx * 0.1 }}
        >
          <GlassCard hoverEffect className="p-6">
            <div className="flex items-center justify-between">
              <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${card.bg}`}>
                <card.icon className={`w-6 h-6 ${card.color}`} />
              </div>
              <div className="text-right">
                <p className="text-sm font-medium text-slate-400 mb-1">{card.title}</p>
                <p className="text-3xl font-bold text-white leading-none">
                  {card.value.toLocaleString()}
                </p>
              </div>
            </div>
          </GlassCard>
        </motion.div>
      ))}
    </div>
  );
}
