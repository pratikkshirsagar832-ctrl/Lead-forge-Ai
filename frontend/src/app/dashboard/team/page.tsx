'use client';

export const dynamic = 'force-dynamic';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import api from '@/lib/api';
import { Users, Trash2, Loader2, UserPlus, Sparkles, Copy, Check } from 'lucide-react';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { Skeleton } from '@/components/shared/Skeleton';

interface TeamMember {
  id: string;
  username: string;
  email: string;
  created_at: string | null;
}

interface TeamData {
  plan_id: string;
  seats_allowed: number;
  seats_used: number;
  members: TeamMember[];
}

export default function TeamPage() {
  const [team, setTeam] = useState<TeamData | null>(null);
  const [planId, setPlanId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAdding, setIsAdding] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [form, setForm] = useState({ username: '', password: '' });

  const loadTeam = useCallback(async () => {
    try {
      setIsLoading(true);
      const meResp = await api.get('/api/auth/me');
      setPlanId(meResp.data?.subscription?.plan_id || 'free');
      if (['pro', 'agency'].includes(meResp.data?.subscription?.plan_id || '')) {
        const resp = await api.get('/api/auth/team');
        setTeam(resp.data);
      }
    } catch {
      setError('Failed to load team data');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { loadTeam(); }, [loadTeam]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccessMsg('');
    setIsAdding(true);
    try {
      await api.post('/api/auth/team', form);
      setSuccessMsg(`Account "${form.username}" created — share the username & password with your teammate`);
      setForm({ username: '', password: '' });
      await loadTeam();
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : detail?.message || 'Failed to create account');
    } finally {
      setIsAdding(false);
    }
  };

  const handleRemove = async (id: string, username: string) => {
    if (!confirm(`Remove "${username}"? They will lose access immediately.`)) return;
    setRemovingId(id);
    try {
      await api.delete(`/api/auth/team/${id}`);
      await loadTeam();
    } catch {
      alert('Failed to remove member');
    } finally {
      setRemovingId(null);
    }
  };

  const copyLoginUrl = () => {
    navigator.clipboard.writeText(`${window.location.origin}/login`).then(() => {
      setCopiedId('url');
      setTimeout(() => setCopiedId(null), 2000);
    });
  };

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-6">
        <Skeleton className="h-10 w-1/3" />
        <GlassCard className="p-8"><Skeleton className="h-40 w-full" /></GlassCard>
      </div>
    );
  }

  // Free/Solo → upsell
  if (!planId || !['pro', 'agency'].includes(planId)) {
    return (
      <div className="max-w-4xl mx-auto space-y-6">
        <div>
          <h1 className="text-3xl font-extrabold text-offwhite tracking-tight">Team</h1>
          <p className="text-ice/60 mt-2 text-sm font-medium">Create accounts for your teammates.</p>
        </div>
        <GlassCard className="p-10 text-center">
          <div className="w-14 h-14 rounded-full bg-violet/20 flex items-center justify-center mx-auto mb-4">
            <Sparkles className="w-7 h-7 text-violet" />
          </div>
          <h2 className="text-xl font-bold text-offwhite mb-2">Team seats are a Pro & Agency feature</h2>
          <p className="text-sm text-ice/60 max-w-md mx-auto mb-6">
            Pro includes 2 team seats, Agency includes 10. Your teammates get their own
            username &amp; password and their own login.
          </p>
          <Link
            href="/dashboard/billing"
            className="inline-flex items-center gap-2 bg-gradient-to-r from-steel to-violet/80 text-offwhite font-semibold px-6 py-2.5 rounded-xl hover:opacity-90 transition-opacity"
          >
            <Sparkles className="w-4 h-4" />
            Upgrade Plan
          </Link>
        </GlassCard>
      </div>
    );
  }

  const seatsLeft = (team?.seats_allowed ?? 0) - (team?.seats_used ?? 0);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-extrabold text-offwhite tracking-tight">Team</h1>
          <p className="text-ice/60 mt-2 text-sm font-medium">
            Create username &amp; password accounts for your teammates.
          </p>
        </div>
        <div className="flex items-center gap-2 text-sm font-medium text-ice/50">
          <Users className="w-4 h-4 text-steel" />
          <span className="text-offwhite font-bold">{team?.seats_used ?? 0}</span>
          / {team?.seats_allowed} seats used
        </div>
      </div>

      {/* Add member */}
      <GlassCard className="p-6">
        <h2 className="text-sm font-bold text-offwhite uppercase tracking-wider mb-4 flex items-center gap-2">
          <UserPlus className="w-4 h-4 text-steel" />
          Create Team Account
        </h2>
        {seatsLeft <= 0 ? (
          <p className="text-sm text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-xl p-4">
            All {team?.seats_allowed} seats are in use. Remove a member to create a new account.
          </p>
        ) : (
          <form onSubmit={handleAdd} className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-3 items-start">
            <div>
              <label className="block text-xs font-semibold text-ice/60 mb-1.5">Username</label>
              <input
                type="text"
                value={form.username}
                onChange={(e) => setForm(f => ({ ...f, username: e.target.value.toLowerCase() }))}
                placeholder="e.g. rahul_sales"
                required
                pattern="[a-z0-9_]{3,20}"
                title="3-20 chars: lowercase letters, numbers, underscores"
                className="w-full px-3 py-2.5 rounded-lg bg-ocean/20 border border-ocean/40 text-ice placeholder-ice/30 text-sm focus:outline-none focus:border-steel focus:ring-1 focus:ring-steel/50"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-ice/60 mb-1.5">Password</label>
              <input
                type="text"
                value={form.password}
                onChange={(e) => setForm(f => ({ ...f, password: e.target.value }))}
                placeholder="min 6 characters"
                required
                minLength={6}
                className="w-full px-3 py-2.5 rounded-lg bg-ocean/20 border border-ocean/40 text-ice placeholder-ice/30 text-sm focus:outline-none focus:border-steel focus:ring-1 focus:ring-steel/50"
              />
            </div>
            <LoadingButton type="submit" isLoading={isAdding} className="sm:mt-[26px]">
              Create
            </LoadingButton>
          </form>
        )}
        {error && <p className="text-sm text-rose-400 mt-3">{error}</p>}
        {successMsg && (
          <div className="mt-3 p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-between gap-3">
            <p className="text-sm text-emerald-300">{successMsg}</p>
            <button
              onClick={copyLoginUrl}
              className="text-xs font-semibold text-emerald-300 hover:text-emerald-200 inline-flex items-center gap-1 shrink-0"
            >
              {copiedId === 'url' ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
              {copiedId === 'url' ? 'Copied' : 'Copy Login URL'}
            </button>
          </div>
        )}
        <p className="text-xs text-ice/40 mt-3">
          Teammates log in at <span className="text-ice/60">/login</span> with just their username &amp; password.
        </p>
      </GlassCard>

      {/* Members list */}
      <GlassCard className="p-6">
        <h2 className="text-sm font-bold text-offwhite uppercase tracking-wider mb-4">
          Members ({team?.members.length ?? 0})
        </h2>
        {!team || team.members.length === 0 ? (
          <p className="text-sm text-ice/50 py-6 text-center">No team accounts yet.</p>
        ) : (
          <div className="space-y-3">
            {team.members.map((m) => (
              <div key={m.id} className="flex items-center justify-between gap-4 p-4 rounded-xl bg-ocean/20 border border-ocean/30">
                <div className="min-w-0">
                  <p className="font-bold text-offwhite text-sm">{m.username}</p>
                  <p className="text-xs text-ice/40 truncate">{m.email}</p>
                  {m.created_at && (
                    <p className="text-xs text-ice/30 mt-0.5">
                      Created {new Date(m.created_at).toLocaleDateString()}
                    </p>
                  )}
                </div>
                <LoadingButton
                  variant="outline"
                  size="sm"
                  isLoading={removingId === m.id}
                  onClick={() => handleRemove(m.id, m.username)}
                  className="border-rose-500/30 text-rose-400 hover:bg-rose-500/10 shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5 mr-1" />
                  Remove
                </LoadingButton>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
}
