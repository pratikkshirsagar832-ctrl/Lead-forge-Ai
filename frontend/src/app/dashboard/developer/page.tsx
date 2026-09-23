'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import api from '@/lib/api';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { ensureRazorpayLoaded, type RazorpayError, type RazorpayResponse } from '@/lib/razorpay';
import { formatDateTime } from '@/lib/utils';
import {
  AlertCircle, BookOpen, Check, Copy, KeyRound, Linkedin, MapPin, Plus, Terminal, Trash2, Wallet, Webhook,
} from 'lucide-react';

interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
}

interface NewKey {
  id: string;
  name: string;
  api_key: string;
  webhook_secret: string;
}

interface LedgerRow {
  type: string;
  amount_inr: number;
  balance_after_inr: number;
  search_id: string | null;
  note: string | null;
  created_at: string | null;
}

interface WalletInfo {
  balance_inr: number;
  held_inr: number;
  available_inr: number;
  prices: {
    linkedin_per_lead_inr: number;
    google_maps_per_lead_inr: number;
    linkedin_per_lead_usd: number;
    google_maps_per_lead_usd: number;
  };
  topup_limits_inr: { min: number; max: number };
  ledger: LedgerRow[];
}

interface ApiSearch {
  id: string;
  source: string;
  service: string;
  status: string;
  requested: number;
  delivered: number;
  charged_inr: number | null;
  charged_usd: number | null;
  max_charge_inr: number;
  max_charge_usd: number;
  created_at: string | null;
}

const inr = (n: number | null | undefined) =>
  `₹${Number(n ?? 0).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;

const usd = (n: number | null | undefined) => `$${Number(n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 3 })}`;
// Wallet balances are stored in INR paise; display USD-primary using the
// LinkedIn per-lead rate as the conversion basis (display only — billing
// and Razorpay top-ups stay INR).
const usdFromInr = (inrVal: number | null | undefined, liInr = 50, liUsd = 0.52) => {
  const rate = liInr > 0 ? liUsd / liInr : 0.0104;
  return usd(Number(inrVal ?? 0) * rate);
};

const TOPUP_PRESETS = [10000, 25000, 50000, 100000];

function errMessage(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
}

function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        }).catch(() => {});
      }}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold bg-steel/15 text-steel border border-steel/25 hover:bg-steel/25 transition-colors"
    >
      {done ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
      {done ? 'Copied' : label}
    </button>
  );
}

function CodeBlock({ code }: { code: string }) {
  return (
    <div className="relative">
      <div className="absolute right-2 top-2"><CopyButton text={code} /></div>
      <pre className="text-[12px] leading-relaxed bg-navy/80 border border-ocean/25 rounded-xl p-4 pr-24 overflow-x-auto text-ice/80">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function DeveloperPage() {
  const [wallet, setWallet] = useState<WalletInfo | null>(null);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [searches, setSearches] = useState<ApiSearch[]>([]);
  const [newKey, setNewKey] = useState<NewKey | null>(null);
  const [keyName, setKeyName] = useState('');
  const [topup, setTopup] = useState<number>(10000);
  const [busy, setBusy] = useState<'' | 'key' | 'topup'>('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [tab, setTab] = useState<'curl' | 'node' | 'python' | 'webhook'>('curl');

  const refresh = useCallback(async () => {
    const [w, k, u] = await Promise.allSettled([
      api.get('/api/developer/wallet'),
      api.get('/api/developer/keys'),
      api.get('/api/developer/usage'),
    ]);
    if (w.status === 'fulfilled') setWallet(w.value.data);
    if (k.status === 'fulfilled') setKeys(k.value.data.keys || []);
    if (u.status === 'fulfilled') setSearches(u.value.data.searches || []);
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const limits = wallet?.topup_limits_inr ?? { min: 10000, max: 100000 };
  const origin = typeof window !== 'undefined' ? window.location.origin : 'https://hyperclients.online';
  const activeKeys = keys.filter((k) => !k.revoked_at);

  async function createKey() {
    setBusy('key'); setError(''); setNotice('');
    try {
      const r = await api.post('/api/developer/keys', { name: keyName.trim() || 'Default key' });
      setNewKey(r.data);
      setKeyName('');
      await refresh();
    } catch (e) {
      setError(errMessage(e, 'Could not create the API key.'));
    } finally {
      setBusy('');
    }
  }

  async function revokeKey(id: string) {
    if (!window.confirm('Revoke this key? Any integration using it stops working immediately.')) return;
    try {
      await api.delete(`/api/developer/keys/${id}`);
      await refresh();
    } catch (e) {
      setError(errMessage(e, 'Could not revoke the key.'));
    }
  }

  async function startTopup() {
    setError(''); setNotice('');
    if (!(topup >= limits.min && topup <= limits.max)) {
      setError(`Top-up must be between ${inr(limits.min)} and ${inr(limits.max)}.`);
      return;
    }
    setBusy('topup');
    try {
      const Razorpay = await ensureRazorpayLoaded();
      if (!Razorpay) throw new Error('Payment window could not load. Disable ad-blockers and retry.');
      const order = (await api.post('/api/developer/wallet/topup', { amount_inr: topup })).data;
      if (!order || !order.order_id || !order.key_id || !(order.amount > 0)) {
        throw new Error('Could not start the payment (invalid order). Please try again.');
      }
      const rzp = new Razorpay({
        key: order.key_id,
        amount: order.amount,
        currency: 'INR',
        order_id: order.order_id,
        name: 'Hyperclients',
        description: `API wallet top-up ${inr(topup)}`,
        theme: { color: '#13e0c2' },
        handler: async (response: unknown) => {
          const r = response as RazorpayResponse;
          try {
            await api.post('/api/developer/wallet/verify', r);
            setNotice(`${inr(topup)} added to your API wallet.`);
          } catch (e) {
            setError(errMessage(e, 'Payment received but verification is pending — it will appear shortly.'));
          } finally {
            refresh();
            setBusy('');
          }
        },
        modal: { ondismiss: () => setBusy('') },
      });
      rzp.on('payment.failed', (response: unknown) => {
        setError((response as RazorpayError)?.error?.description || 'Payment failed.');
        setBusy('');
      });
      rzp.open();
    } catch (e) {
      setError(e instanceof Error && !('response' in e) ? e.message : errMessage(e, 'Could not start the payment.'));
      setBusy('');
    }
  }

  const snippets = useMemo(() => ({
    curl: `# 1) Start a search (you are charged only for leads delivered)
