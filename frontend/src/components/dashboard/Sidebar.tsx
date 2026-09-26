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
  X,
  CreditCard,
  LogOut,
  User,
  Sparkles,
  ArrowUpRight,
  Kanban,
  UsersRound,
  Code2,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { ThemeToggle } from '@/components/ThemeToggle';

const navItems = [
  { name: 'Dashboard', href: '/dashboard', icon: LayoutDashboard },
  { name: 'New Search', href: '/dashboard/search', icon: Search },
  { name: 'Leads', href: '/dashboard/leads', icon: Users },
  { name: 'Sales Manager', href: '/dashboard/pipeline', icon: Kanban },
  { name: 'Team', href: '/dashboard/team', icon: UsersRound },
  { name: 'History', href: '/dashboard/history', icon: History },
  { name: 'Export', href: '/dashboard/export', icon: Download },
  { name: 'Billing', href: '/dashboard/billing', icon: CreditCard },
  { name: 'Developer API', href: '/dashboard/developer', icon: Code2 },
  { name: 'Settings', href: '/dashboard/settings', icon: Settings },
];

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const [user, setUser] = useState<any>(null);
  const [subscription, setSubscription] = useState<any>(null);

  useEffect(() => {
    const fetchUser = async () => {
      // Local session read (no network): the API calls below verify it.
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.user) setUser(session.user);

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
    // scope 'local': log out THIS device only. The default ('global') revokes
    // every session of the account, logging out teammates / other devices
    // that share the same agency login.
    try {
      await supabase.auth.signOut({ scope: 'local' });
    } finally {
      window.location.href = '/login';
    }
  };

  const planBadge = subscription?.plan_name || 'Free';
  const planColor = planBadge === 'Pro' ? 'bg-violet/20 text-violet border-violet/30'
    : planBadge === 'Agency' ? 'text-amber-400 bg-amber-500/10 border-amber-500/30'
    : planBadge === 'Solo' ? 'text-steel bg-steel/10 border-steel/30'
    : 'text-ice/50 bg-ocean/20 border-steel/20';

  const remaining = subscription?.remaining_searches ?? 1;
  const searchesPerDay = subscription?.searches_per_day ?? 1;
  const linkedinUsed = subscription?.linkedin_hq_leads_used ?? 0;
  const linkedinMonthly = subscription?.linkedin_hq_leads_monthly ?? 0;
  const gmbUsed = subscription?.gmb_leads_used ?? 0;
  const gmbMonthly = subscription?.gmb_leads_monthly ?? 0;

  return (
    <>
      {open && (
        <div className="fixed inset-0 bg-navy/80 backdrop-blur-sm z-20 lg:hidden" onClick={onClose} />
      )}
      <div className={cn(
        'w-64 flex flex-col h-[100dvh] fixed top-0 left-0 z-30 transition-transform duration-300',
        'bg-[linear-gradient(180deg,rgba(10,43,38,0.92),rgba(6,35,31,0.96))] backdrop-blur-xl',
        'shadow-[inset_-1px_0_0_rgba(79,216,195,0.10),12px_0_40px_-20px_rgba(1,12,10,0.9)]',
        'lg:translate-x-0',
        open ? 'translate-x-0' : '-translate-x-full'
      )}>

        <div className="p-6 flex items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2 group" onClick={onClose}>
            <div className="rounded-xl p-1.5 bg-gradient-to-br from-[#16756B] to-[#0D4F4A] shadow-[inset_0_1px_0_rgba(79,216,195,0.4),0_3px_0_#04201C,0_10px_20px_-8px_rgba(13,79,74,0.9)] transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:rotate-[-4deg]">
              <Image src="/hyperclients-icon.png" alt="Hyperclients" width={32} height={32} className="object-contain" />
            </div>
            <span className="font-bold text-xl tracking-tight text-offwhite" style={{ fontFamily: 'var(--font-heading)' }}>Hyperclients</span>
          </Link>
          <button onClick={onClose} className="lg:hidden p-1.5 rounded-lg hover:bg-ocean/50 text-ice/60 hover:text-offwhite transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        <nav className="flex-1 px-3 py-2 space-y-1 overflow-y-auto" aria-label="Dashboard">
          {navItems.map((item, idx) => {
            const isActive = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href));
            return (
              <Link
                key={item.name}
                href={item.href}
                onClick={onClose}
                aria-current={isActive ? 'page' : undefined}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors duration-200 group relative focus-visible:outline-2 focus-visible:outline-steel',
                  isActive ? 'text-offwhite' : 'text-ice/55 hover:text-offwhite'
                )}
              >
                {isActive ? (
                  // One raised, lit pill that glides between items.
                  <motion.span
                    layoutId="nav-active"
                    transition={{ type: 'spring', stiffness: 380, damping: 32 }}
                    className="absolute inset-0 rounded-xl key-3d is-active"
                  >
                    <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-steel shadow-[0_0_12px_rgba(79,216,195,0.9)]" />
                  </motion.span>
                ) : (
                  <span className="absolute inset-0 rounded-xl bg-white/[0.03] opacity-0 group-hover:opacity-100 transition-opacity" />
                )}
                <item.icon className={cn('relative w-[18px] h-[18px] shrink-0 transition-all duration-200', isActive ? 'text-steel drop-shadow-[0_0_6px_rgba(79,216,195,0.6)]' : 'text-ice/40 group-hover:text-ice/75 group-hover:-translate-y-px')} />
                <span className="relative">{item.name}</span>
              </Link>
            );
          })}
        </nav>

        {/* User section */}
        <div className="m-3 p-3 rounded-2xl surface-3d space-y-3">
          <div className="flex items-center gap-3 px-2">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[#16756B] to-[#0D4F4A] flex items-center justify-center text-sm font-bold text-steel shrink-0 overflow-hidden shadow-[inset_0_1px_0_rgba(79,216,195,0.35),0_2px_0_#04201C]">
              {/* Local initial avatar — never send the account email to a third
                  party (ui-avatars.com) on every dashboard load. */}
              <span className="select-none">
                {(user?.name || user?.email || 'U').trim().charAt(0).toUpperCase()}
              </span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-offwhite truncate">{user?.email || 'User'}</p>
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className={cn('text-[10px] font-medium px-1.5 py-0.5 rounded border', planColor)}>
                  {planBadge === 'Free' && subscription?.is_trial_expired ? 'Trial Expired' : planBadge}
                </span>
                {planBadge === 'Free' && (
                  <Link
                    href="/dashboard/billing"
                    className="text-[10px] font-semibold text-accent-cyan hover:text-accent-cyan/80 transition-colors flex items-center gap-0.5"
                  >
                    Upgrade
                    <ArrowUpRight className="w-3 h-3" />
                  </Link>
                )}
              </div>
            </div>
          </div>

          {searchesPerDay > 0 && (
            <div className="px-2">
              <div className="flex justify-between text-[10px] text-ice/40 mb-1">
                <span>Searches used (monthly)</span>
                <span>{remaining}/{searchesPerDay}</span>
              </div>
              <div className="h-1.5 rounded-full well-3d overflow-hidden">
                <motion.div
                  className={cn('h-full rounded-full', remaining > 0 ? 'bg-gradient-to-r from-steel to-brand-accent' : 'bg-rose-500')}
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(100, ((searchesPerDay - remaining) / searchesPerDay) * 100)}%` }}
                  transition={{ duration: 0.8, ease: 'easeOut' }}
                />
              </div>
            </div>
          )}
          {linkedinMonthly > 0 && (
            <div className="px-2">
              <div className="flex justify-between text-[10px] text-ice/40 mb-1">
                <span>LinkedIn leads used</span>
                <span>{linkedinUsed}/{linkedinMonthly}</span>
              </div>
              <div className="h-1.5 rounded-full well-3d overflow-hidden">
                <motion.div
                  className={cn('h-full rounded-full', linkedinUsed < linkedinMonthly ? 'bg-gradient-to-r from-steel to-teal' : 'bg-rose-500')}
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(100, linkedinMonthly > 0 ? (linkedinUsed / linkedinMonthly) * 100 : 0)}%` }}
                  transition={{ duration: 0.8, ease: 'easeOut' }}
                />
              </div>
            </div>
          )}
          {gmbMonthly > 0 && (
            <div className="px-2">
              <div className="flex justify-between text-[10px] text-ice/40 mb-1">
                <span>GMB leads used</span>
                <span>{gmbUsed}/{gmbMonthly}</span>
              </div>
              <div className="h-1.5 rounded-full well-3d overflow-hidden">
                <motion.div
                  className={cn('h-full rounded-full', gmbUsed < gmbMonthly ? 'bg-gradient-to-r from-brand-accent to-brand-accent-light' : 'bg-rose-500')}
                  initial={{ width: 0 }}
                  animate={{ width: `${Math.min(100, gmbMonthly > 0 ? (gmbUsed / gmbMonthly) * 100 : 0)}%` }}
                  transition={{ duration: 0.8, ease: 'easeOut' }}
                />
              </div>
            </div>
          )}

          <div className="flex items-center justify-between px-2 pt-1">
            <button
              onClick={handleLogout}
              className="flex items-center gap-1.5 text-[11px] text-ice/40 hover:text-rose-400 transition-colors group"
            >
              <LogOut className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
              Sign Out
            </button>
            <ThemeToggle />
          </div>
        </div>
      </div>
    </>
  );
}
