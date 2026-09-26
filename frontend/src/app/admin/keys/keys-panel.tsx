'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, CheckCircle2, KeyRound, Loader2, Plus, RefreshCw, Trash2, AlertCircle } from 'lucide-react';

interface KeyRow {
  id: string; label: string | null; key_hint: string; status: 'active' | 'exhausted' | 'invalid' | 'disabled';
  source: 'admin' | 'env'; credits_remaining: number | null; credits_used: number; calls: number;
  last_error: string | null; last_used_at: string | null; last_checked_at: string | null; created_at: string;
}
interface KeysResponse {
  keys: KeyRow[];
  totals: { keys: number; active: number; credits_remaining: number; credits_used: number; calls: number };
  in_use: string | null;
}

const STATUS: Record<KeyRow['status'], { label: string; cls: string }> = {
  active: { label: 'Active', cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25' },
  exhausted: { label: 'Out of credits', cls: 'bg-amber-500/10 text-amber-300 border-amber-500/25' },
  invalid: { label: 'Invalid', cls: 'bg-rose-500/10 text-rose-300 border-rose-500/25' },
  disabled: { label: 'Disabled', cls: 'bg-white/5 text-ice/50 border-white/10' },
};

function ago(iso: string | null): string {
  if (!iso) return 'never';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

const inputCls = 'w-full rounded-xl bg-bg-elevated border border-primary/20 px-4 py-2.5 text-sm text-offwhite placeholder:text-text-muted/60 outline-none focus:border-brand-accent/50 focus:ring-2 focus:ring-brand-accent/20';

export default function KeysPanel() {
  const [data, setData] = useState<KeysResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [newKey, setNewKey] = useState('');
  const [label, setLabel] = useState('');

  const call = useCallback(async (url: string, init?: RequestInit) => {
    const res = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json' }, cache: 'no-store' });
    const body = await res.json().catch(() => ({}));
    if (res.status === 401) { window.location.href = '/admin/login'; throw new Error('Session expired'); }
    if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
    return body;
  }, []);

  const load = useCallback(async () => {
    try { setData(await call('/api/admin/socialcrawl-keys')); setError(''); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }, [call]);

  useEffect(() => { load(); }, [load]);

  async function act(name: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(name); setError(''); setNotice('');
    try { await fn(); setNotice(ok); await load(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(''); }
  }

  const add = () => act('add', async () => {
    const r = await call('/api/admin/socialcrawl-keys', { method: 'POST', body: JSON.stringify({ key: newKey.trim(), label: label.trim() }) });
    setNewKey(''); setLabel('');
    return r;
  }, 'Key added and verified.');
  const refresh = () => act('refresh', async () => setData(await call('/api/admin/socialcrawl-keys/refresh', { method: 'POST' })), 'Balances updated.');
  const toggle = (k: KeyRow) => act(k.id, () => call(`/api/admin/socialcrawl-keys/${k.id}`, { method: 'PATCH', body: JSON.stringify({ enabled: k.status === 'disabled' }) }),
    k.status === 'disabled' ? 'Key enabled.' : 'Key disabled.');
  const remove = (k: KeyRow) => {
    if (!window.confirm(`Remove key …${k.key_hint}? Searches will stop using it.`)) return;
    act(k.id, () => call(`/api/admin/socialcrawl-keys/${k.id}`, { method: 'DELETE' }), 'Key removed.');
  };

  const t = data?.totals;

  return (
    <div className="relative min-h-screen bg-navy text-ice font-sans">
      <div className="container mx-auto px-4 sm:px-6 pt-24 pb-16 max-w-5xl space-y-6">
        <header className="flex items-center justify-between flex-wrap gap-4">
          <div>
            <Link href="/admin" className="text-xs text-text-secondary hover:text-offwhite inline-flex items-center gap-1 mb-2"><ArrowLeft className="w-3.5 h-3.5" /> Blog admin</Link>
            <h1 className="text-3xl font-bold text-offwhite font-heading flex items-center gap-2"><KeyRound className="w-7 h-7 text-brand-accent-light" /> SocialCrawl API keys</h1>
            <p className="text-text-secondary text-sm mt-1 max-w-2xl">
              LinkedIn searches use the first active key. When a key runs out of credits it is marked &ldquo;Out of credits&rdquo; and the
              next key takes over automatically, even in the middle of a search.
            </p>
          </div>
          <button onClick={refresh} disabled={!!busy} className="btn-glass rounded-xl px-4 py-2 text-sm inline-flex items-center gap-2 disabled:opacity-50">
            {busy === 'refresh' ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} Check balances
          </button>
        </header>

        {error && <div className="flex items-center gap-2 text-sm text-rose-300 bg-rose-500/10 border border-rose-500/25 rounded-xl px-4 py-3"><AlertCircle className="w-4 h-4 shrink-0" /> {error}</div>}
        {notice && <div className="flex items-center gap-2 text-sm text-emerald-300 bg-emerald-500/10 border border-emerald-500/25 rounded-xl px-4 py-3"><CheckCircle2 className="w-4 h-4 shrink-0" /> {notice}</div>}

        {/* low-balance warning: one LinkedIn search uses ~25-60 credits */}
        {t && t.credits_remaining < 300 && (
          <div className="flex items-start gap-2 text-sm text-amber-200 bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>
              Only <b>{t.credits_remaining.toLocaleString()}</b> SocialCrawl credits left across active keys - roughly{' '}
              {Math.max(0, Math.floor(t.credits_remaining / 40))} more LinkedIn searches. Top up or add a key so searches don&apos;t fail.
            </span>
          </div>
        )}

        {/* totals */}
        {t && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              ['Credits left (active keys)', t.credits_remaining.toLocaleString()],
              ['Active keys', `${t.active} / ${t.keys}`],
              ['Credits used', t.credits_used.toLocaleString()],
              ['Search calls', t.calls.toLocaleString()],
            ].map(([k, v]) => (
              <div key={k} className="rounded-2xl bg-white/[0.03] border border-primary/15 p-4">
                <p className="text-2xl font-bold text-offwhite">{v}</p>
                <p className="text-xs text-text-secondary mt-1">{k}</p>
              </div>
            ))}
          </div>
        )}
        {t && t.active === 0 && (
          <div className="text-sm text-amber-300 bg-amber-500/10 border border-amber-500/25 rounded-xl px-4 py-3">
            No active key - LinkedIn searches will fail until you add a key or top one up and press &ldquo;Check balances&rdquo;.
          </div>
        )}

        {/* add */}
        <div className="rounded-2xl bg-white/[0.03] border border-primary/15 p-5 space-y-3">
          <p className="text-sm font-semibold text-offwhite">Add a key</p>
          <div className="grid grid-cols-1 md:grid-cols-[1fr_200px_auto] gap-2">
            <input value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="sc_..." className={`${inputCls} font-mono`} autoComplete="off" spellCheck={false} />
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label (optional)" className={inputCls} maxLength={80} />
            <button onClick={add} disabled={!!busy || newKey.trim().length < 10}
                    className="rounded-xl px-5 py-2.5 text-sm font-semibold bg-brand-accent text-navy inline-flex items-center justify-center gap-2 disabled:opacity-50">
              {busy === 'add' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />} Add key
            </button>
          </div>
          <p className="text-xs text-text-secondary">The key is checked with SocialCrawl (free) and stored encrypted. Only its last 4 characters are ever shown.</p>
        </div>

        {/* list */}
        <div className="rounded-2xl bg-white/[0.03] border border-primary/15 overflow-hidden">
          {loading ? (
            <div className="p-10 flex justify-center"><Loader2 className="w-6 h-6 animate-spin text-brand-accent-light" /></div>
          ) : !data?.keys.length ? (
            <p className="p-8 text-center text-sm text-text-secondary">No keys yet. Add one above.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-text-secondary border-b border-primary/15">
                    <th className="px-4 py-3 font-semibold">Key</th>
                    <th className="px-4 py-3 font-semibold">Status</th>
                    <th className="px-4 py-3 font-semibold text-right">Credits left</th>
                    <th className="px-4 py-3 font-semibold text-right">Used</th>
                    <th className="px-4 py-3 font-semibold text-right">Calls</th>
                    <th className="px-4 py-3 font-semibold">Last used</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {data.keys.map((k) => (
                    <tr key={k.id} className="border-b border-primary/10 last:border-0 align-top">
                      <td className="px-4 py-3">
                        <p className="font-mono text-offwhite">sc_…{k.key_hint}</p>
                        <p className="text-[11px] text-text-secondary">{k.label || (k.source === 'env' ? 'from .env' : 'added in admin')}
                          {data.in_use === k.id && <span className="ml-2 text-brand-accent-light font-semibold">in use</span>}</p>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex px-2 py-0.5 rounded-md border text-[11px] font-semibold ${STATUS[k.status]?.cls || ''}`}>{STATUS[k.status]?.label || k.status}</span>
                        {k.last_error && k.status !== 'active' && <p className="text-[11px] text-text-secondary mt-1 max-w-[200px] truncate" title={k.last_error}>{k.last_error}</p>}
                      </td>
                      <td className="px-4 py-3 text-right text-offwhite font-semibold">{k.credits_remaining == null ? '—' : k.credits_remaining.toLocaleString()}</td>
                      <td className="px-4 py-3 text-right">{Number(k.credits_used || 0).toLocaleString()}</td>
                      <td className="px-4 py-3 text-right">{Number(k.calls || 0).toLocaleString()}</td>
                      <td className="px-4 py-3 text-xs text-text-secondary whitespace-nowrap">{ago(k.last_used_at)}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-3 whitespace-nowrap">
                          <button onClick={() => toggle(k)} disabled={!!busy} className="text-xs text-text-secondary hover:text-offwhite disabled:opacity-50">
                            {k.status === 'disabled' ? 'Enable' : 'Disable'}
                          </button>
                          <button onClick={() => remove(k)} disabled={!!busy} className="text-xs text-rose-300/80 hover:text-rose-300 inline-flex items-center gap-1 disabled:opacity-50">
                            <Trash2 className="w-3.5 h-3.5" /> Remove
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <p className="text-xs text-text-secondary">Balances update after every search call. &ldquo;Check balances&rdquo; asks SocialCrawl directly (free) and brings topped-up keys back.</p>
      </div>
    </div>
  );
}