curl -X POST ${origin}/v1/searches \\
  -H "Authorization: Bearer $HYPERCLIENTS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"source":"linkedin","service":"video editing","mode":"freelancer","leads":5}'

# 2) Poll until status is "completed"
curl ${origin}/v1/searches/SEARCH_ID \\
  -H "Authorization: Bearer $HYPERCLIENTS_API_KEY"

# 3) Get the leads
curl ${origin}/v1/searches/SEARCH_ID/leads \\
  -H "Authorization: Bearer $HYPERCLIENTS_API_KEY"`,
    node: `const BASE = "${origin}/v1";
const headers = {
  Authorization: \`Bearer \${process.env.HYPERCLIENTS_API_KEY}\`,
  "Content-Type": "application/json",
};

const search = await fetch(\`\${BASE}/searches\`, {
  method: "POST",
  headers,
  body: JSON.stringify({ source: "google_maps", service: "dentists", location: "Pune, India", leads: 50 }),
}).then((r) => r.json());

let s = search;
while (!["completed", "failed", "cancelled"].includes(s.status)) {
  await new Promise((r) => setTimeout(r, 5000));
  s = await fetch(\`\${BASE}/searches/\${search.id}\`, { headers }).then((r) => r.json());
}
const { data: leads } = await fetch(\`\${BASE}/searches/\${search.id}/leads\`, { headers }).then((r) => r.json());
console.log(s.delivered, "leads, charged $" + s.charged_usd, leads);`,
    python: `import os, time, requests

BASE = "${origin}/v1"
H = {"Authorization": f"Bearer {os.environ['HYPERCLIENTS_API_KEY']}"}

search = requests.post(f"{BASE}/searches", headers=H, json={
    "source": "linkedin", "service": "I am a lawyer", "mode": "freelancer", "leads": 3,
}).json()

while True:
    s = requests.get(f"{BASE}/searches/{search['id']}", headers=H).json()
    if s["status"] in ("completed", "failed", "cancelled"):
        break
    time.sleep(5)

leads = requests.get(f"{BASE}/searches/{search['id']}/leads", headers=H).json()["data"]
print(s["delivered"], "leads, charged $", s["charged_usd"])`,
    webhook: `// Verify a webhook (Node / Express). Use the RAW request body.
import crypto from "crypto";

app.post("/hooks/hyperclients", express.raw({ type: "application/json" }), (req, res) => {
  const header = req.get("X-Hyperclients-Signature") || "";     // "t=1727000000,v1=abc..."
  const parts = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  const expected = crypto
    .createHmac("sha256", process.env.HYPERCLIENTS_WEBHOOK_SECRET)   // whsec_...
    .update(\`\${parts.t}.\${req.body}\`)
    .digest("hex");
  const fresh = Math.abs(Date.now() / 1000 - Number(parts.t)) < 300;
  if (!fresh || !crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(parts.v1 || ""))) {
    return res.status(400).send("bad signature");
  }
  const { event, data } = JSON.parse(req.body);                  // "search.completed"
  console.log(event, data.search.delivered, data.leads);
  res.sendStatus(200);
});`,
  }), [origin]);

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-offwhite">Developer API</h1>
          <p className="text-ice/50 text-sm mt-1">
            Pull fresh leads into your CRM, Zapier or n8n. Pay only for leads delivered.
          </p>
        </div>
        <div className="flex gap-2">
          <a href="/v1/docs" target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold bg-steel/15 text-steel border border-steel/25 hover:bg-steel/25">
            <BookOpen className="w-4 h-4" /> API reference
          </a>
          <a href="/v1/redoc" target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold bg-navy/60 text-ice/70 border border-ocean/25 hover:text-offwhite">
            Full docs
          </a>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 rounded-xl bg-rose-500/10 border border-rose-500/25 text-rose-300 text-sm">
          <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
        </div>
      )}
      {notice && (
        <div className="flex items-start gap-2 p-3 rounded-xl bg-emerald-500/10 border border-emerald-500/25 text-emerald-300 text-sm">
          <Check className="w-4 h-4 mt-0.5 shrink-0" /> {notice}
        </div>
      )}

      {/* Pricing + wallet */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <GlassCard className="p-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-ice/40 mb-3">Pricing</p>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm text-offwhite"><Linkedin className="w-4 h-4 text-sky-400" /> LinkedIn lead</span>
              <span className="text-right">
                <span className="text-lg font-bold text-offwhite">{usd(wallet?.prices.linkedin_per_lead_usd ?? 0.52)} <span className="text-[11px] font-semibold text-ice/50">per lead</span></span>
                <span className="block text-[11px] text-ice/50">{inr(wallet?.prices.linkedin_per_lead_inr ?? 50)} in wallet</span>
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm text-offwhite"><MapPin className="w-4 h-4 text-emerald-400" /> Google Maps lead</span>
              <span className="text-right">
                <span className="text-lg font-bold text-offwhite">{usd(wallet?.prices.google_maps_per_lead_usd ?? 0.052)} <span className="text-[11px] font-semibold text-ice/50">per lead</span></span>
                <span className="block text-[11px] text-ice/50">{inr(wallet?.prices.google_maps_per_lead_inr ?? 5)} in wallet</span>
              </span>
            </div>
          </div>
          <p className="text-[11px] text-ice/40 mt-4 leading-relaxed">
            A search holds <em>leads × price</em>. When it finishes you pay only for leads actually delivered —
            the rest is released automatically.
          </p>
        </GlassCard>

        <GlassCard className="p-5 lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-ice/40 flex items-center gap-2">
              <Wallet className="w-4 h-4" /> API wallet
            </p>
          </div>
          <div className="grid grid-cols-3 gap-3 mb-5">
            {[
              { label: 'Available', value: wallet?.available_inr, strong: true },
              { label: 'Balance', value: wallet?.balance_inr },
              { label: 'Held by running searches', value: wallet?.held_inr },
            ].map((s) => (
              <div key={s.label} className="rounded-xl bg-navy/60 border border-ocean/25 p-3">
                <p className="text-[11px] text-ice/45">{s.label}</p>
                <p className={`mt-1 font-bold ${s.strong ? 'text-2xl text-emerald-300' : 'text-lg text-offwhite'}`}>
                  {usdFromInr(s.value, wallet?.prices.linkedin_per_lead_inr ?? 50, wallet?.prices.linkedin_per_lead_usd ?? 0.52)}
                </p>
                <p className="text-[11px] text-ice/45">{inr(s.value)}</p>
              </div>
            ))}
          </div>
          <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
            <div className="flex gap-1.5 flex-wrap">
              {TOPUP_PRESETS.map((n) => (
                <button key={n} type="button" onClick={() => setTopup(n)}
                        className={`px-3 py-2 rounded-xl text-sm font-semibold border transition-colors ${
                          topup === n ? 'bg-emerald-500/10 border-emerald-500/40 text-emerald-300'
                                      : 'bg-navy/60 border-ocean/25 text-ice/60 hover:text-offwhite'}`}>
                  {inr(n)}
                </button>
              ))}
            </div>
            <input type="number" min={limits.min} max={limits.max} step={1000} value={topup}
                   onChange={(e) => setTopup(Number(e.target.value))}
                   className="w-full sm:w-36 px-3 py-2 rounded-xl border border-ocean/30 bg-navy/60 text-offwhite outline-none focus:ring-2 focus:ring-steel/40" />
            <LoadingButton isLoading={busy === 'topup'} onClick={startTopup} className="sm:ml-auto">
              Add {inr(topup)}
            </LoadingButton>
          </div>
          <p className="text-[11px] text-ice/40 mt-2">
            Top-ups from {inr(limits.min)} to {inr(limits.max)} per payment, via Razorpay (charged in INR
            ≈ {usdFromInr(limits.min, wallet?.prices.linkedin_per_lead_inr ?? 50, wallet?.prices.linkedin_per_lead_usd ?? 0.52)}–{usdFromInr(limits.max, wallet?.prices.linkedin_per_lead_inr ?? 50, wallet?.prices.linkedin_per_lead_usd ?? 0.52)}).
          </p>
        </GlassCard>
      </div>

      {/* API keys */}
      <GlassCard className="p-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-ice/40 flex items-center gap-2">
            <KeyRound className="w-4 h-4" /> API keys
          </p>
          <div className="flex gap-2">
            <input value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="Key name (e.g. Zapier)"
                   maxLength={60}
                   className="px-3 py-2 rounded-xl border border-ocean/30 bg-navy/60 text-offwhite text-sm outline-none focus:ring-2 focus:ring-steel/40" />
            <LoadingButton isLoading={busy === 'key'} onClick={createKey} icon={<Plus className="w-4 h-4" />}>
              Create key
            </LoadingButton>
          </div>
        </div>

        {newKey && (
          <div className="mb-4 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 space-y-3">
            <p className="text-sm font-semibold text-amber-200">
              Copy these now — they are shown only once and cannot be retrieved later.
            </p>
            {[
              { label: 'API key', value: newKey.api_key },
              { label: 'Webhook signing secret', value: newKey.webhook_secret },
            ].map((f) => (
              <div key={f.label}>
                <p className="text-[11px] text-ice/50 mb-1">{f.label}</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 truncate px-3 py-2 rounded-lg bg-navy/80 border border-ocean/25 text-[12px] text-offwhite">{f.value}</code>
                  <CopyButton text={f.value} />
                </div>
              </div>
            ))}
            <button type="button" onClick={() => setNewKey(null)} className="text-xs text-ice/50 hover:text-offwhite">
              I have saved them
            </button>
          </div>
        )}

        {keys.length === 0 ? (
          <p className="text-sm text-ice/45">No API keys yet. Create one to start using the API.</p>
        ) : (
          <div className="divide-y divide-ocean/20">
            {keys.map((k) => (
              <div key={k.id} className="flex items-center justify-between py-3 gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-offwhite truncate">
                    {k.name} {k.revoked_at && <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-300">revoked</span>}
                  </p>
                  <p className="text-[11px] text-ice/45 font-mono">{k.prefix}••••••••</p>
                </div>
                <div className="text-right text-[11px] text-ice/45 hidden sm:block">
                  <p>Created {k.created_at ? formatDateTime(k.created_at) : '—'}</p>
                  <p>Last used {k.last_used_at ? formatDateTime(k.last_used_at) : 'never'}</p>
                </div>
                {!k.revoked_at && (
                  <button type="button" onClick={() => revokeKey(k.id)} title="Revoke"
                          className="p-2 rounded-lg text-rose-300/80 hover:bg-rose-500/10">
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
        {activeKeys.length > 0 && (
          <p className="text-[11px] text-ice/40 mt-3">
            Keep keys on your server only — never in a browser or mobile app. Revoke a key immediately if it leaks.
          </p>
        )}
      </GlassCard>

      {/* Quick start */}
      <GlassCard className="p-5">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-ice/40 flex items-center gap-2">
            <Terminal className="w-4 h-4" /> Quick start
          </p>
          <div className="flex gap-1 flex-wrap">
            {([['curl', 'cURL'], ['node', 'Node.js'], ['python', 'Python'], ['webhook', 'Webhook']] as const).map(([k, label]) => (
              <button key={k} type="button" onClick={() => setTab(k)}
                      className={`px-3 py-1.5 rounded-lg text-xs font-semibold border ${
                        tab === k ? 'bg-steel/20 border-steel/40 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/55 hover:text-offwhite'}`}>
                {k === 'webhook' && <Webhook className="w-3 h-3 inline mr-1" />}{label}
              </button>
            ))}
          </div>
        </div>
        <CodeBlock code={snippets[tab]} />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4 text-[12px] text-ice/55">
          <div className="rounded-xl bg-navy/50 border border-ocean/20 p-3">
            <p className="font-semibold text-offwhite mb-1">source</p>
            <code>linkedin</code> — people posting that they need your service (1–10 leads). <code>google_maps</code> — local businesses (1–100 leads, <code>location</code> required).
          </div>
          <div className="rounded-xl bg-navy/50 border border-ocean/20 p-3">
            <p className="font-semibold text-offwhite mb-1">service</p>
            Any wording, any industry: “video editing”, “I am a CA”, “we are a law firm”, “dentists”.
          </div>
          <div className="rounded-xl bg-navy/50 border border-ocean/20 p-3">
            <p className="font-semibold text-offwhite mb-1">mode (LinkedIn)</p>
            <code>freelancer</code> — someone needs an individual. <code>agency</code> — a client wants an agency/firm.
          </div>
        </div>
      </GlassCard>

      {/* Usage */}
      <GlassCard className="p-5">
        <p className="text-xs font-semibold uppercase tracking-wide text-ice/40 mb-3">Recent API searches</p>
        {searches.length === 0 ? (
          <p className="text-sm text-ice/45">No API searches yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-ice/45 uppercase">
                  <th className="py-2 pr-3">When</th><th className="py-2 pr-3">Source</th><th className="py-2 pr-3">Service</th>
                  <th className="py-2 pr-3">Status</th><th className="py-2 pr-3 text-right">Leads</th><th className="py-2 text-right">Charged</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ocean/15">
                {searches.map((s) => (
                  <tr key={s.id} className="text-ice/75">
                    <td className="py-2 pr-3 whitespace-nowrap">{s.created_at ? formatDateTime(s.created_at) : '—'}</td>
                    <td className="py-2 pr-3">{s.source === 'linkedin' ? 'LinkedIn' : 'Google Maps'}</td>
                    <td className="py-2 pr-3 max-w-[220px] truncate">{s.service}</td>
                    <td className="py-2 pr-3 capitalize">{s.status}</td>
                    <td className="py-2 pr-3 text-right">{s.delivered}/{s.requested}</td>
                    <td className="py-2 text-right whitespace-nowrap">
                      {s.charged_inr == null
                        ? <span className="text-ice/40">held {usd(s.max_charge_usd)} <span className="text-[11px]">({inr(s.max_charge_inr)})</span></span>
                        : <>{usd(s.charged_usd)} <span className="text-ice/45 text-[11px]">({inr(s.charged_inr)})</span></>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!!wallet?.ledger?.length && (
          <details className="mt-4">
            <summary className="text-xs text-ice/50 cursor-pointer hover:text-offwhite">Wallet transactions</summary>
            <div className="mt-2 divide-y divide-ocean/15 text-[12px]">
              {wallet.ledger.map((l, i) => (
                <div key={i} className="flex justify-between py-1.5 text-ice/65">
                  <span className="capitalize">{l.type}{l.note ? ` — ${l.note}` : ''}</span>
                  <span className={l.amount_inr < 0 ? 'text-rose-300' : 'text-emerald-300'}>
                    {l.amount_inr < 0 ? '−' : '+'}{usdFromInr(Math.abs(l.amount_inr), wallet?.prices.linkedin_per_lead_inr ?? 50, wallet?.prices.linkedin_per_lead_usd ?? 0.52)}{' '}
                    <span className="text-[11px] opacity-70">({inr(Math.abs(l.amount_inr))})</span>
                  </span>
                </div>
              ))}
            </div>
          </details>
        )}
      </GlassCard>
    </div>
  );
}
