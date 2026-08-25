'use client';

export const dynamic = 'force-dynamic';

import { Suspense, useEffect, useState, useRef, type ElementType } from 'react';
import { useSearchParams } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import api from '@/lib/api';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import type { SubscriptionInfo, Plan } from '@/lib/types';
import {
  CreditCard, Check, ArrowLeft, Zap, Star, Building2,
  Loader2, AlertCircle, ExternalLink, Clock,
} from 'lucide-react';
import Link from 'next/link';

const PLAN_META: Record<string, { name: string; icon: ElementType; color: string; bg: string }> = {
  free: { name: 'Free', icon: Zap, color: 'text-ice/60', bg: 'bg-ocean/20' },
  solo: { name: 'Solo', icon: Star, color: 'text-sky-400', bg: 'bg-sky-500/10' },
  pro: { name: 'Pro', icon: Star, color: 'text-violet', bg: 'bg-violet/20' },
  agency: { name: 'Agency', icon: Building2, color: 'text-amber-400', bg: 'bg-amber-500/10' },
};

function BillingContent() {
  const searchParams = useSearchParams();
  const [subscription, setSubscription] = useState<SubscriptionInfo | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const upgradeRequested = useRef<string | null>(null);

  const loadData = async () => {
    try {
      const [subResp, plansResp] = await Promise.all([
        api.get('/api/subscriptions/current'),
        api.get('/api/subscriptions/plans'),
      ]);
      setSubscription(subResp.data);
      setPlans(plansResp.data?.plans || []);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to load billing data');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    const upgradeParam = searchParams.get('upgrade');
    if (upgradeParam && plans.length > 0 && upgradeParam !== upgradeRequested.current) {
      const plan = plans.find((p) => p.id === upgradeParam);
      if (plan && plan.id !== subscription?.plan_id) {
        upgradeRequested.current = upgradeParam;
        handleUpgrade(plan);
      }
    }
  }, [searchParams, plans, subscription?.plan_id]);

  interface RazorpayResponse {
    razorpay_order_id: string;
    razorpay_payment_id: string;
    razorpay_signature: string;
  }

  interface RazorpayError {
    error?: { description?: string };
  }

  const handleUpgrade = async (plan: Plan) => {
    if (plan.price_monthly <= 0) return;
    const Razorpay = (window as any).Razorpay as { new(options: Record<string, unknown>): { on: (event: string, handler: (response: unknown) => void) => void; open: () => void } } | undefined;
    if (!Razorpay) {
      setError('Payment gateway not loaded. Please refresh the page.');
      return;
    }
    setIsProcessing(true);
    setError('');

    try {
      const orderResp = await api.post('/api/subscriptions/create-order', { plan_id: plan.id });
      const order = orderResp.data as { key_id: string; amount: number; currency: string; plan_name: string; order_id: string };

      const options = {
        key: order.key_id,
        amount: order.amount,
        currency: order.currency || 'INR',
        name: 'Hyperclients',
        description: `${order.plan_name} Plan`,
        order_id: order.order_id,
        prefill: { email: (await supabase.auth.getUser()).data.user?.email },
        theme: { color: '#6366f1' },
        handler: async (response: unknown) => {
          const r = response as RazorpayResponse;
          try {
            await api.post('/api/subscriptions/verify', {
              razorpay_order_id: r.razorpay_order_id,
              razorpay_payment_id: r.razorpay_payment_id,
              razorpay_signature: r.razorpay_signature,
              plan_id: plan.id,
            });
            setSuccess(`Upgraded to ${plan.name} plan successfully!`);
            loadData();
          } catch (err) {
            const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
            setError(typeof detail === 'string' ? detail : 'Payment verification failed');
          } finally {
            setIsProcessing(false);
          }
        },
        modal: {
          ondismiss: () => setIsProcessing(false),
        },
      };

      const rzp = new Razorpay(options);
      rzp.on('payment.failed', (response: unknown) => {
        const errResp = response as RazorpayError;
        setError(errResp.error?.description || 'Payment failed');
        setIsProcessing(false);
      });
      rzp.open();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to start upgrade');
      setIsProcessing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 text-steel animate-spin" />
      </div>
    );
  }

  const currentPlanId = subscription?.plan_id || 'free';
  const currentMeta = PLAN_META[currentPlanId] || PLAN_META.free;
  const CurrentIcon = currentMeta.icon;
  const isTrialExpired = subscription?.is_trial_expired;

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex items-center gap-3">
        <CreditCard className="w-6 h-6 text-steel" />
        <h1 className="text-2xl font-bold text-offwhite">Billing & Plan</h1>
      </div>

      {error && (
        <div className="flex items-center gap-2 p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-rose-400 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {success && (
        <div className="flex items-center gap-2 p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 text-sm">
          <Check className="w-4 h-4 shrink-0" />
          {success}
        </div>
      )}

      {/* Current Plan */}
      <GlassCard className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className={`p-3 rounded-xl ${currentMeta.bg}`}>
              <CurrentIcon className={`w-6 h-6 ${currentMeta.color}`} />
            </div>
            <div>
              <p className="text-xs text-ice/50 uppercase tracking-wider font-semibold">Current Plan</p>
              <h2 className="text-2xl font-bold text-offwhite mt-0.5">{currentMeta.name}</h2>
              {isTrialExpired && currentPlanId === 'free' && (
                <p className="text-xs text-rose-400 mt-1">Trial expired — upgrade to continue searching</p>
              )}
              {subscription?.trial_end && currentPlanId === 'free' && !isTrialExpired && (
                <p className="text-xs text-amber-400 mt-1">
                  Trial ends {new Date(subscription.trial_end).toLocaleDateString()}
                </p>
              )}
              {subscription?.current_period_end && currentPlanId !== 'free' && (
                <p className="text-xs text-ice/40 mt-1">
                  Next billing: {new Date(subscription.current_period_end).toLocaleDateString()}
                </p>
              )}
            </div>
          </div>
          <span className={`px-3 py-1 rounded-full text-xs font-semibold ${currentMeta.bg} ${currentMeta.color}`}>
            {subscription?.status || 'active'}
          </span>
        </div>
      </GlassCard>

      {/* Usage */}
      <GlassCard className="p-6">
        <h3 className="text-sm font-semibold text-offwhite mb-4">Daily Usage</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <div className="flex justify-between text-xs text-ice/50 mb-1">
              <span>Searches</span>
              <span>{subscription?.searches_per_day ? (subscription.searches_per_day - (subscription.remaining_searches || 0)) : 0} / {subscription?.searches_per_day || 1}</span>
            </div>
            <div className="h-2 rounded-full bg-ocean/30 overflow-hidden">
              <div
                className="h-full rounded-full bg-steel transition-all"
                style={{ width: `${subscription?.searches_per_day ? ((subscription.searches_per_day - (subscription.remaining_searches || 0)) / subscription.searches_per_day) * 100 : 0}%` }}
              />
            </div>
          </div>
          <div>
            <div className="flex justify-between text-xs text-ice/50 mb-1">
              <span>Leads / day limit</span>
              <span>{subscription?.leads_per_day ? (subscription.leads_per_day - (subscription.remaining_leads || 0)) : 0} / {subscription?.leads_per_day || 30}</span>
            </div>
            <div className="h-2 rounded-full bg-ocean/30 overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-400 transition-all"
                style={{ width: `${subscription?.leads_per_day ? ((subscription.leads_per_day - (subscription.remaining_leads || 0)) / subscription.leads_per_day) * 100 : 0}%` }}
              />
            </div>
          </div>
        </div>
      </GlassCard>

      {/* Available Plans */}
      <GlassCard className="p-6">
        <h3 className="text-sm font-semibold text-offwhite mb-4">Available Plans</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {plans.filter((p) => p.id !== 'free').map((plan) => {
            const meta = PLAN_META[plan.id];
            const Icon = meta?.icon || Zap;
            const isCurrent = plan.id === currentPlanId;
            const priceUsd = (plan.price_monthly / 100);

            return (
              <div
                key={plan.id}
                className={`p-5 rounded-xl border transition-all ${isCurrent ? 'border-steel/50 bg-steel/10' : 'border-ocean/40 bg-ocean/10 hover:border-ocean/60'}`}
              >
                <div className="flex items-center gap-2 mb-3">
                  <Icon className={`w-4 h-4 ${meta?.color || 'text-ice/60'}`} />
                  <h4 className="font-bold text-offwhite">{plan.name}</h4>
                </div>
                <p className="text-2xl font-extrabold text-offwhite mb-1">
                  ${priceUsd}<span className="text-sm font-normal text-ice/40">/mo</span>
                </p>
                <p className="text-xs text-ice/50 mb-4">{plan.leads_per_day} leads/day · {plan.searches_per_day} searches</p>
                {isCurrent ? (
                  <div className="w-full py-2 rounded-lg bg-steel/20 text-steel text-xs font-semibold text-center">
                    Current Plan
                  </div>
                ) : (
                  <LoadingButton
                    fullWidth
                    className="text-xs"
                    onClick={() => handleUpgrade(plan)}
                    isLoading={isProcessing}
                    disabled={isProcessing}
                  >
                    Upgrade
                  </LoadingButton>
                )}
              </div>
            );
          })}
        </div>
      </GlassCard>

      {/* Need help */}
      <div className="text-center">
        <p className="text-xs text-ice/40">
          Need a custom plan? <Link href="mailto:contact@hyperclients.online" className="text-steel hover:underline">Contact us</Link>
        </p>
      </div>
    </div>
  );
}

export default function BillingPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 text-steel animate-spin" /></div>}>
      <BillingContent />
    </Suspense>
  );
}
