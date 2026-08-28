'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import api, { getLocalToken } from '@/lib/api';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { Footer } from '@/components/landing/Footer';
import Header from '@/components/landing/Header';
import { Check, Zap, Star, Building2, ArrowRight, Loader2 } from 'lucide-react';

const plans = [
  {
    id: 'free', name: 'Free', price: 0, currency: '$', period: '/mo',
    linkedinLeads: '3', gmbLeads: '30', trial: '1 day trial',
    features: ['3 searches', 'Leads management', 'Website analysis', 'Basic lead data'],
    icon: Zap, color: 'text-ice/60',
  },
  {
    id: 'solo', name: 'Solo', price: 19, currency: '$', period: '/mo',
    linkedinLeads: '20', gmbLeads: '200', trial: null,
    features: ['5 searches', 'Leads management', 'Website analysis', 'AI pitch generation'],
    icon: Star, color: 'text-sky-400', popular: false,
  },
  {
    id: 'pro', name: 'Pro', price: 99, currency: '$', period: '/mo',
    linkedinLeads: '120', gmbLeads: '1500', trial: null, seats: '2 team seats included',
    features: ['15 searches', 'Leads management', 'CSV export', 'Priority support', 'Everything in Solo', 'Advanced analytics'],
    icon: Star, color: 'text-violet', popular: true,
  },
  {
    id: 'agency', name: 'Agency', price: 299, currency: '$', period: '/mo',
    linkedinLeads: '400', gmbLeads: '6000', trial: null, seats: '10 team seats included',
    features: ['50 searches', 'Leads management', 'CSV export', 'Team access', 'Everything in Pro', 'API access', 'Dedicated support'],
    icon: Building2, color: 'text-amber-400',
  },
];

export default function PricingPage() {
  const [session, setSession] = useState<any>(null);
  const [currentPlan, setCurrentPlan] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const init = async () => {
      const token = getLocalToken();
      setSession(token ? { access_token: token } : null);

      if (token) {
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
              const Icon = plan.icon;

              return (
                <GlassCard
                  key={plan.id}
                  className={`p-6 relative flex flex-col ${plan.popular ? 'border-violet/50 ring-1 ring-violet/30' : ''}`}
                >
                  {plan.popular && (
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-violet text-offwhite text-[11px] font-bold px-4 py-1 rounded-full">
                      Most Popular
                    </div>
                  )}

                  <div className="flex items-center gap-2 mb-4">
                    <div className={`p-2 rounded-lg bg-ocean/30 ${plan.color}`}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <h3 className="text-lg font-bold text-offwhite">{plan.name}</h3>
                  </div>

                  <div className="mb-6">
                    <div className="flex items-baseline gap-1">
                      <span className="text-3xl font-extrabold text-offwhite">
                        {plan.price === 0 ? 'Free' : `${plan.currency}${plan.price}`}
                      </span>
                      {plan.price > 0 && <span className="text-sm text-ice/40">{plan.period}</span>}
                    </div>
                    {plan.trial && <p className="text-xs text-ice/40 mt-1">{plan.trial}</p>}
                    {!plan.trial && plan.seats && <p className="text-xs text-steel font-semibold mt-1">{plan.seats}</p>}
                  </div>

                  <div className="flex flex-col gap-2 mb-6 p-3 rounded-lg bg-ocean/20">
                    <div className="flex items-center gap-2">
                      <span className="text-xl font-bold text-steel">{plan.linkedinLeads}</span>
                      <span className="text-xs text-ice/60">HQ LinkedIn Leads</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xl font-bold text-steel">{plan.gmbLeads}</span>
                      <span className="text-xs text-ice/60">GMB Leads</span>
                    </div>
                  </div>

                  <ul className="space-y-2.5 mb-8 flex-1">
                    {plan.features.map((f, i) => (
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
                      className={`w-full py-2.5 rounded-lg text-center text-sm font-semibold transition-all ${plan.popular ? 'bg-violet text-offwhite hover:opacity-90' : 'bg-ocean/30 text-ice hover:bg-ocean/50'}`}
                    >
                      {plan.price === 0 ? 'Downgrade' : 'Upgrade'}
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
