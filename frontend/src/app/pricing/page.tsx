'use client';

export const dynamic = 'force-dynamic';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { supabase } from '@/lib/supabase';
import api from '@/lib/api';
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
      const { data: { session: s } } = await supabase.auth.getSession();
      setSession(s);

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
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-navy font-sans">
      <Header />
      <div className="flex-1 py-20 px-4">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h1 className="text-4xl font-bold text-offwhite mb-4">Simple, transparent pricing</h1>
            <p className="text-ice/60 text-lg">Choose the plan that fits your lead generation needs</p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            {plans.map((plan) => {
              const Icon = plan.icon;
              const isCurrent = plan.id === currentPlan;
              return (
                <GlassCard key={plan.id} className={`p-6 relative ${isCurrent ? 'ring-2 ring-violet' : ''} ${(plan as any).popular ? 'ring-2 ring-violet' : ''}`}>
                  {(plan as any).popular && (
                    <div className="absolute -top-3 left-1/2 -translate-x-1/2 bg-violet text-white text-xs font-bold px-3 py-1 rounded-full">
                      Most Popular
                    </div>
                  )}
                  <Icon className={`w-8 h-8 ${plan.color} mb-4`} />
                  <h3 className="text-xl font-bold text-offwhite">{plan.name}</h3>
                  <div className="mt-4 mb-6">
                    <span className="text-4xl font-bold text-offwhite">{plan.currency}{plan.price}</span>
                    <span className="text-ice/50">{plan.period}</span>
                  </div>
                  <ul className="space-y-3 mb-6">
                    {plan.features.map((feature, i) => (
                      <li key={i} className="flex items-center gap-2 text-sm text-ice/70">
                        <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                        {feature}
                      </li>
                    ))}
                  </ul>
                  <Link href={session ? '/dashboard/billing' : '/login'}>
                    <LoadingButton fullWidth variant={isCurrent ? 'outline' : 'default'}>
                      {isCurrent ? 'Current Plan' : session ? 'Upgrade' : 'Get Started'}
                      {!isCurrent && <ArrowRight className="w-4 h-4 ml-2" />}
                    </LoadingButton>
                  </Link>
                </GlassCard>
              );
            })}
          </div>
        </div>
      </div>
      <Footer />
    </div>
  );
}
