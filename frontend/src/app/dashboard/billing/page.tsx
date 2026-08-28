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
            setError('Payment verification failed. Contact support.');
          } finally {
            setIsProcessing(false);
          }
        },
        modal: {
          ondismiss: () => {
            setIsProcessing(false);
          },
        },
      };

      const rzp = new Razorpay(options);
      rzp.on('payment.failed', (response: any) => {
        setError(response.error?.description || 'Payment failed');
        setIsProcessing(false);
      });
      rzp.open();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Failed to create order');
      setIsProcessing(false);
    }
  };

  const handleCancel = async () => {
    if (!confirm('Are you sure you want to cancel your subscription?')) return;
    try {
      await api.post('/api/subscriptions/cancel');
      setSuccess('Subscription cancelled');
      loadData();
    } catch (err) {
      setError('Failed to cancel subscription');
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 text-steel animate-spin" />
      </div>
    );
  }

  const currentMeta = PLAN_META[subscription?.plan_id || 'free'];

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/dashboard" className="p-2 rounded-lg hover:bg-ocean/20 text-ice/40 hover:text-ice">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <h1 className="text-2xl font-bold text-offwhite">Billing & Plans</h1>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-rose-400 shrink-0" />
          <p className="text-sm text-rose-300">{error}</p>
        </div>
      )}
      {success && (
        <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30">
          <p className="text-sm text-emerald-300">{success}</p>
        </div>
      )}

      <GlassCard className="p-6">
        <h2 className="text-lg font-semibold text-offwhite mb-4">Current Plan</h2>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {currentMeta && <currentMeta.icon className={`w-6 h-6 ${currentMeta.color}`} />}
            <div>
              <p className="text-xl font-bold text-offwhite">{currentMeta?.name || 'Free'}</p>
              <p className="text-sm text-ice/50">
                {subscription?.status === 'active' ? 'Active' : subscription?.status === 'trial' ? 'Trial' : 'Inactive'}
              </p>
            </div>
          </div>
          {subscription?.plan_id !== 'free' && (
            <LoadingButton variant="outline" onClick={handleCancel} className="text-rose-400 border-rose-400/30">
              Cancel Plan
            </LoadingButton>
          )}
        </div>
      </GlassCard>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {plans.map((plan) => {
          const meta = PLAN_META[plan.id] || PLAN_META.free;
          const isCurrent = plan.id === subscription?.plan_id;
          return (
            <GlassCard key={plan.id} className={`p-6 ${isCurrent ? 'ring-2 ring-violet' : ''}`}>
              <meta.icon className={`w-8 h-8 ${meta.color} mb-3`} />
              <h3 className="text-lg font-bold text-offwhite">{meta.name}</h3>
              <p className="text-2xl font-bold text-offwhite mt-2">
                ${Math.round(plan.price_monthly / 100)}<span className="text-sm font-normal text-ice/50">/mo</span>
              </p>
              <ul className="mt-4 space-y-2 text-sm text-ice/60">
                <li className="flex items-center gap-2"><Check className="w-4 h-4 text-emerald-400" />{plan.searches_per_day} searches/day</li>
                <li className="flex items-center gap-2"><Check className="w-4 h-4 text-emerald-400" />{plan.leads_per_day} leads/day</li>
              </ul>
              {!isCurrent && plan.price_monthly > 0 && (
                <LoadingButton
                  fullWidth
                  className="mt-4"
                  onClick={() => handleUpgrade(plan)}
                  isLoading={isProcessing}
                >
                  Upgrade
                </LoadingButton>
              )}
              {isCurrent && (
                <div className="mt-4 text-center text-sm font-semibold text-violet">Current Plan</div>
              )}
            </GlassCard>
          );
        })}
      </div>
    </div>
  );
}

export default function BillingPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 text-steel animate-spin" />
      </div>
    }>
      <BillingContent />
    </Suspense>
  );
}
