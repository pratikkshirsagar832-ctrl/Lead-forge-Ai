'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { supabase } from '@/lib/supabase';
import api from '@/lib/api';
import { GlassCard } from '@/components/shared/GlassCard';
import { Footer } from '@/components/landing/Footer';
import Header from '@/components/landing/Header';
import { Check, Zap, Star, Building2, Loader2 } from 'lucide-react';

interface PlanData {
  id: string;
  name: string;
  price_monthly: number;
  linkedin_hq_leads_monthly: number;
  gmb_leads_monthly: number;
  searches_per_day: number;
  team_seats: number;
  sort_order: number;
}

const PLAN_ICONS: Record<string, typeof Zap> = {
  free: Zap,
  solo: Star,
  pro: Star,
  agency: Building2,
};

const PLAN_COLORS: Record<string, string> = {
  free: 'text-ice/60',
  solo: 'text-sky-400',
  pro: 'text-violet',
  agency: 'text-amber-400',
};

function getFeatures(plan: PlanData): string[] {
  const features: string[] = [
    `${plan.linkedin_hq_leads_monthly} HQ LinkedIn leads/mo`,
    `${plan.gmb_leads_monthly} GMB leads/mo`,
    'Leads management',
    'Website analysis',
  ];
  if (plan.id !== 'free') features.push('AI pitch generation');
  if (plan.id === 'pro' || plan.id === 'agency') {
    features.push('CSV export', 'Priority support', 'Advanced analytics');
  }
  if (plan.id === 'agency') {
    features.push('API access', 'Dedicated support');
  }
  if (plan.team_seats > 0) {
    features.push(`${plan.team_seats} team seats`);
  }
  return features;
}

export default function PricingPage() {
  const [session, setSession] = useState<any>(null);
  const [currentPlan, setCurrentPlan] = useState<string | null>(null);
  const [plans, setPlans] = useState<PlanData[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const init = async () => {
      const { data: { session: s } } = await supabase.auth.getSession();
      setSession(s);

      try {
        const plansResp = await api.get('/api/subscriptions/plans');
        setPlans(plansResp.data?.plans || []);
      } catch (e) {
        console.error('Failed to fetch plans:', e);
      }

      if (s) {
        try {
          const resp = await api.get('/api/auth/me');
          if (resp.data?.subscription) {
            setCurrentPlan(resp.data.subscription.plan_id);
          }
        } catch (e) {
          console.error('Failed to fetch current subscription:', e);
        }
      }
      setIsLoading(false);
    };
    init();
  }, []);

  if (isLoading) {
    return (
      <div className="min-h-screen flex flex-col bg-navy font-sans">
        <Header />
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-6 h-6 text-steel animate-spin" />
        </div>
        <Footer />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-navy font-sans relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-violet/20 via-navy to-navy pointer-events-none" />
      <Header />

      <section className="relative z-10 py-20 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-16">
            <h1 className="text-4xl md:text-5xl font-bold text-offwhite mb-4">
              Simple, transparent pricing
            </h1>
            <p className="text-lg text-ice/60 max-w-2xl mx-auto">
              Choose the plan that fits your lead generation needs. Upgrade anytime.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {plans.map((plan) => {
              const isCurrent = currentPlan === plan.id;
              const isPopular = plan.id === 'pro';
              const Icon = PLAN_ICONS[plan.id] || Zap;
              const color = PLAN_COLORS[plan.id] || 'text-ice/60';
              const features = getFeatures(plan);

              return (
                <GlassCard
                  key={plan.id}
                  className={`p-6 relative flex flex-col ${isPopular ? 'border-violet/50 ring-1 ring-violet/30' : ''}`}
                >
                  {isPopular && (
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-violet text-offwhite text-[11px] font-bold px-4 py-1 rounded-full">
                      Most Popular
                    </div>
                  )}

                  <div className="flex items-center gap-2 mb-4">
                    <div className={`p-2 rounded-lg bg-ocean/30 ${color}`}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <h3 className="text-lg font-bold text-offwhite">{plan.name}</h3>
                  </div>

                  <div className="mb-6">
                    <div className="flex items-baseline gap-1">
                      <span className="text-3xl font-extrabold text-offwhite">
                        {plan.price_monthly === 0 ? 'Free' : `$${Math.round(plan.price_monthly / 100)}`}
                      </span>
                      {plan.price_monthly > 0 && <span className="text-sm text-ice/40">/mo</span>}
                    </div>
                    {plan.id === 'free' && <p className="text-xs text-ice/40 mt-1">1 day trial</p>}
                  </div>

                  <div className="flex flex-col gap-2 mb-6 p-3 rounded-lg bg-ocean/20">
                    <div className="flex items-center gap-2">
                      <span className="text-xl font-bold text-steel">{plan.linkedin_hq_leads_monthly}</span>
                      <span className="text-xs text-ice/60">HQ LinkedIn Leads/mo</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xl font-bold text-steel">{plan.gmb_leads_monthly}</span>
                      <span className="text-xs text-ice/60">GMB Leads/mo</span>
                    </div>
                  </div>

                  <ul className="space-y-2.5 mb-8 flex-1">
                    {features.map((f, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-ice/70">
                        <Check className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                        {f}
                      </li>
                    ))}
                  </ul>

                  {isCurrent ? (
                    <div className="w-full py-2.5 rounded-lg bg-steel/20 text-steel text-sm font-semibold text-center">
                      Current Plan
                    </div>
                  ) : session ? (
                    <Link
                      href={`/dashboard/billing?upgrade=${plan.id}`}
                      className={`w-full py-2.5 rounded-lg text-center text-sm font-semibold transition-all ${isPopular ? 'bg-violet text-offwhite hover:opacity-90' : 'bg-ocean/30 text-ice hover:bg-ocean/50'}`}
                    >
                      {plan.price_monthly === 0 ? 'Downgrade' : 'Upgrade'}
                    </Link>
                  ) : (
                    <Link
                      href="/login"
                      className="w-full py-2.5 rounded-lg bg-steel text-offwhite text-sm font-semibold text-center hover:opacity-90 transition-opacity"
                    >
                      Get Started
                    </Link>
                  )}
                </GlassCard>
              );
            })}
          </div>
        </div>
      </section>
      <Footer />
    </div>
  );
}
