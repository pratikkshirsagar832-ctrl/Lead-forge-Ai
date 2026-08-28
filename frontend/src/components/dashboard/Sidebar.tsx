'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import Image from 'next/image';
import { cn } from '@/lib/utils';
import { supabase } from '@/lib/supabase';
import api from '@/lib/api';
import {
  LayoutDashboard,
  Search,
  Users,
  History,
  Download,
  Settings,
  Target,
  X,
  CreditCard,
  LogOut,
  User,
  Zap,
  Sparkles,
  ArrowUpRight,
  Kanban,
  UsersRound,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { ThemeToggle } from '@/components/ThemeToggle';

const navItems = [
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'New Search', href: '/dashboard/search', icon: Search },
  { name: 'Leads', href: '/dashboard/leads', icon: Users },
  { name: 'Lead Manager', href: '/dashboard/pipeline', icon: Kanban },
  { name: 'Team', href: '/dashboard/team', icon: UsersRound },
  { name: 'Hyper Agent', href: '/dashboard/hyper-agent/chat', icon: Zap },
  { name: 'History', href: '/dashboard/history', icon: History },
  { name: 'Export', href: '/dashboard/export', icon: Download },
  { name: 'Billing', href: '/dashboard/billing', icon: CreditCard },
  { name: 'Settings', href: '/dashboard/settings', icon: Settings },
];

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const [user, setUser] = useState<any>(null);
  const [subscription, setSubscription] = useState<any>(null);

  useEffect(() => {
    const fetchUser = async () => {
      const { data: { user: u } } = await supabase.auth.getUser();
      if (u) setUser(u);

      try {
        const resp = await api.get('/api/auth/me');
        if (resp.data?.subscription) {
          setSubscription(resp.data.subscription);
        }
      } catch (e) {
        console.error('Failed to fetch subscription:', e);
      }
    };
    fetchUser();
  }, []);

  const handleLogout = async () => {
    await supabase.auth.signOut();
    window.location.href = '/login';
  };

  const planBadge = subscription?.plan_name || 'Free';
  const planColor = planBadge === 'Pro' ? 'bg-violet/20 text-violet border-violet/30'
    : planBadge === 'Agency' ? 'text-amber-400 bg-amber-500/10 border-amber-500/30'
    : planBadge === 'Solo' ? 'text-sky-400 bg-sky-500/10 border-sky-500/30'
    : 'text-ice/50 bg-ocean/20 border-steel/20';

  const remaining = subscription?.remaining_searches ?? 1;
  const searchesPerDay = subscription?.searches_per_day ?? 1;
  const leadsRemaining = subscription?.remaining_leads ?? 0;
  const leadsPerDay = subscription?.leads_per_day ?? 30;

  return (
    <>
      {open && (
        <div className="fixed inset-0 bg-navy/80 backdrop-blur-sm z-20 lg:hidden" onClick={onClose} />
      )}
      <div className={cn(
        'w-64 bg-gradient-to-b from-navy via-sapphire/20 to-navy flex flex-col h-screen fixed top-0 left-0 border-r border-steel/20 z-30 transition-transform duration-300 backdrop-blur-sm',
        'lg:translate-x-0',
        open ? 'translate-x-0' : '-translate-x-full'
      )}>
        <div className="absolute top-0 left-4 right-4 h-px bg-gradient-to-r from-transparent via-steel/30 to-transparent pointer-events-none" />

        <div className="p-6 flex items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2 group" onClick={onClose}>
            <div className="bg-gradient-to-br from-primary to-brand-accent rounded-lg p-1">
              <Image src="/hyperclients-icon.png" alt="Hyperclients" width={40} height={40} className="object-contain" />
            </div>
            <span className="font-bold text-xl tracking-tight text-offwhite" style={{ fontFamily: 'var(--font-heading)' }}>Hyperclients</span>
          </Link>
          <button onClick={onClose} className="lg:hidden text-ice/40 hover:text-ice">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-4 mb-4">
          <div className={cn('px-3 py-1.5 rounded-lg text-xs font-semibold border', planColor)}>
            {planBadge} Plan
          </div>
          <div className="mt-2 text-xs text-ice/40">
            <p>Searches: {remaining}/{searchesPerDay}</p>
            <p>Leads: {leadsRemaining}/{leadsPerDay}</p>
          </div>
        </div>

        <nav className="flex-1 px-3 space-y-1 overflow-y-auto">
          {navItems.map((item) => {
            const isActive = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href));
            return (
              <Link
                key={item.name}
                href={item.href}
                onClick={onClose}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-steel/20 text-offwhite'
                    : 'text-ice/50 hover:text-ice hover:bg-ocean/20'
                )}
              >
                <item.icon className="w-4 h-4" />
                {item.name}
              </Link>
            );
          })}
        </nav>

        <div className="p-4 border-t border-steel/20">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded-full bg-steel/20 flex items-center justify-center">
              <User className="w-4 h-4 text-steel" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-offwhite truncate">{user?.email || 'Guest'}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-ice/40 hover:text-ice hover:bg-ocean/20 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              Logout
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
