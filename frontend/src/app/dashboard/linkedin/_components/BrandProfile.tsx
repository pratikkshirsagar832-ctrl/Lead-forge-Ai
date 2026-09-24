'use client';

import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { Building2, Check, ChevronLeft, ChevronRight, ShieldCheck, UserRound, Users, X } from 'lucide-react';
import { Chips, TagInput, errText, inputCls, labelCls } from './shared';

export interface Brand {
  managed_for: 'self' | 'company' | 'client';
  full_name: string; headline: string; company: string; website: string; industry: string; location: string;
  language: string; services: string; offer: string; target_audience: string; ideal_client: string;
  goals: string[]; tone: string[]; topics: string[]; expertise: string; story_bank: string;
  writing_samples: string; cta_preference: string; avoid: string; posting_frequency: string; notes: string;
  authorized: boolean; voice_profile?: string | null; voice_updated_at?: string | null;
}

const EMPTY: Brand = {
  managed_for: 'self', full_name: '', headline: '', company: '', website: '', industry: '', location: '',
  language: 'English', services: '', offer: '', target_audience: '', ideal_client: '', goals: [], tone: [],
  topics: [], expertise: '', story_bank: '', writing_samples: '', cta_preference: '', avoid: '',
  posting_frequency: '3 posts / week', notes: '', authorized: false,
};

const GOALS = [
  { v: 'Inbound leads', label: 'Inbound leads' }, { v: 'Authority / thought leadership', label: 'Authority' },
  { v: 'Personal brand', label: 'Personal brand' }, { v: 'Hiring', label: 'Hiring' },
  { v: 'Community / network', label: 'Network' }, { v: 'Launch / product awareness', label: 'Launches' },
] as const;
const TONES = [
  { v: 'Conversational', label: 'Conversational' }, { v: 'Direct', label: 'Direct' }, { v: 'Bold / contrarian', label: 'Bold' },
  { v: 'Storytelling', label: 'Storytelling' }, { v: 'Data-driven', label: 'Data-driven' }, { v: 'Warm', label: 'Warm' },
  { v: 'Humorous', label: 'Humorous' }, { v: 'Formal', label: 'Formal' },
] as const;
const WHO = [
  { v: 'self', label: 'Myself', desc: 'My own personal brand', Icon: UserRound },
  { v: 'company', label: 'My company', desc: 'Founder / team voice for the business', Icon: Building2 },
  { v: 'client', label: 'A client', desc: 'I manage LinkedIn for a client', Icon: Users },
] as const;
const STEPS = ['Who', 'Business', 'Content', 'Stories & consent'];

function fromApi(p: Partial<Record<keyof Brand, unknown>> | null): Brand {
  const b = { ...EMPTY };
  if (!p) return b;
  for (const k of Object.keys(EMPTY) as (keyof Brand)[]) {
    const v = p[k];
    if (v === null || v === undefined) continue;
    (b as unknown as Record<string, unknown>)[k] = v;
  }
  b.voice_profile = (p.voice_profile as string) || null;
  b.voice_updated_at = (p.voice_updated_at as string) || null;
  return b;
}

export function BrandForm({ onSaved, onCancel, compact = false }: {
  onSaved: (b: Brand) => void; onCancel?: () => void; compact?: boolean;
}) {
  const [b, setB] = useState<Brand>(EMPTY);
  const [step, setStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get('/api/linkedin/brand')
      .then((r) => setB(fromApi(r.data.profile)))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const set = <K extends keyof Brand>(k: K, v: Brand[K]) => setB((cur) => ({ ...cur, [k]: v }));
  const whoLabel = b.managed_for === 'client' ? "Client's" : b.managed_for === 'company' ? "Company's" : 'Your';
  const stepOk = [
    b.full_name.trim().length >= 2,
    b.services.trim().length >= 3 && b.target_audience.trim().length >= 3,
    true,
    b.authorized,
  ];

  async function save() {
    setError(''); setSaving(true);
    try {
      const { voice_profile: _v, voice_updated_at: _u, ...payload } = b;
      const r = await api.put('/api/linkedin/brand', payload);
      onSaved(fromApi(r.data.profile));
    } catch (e) {
      setError(errText(e, 'Could not save the profile.'));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="h-40 flex items-center justify-center"><div className="animate-spin rounded-full h-6 w-6 border-t-2 border-steel" /></div>;

  return (
    <div className="space-y-4">
      {/* stepper */}
      <div className="flex items-center gap-1.5">
        {STEPS.map((s, i) => (
          <button key={s} type="button" onClick={() => (i <= step || stepOk.slice(0, i).every(Boolean)) && setStep(i)}
                  className={`flex-1 text-left rounded-lg px-2 py-1.5 border text-[11px] font-semibold ${i === step ? 'bg-steel/20 border-steel/40 text-offwhite' : i < step ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300' : 'bg-navy/50 border-ocean/20 text-ice/40'}`}>
            <span className="opacity-60 mr-1">{i + 1}</span>{s}
          </button>
        ))}
      </div>

      {step === 0 && (
        <div className="space-y-3">
          <div>
            <p className={labelCls}>Whose LinkedIn will Hyperclients manage?</p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              {WHO.map(({ v, label, desc, Icon }) => (
                <button key={v} type="button" onClick={() => set('managed_for', v)}
                        className={`text-left p-3 rounded-xl border ${b.managed_for === v ? 'bg-steel/20 border-steel/50' : 'bg-navy/60 border-ocean/25 hover:border-steel/30'}`}>
                  <Icon className="w-4 h-4 text-sky-300 mb-1" />
                  <p className="text-sm font-semibold text-offwhite">{label}</p>
                  <p className="text-[11px] text-ice/50">{desc}</p>
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div><label className={labelCls}>{whoLabel} full name *</label><input className={inputCls} value={b.full_name} onChange={(e) => set('full_name', e.target.value)} placeholder="e.g. Asha Rao" maxLength={120} /></div>
            <div><label className={labelCls}>Role / LinkedIn headline</label><input className={inputCls} value={b.headline} onChange={(e) => set('headline', e.target.value)} placeholder="e.g. Founder, Rao & Co. Chartered Accountants" maxLength={220} /></div>
            <div><label className={labelCls}>Company</label><input className={inputCls} value={b.company} onChange={(e) => set('company', e.target.value)} maxLength={160} /></div>
            <div><label className={labelCls}>Website</label><input className={inputCls} value={b.website} onChange={(e) => set('website', e.target.value)} placeholder="https://" maxLength={300} /></div>
            <div><label className={labelCls}>Industry</label><input className={inputCls} value={b.industry} onChange={(e) => set('industry', e.target.value)} placeholder="e.g. Accounting, SaaS, Real estate" maxLength={120} /></div>
            <div><label className={labelCls}>Location</label><input className={inputCls} value={b.location} onChange={(e) => set('location', e.target.value)} placeholder="e.g. Pune, India" maxLength={120} /></div>
            <div><label className={labelCls}>Write posts in</label>
              <select className={inputCls} value={b.language} onChange={(e) => set('language', e.target.value)}>
                {['English', 'Hinglish', 'Hindi', 'Spanish', 'French', 'German', 'Portuguese', 'Arabic'].map((l) => <option key={l}>{l}</option>)}
              </select>
            </div>
          </div>
        </div>
      )}

      {step === 1 && (
        <div className="space-y-3">
          <div><label className={labelCls}>What do they sell / do? *</label><textarea rows={3} className={inputCls} value={b.services} onChange={(e) => set('services', e.target.value)} maxLength={1500} placeholder="Services, products, how they deliver" /></div>
          <div><label className={labelCls}>Offer, proof &amp; what makes them different</label><textarea rows={3} className={inputCls} value={b.offer} onChange={(e) => set('offer', e.target.value)} maxLength={1500} placeholder="Results, case studies, pricing angle, guarantees - real facts only" /></div>
          <div><label className={labelCls}>Who should read the posts? (target audience) *</label><textarea rows={2} className={inputCls} value={b.target_audience} onChange={(e) => set('target_audience', e.target.value)} maxLength={800} placeholder="e.g. Founders of 10-50 person SaaS companies in India" /></div>
          <div><label className={labelCls}>Ideal client</label><textarea rows={2} className={inputCls} value={b.ideal_client} onChange={(e) => set('ideal_client', e.target.value)} maxLength={800} placeholder="Who buys, their pain, what triggers them to buy" /></div>
        </div>
      )}

      {step === 2 && (
        <div className="space-y-3">
          <div><p className={labelCls}>Goals on LinkedIn</p><Chips options={GOALS} value={b.goals as never[]} onChange={(v) => set('goals', v)} /></div>
          <div><p className={labelCls}>Tone</p><Chips options={TONES} value={b.tone as never[]} onChange={(v) => set('tone', v)} /></div>
          <div><p className={labelCls}>Content pillars / topics (Enter to add, 3-5 is ideal)</p><TagInput value={b.topics} onChange={(v) => set('topics', v)} placeholder="e.g. GST mistakes, cash flow, founder lessons" /></div>
          <div><label className={labelCls}>Expertise &amp; strong opinions</label><textarea rows={3} className={inputCls} value={b.expertise} onChange={(e) => set('expertise', e.target.value)} maxLength={2000} placeholder="What they know better than most, and what they believe that peers disagree with" /></div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div><label className={labelCls}>Preferred call to action</label><input className={inputCls} value={b.cta_preference} onChange={(e) => set('cta_preference', e.target.value)} maxLength={300} placeholder="e.g. DM me 'audit' / soft question / none" /></div>
            <div><label className={labelCls}>Posting frequency</label>
              <select className={inputCls} value={b.posting_frequency} onChange={(e) => set('posting_frequency', e.target.value)}>
                {['2 posts / week', '3 posts / week', '4 posts / week', '5 posts / week', 'Daily'].map((f) => <option key={f}>{f}</option>)}
              </select>
            </div>
          </div>
          <div><label className={labelCls}>Never use / never mention</label><input className={inputCls} value={b.avoid} onChange={(e) => set('avoid', e.target.value)} maxLength={800} placeholder="Words, topics, competitors, client names to keep out" /></div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-3">
          <div><label className={labelCls}>Story bank - real numbers, wins, failures, lessons (the AI uses only these facts)</label>
            <textarea rows={5} className={inputCls} value={b.story_bank} onChange={(e) => set('story_bank', e.target.value)} maxLength={8000}
                      placeholder={'- Mar 2025: cut client onboarding from 11 days to 4\n- Lost our biggest client in 2024 because...\n- 312 GST notices handled for SaaS founders'} />
            <p className="text-[10px] text-ice/40 mt-1">Tip: the AI Skills → Interview tool fills this for you by asking questions.</p>
          </div>
          <div><label className={labelCls}>Anything else the AI should know</label><textarea rows={2} className={inputCls} value={b.notes} onChange={(e) => set('notes', e.target.value)} maxLength={2000} /></div>
          <label className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer ${b.authorized ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-navy/60 border-ocean/25'}`}>
            <input type="checkbox" checked={b.authorized} onChange={(e) => set('authorized', e.target.checked)} className="mt-1 accent-emerald-500" />
            <span className="text-xs text-ice/70 leading-relaxed">
              <ShieldCheck className="inline w-3.5 h-3.5 text-emerald-300 mr-1" />
              I confirm I am {b.managed_for === 'self' ? 'this person' : b.managed_for === 'company' ? 'authorized to post for this company' : 'authorized by this client'} and I
              authorize Hyperclients to create, schedule and publish LinkedIn posts on {b.managed_for === 'self' ? 'my' : 'their'} behalf using
              LinkedIn&apos;s official API. Posts only go out when I schedule them or turn on autopilot.
            </span>
          </label>
        </div>
      )}

      {error && <p className="text-xs text-rose-300">{error}</p>}
      <div className="flex items-center justify-between gap-2">
        <div>
          {step > 0
            ? <button type="button" onClick={() => setStep(step - 1)} className="inline-flex items-center gap-1 text-sm text-ice/60 hover:text-offwhite"><ChevronLeft className="w-4 h-4" /> Back</button>
            : onCancel && <button type="button" onClick={onCancel} className="text-sm text-ice/50 hover:text-offwhite">Cancel</button>}
        </div>
        {step < STEPS.length - 1
          ? <LoadingButton onClick={() => setStep(step + 1)} disabled={!stepOk[step]}>Next <ChevronRight className="w-4 h-4 ml-1" /></LoadingButton>
          : <LoadingButton onClick={save} isLoading={saving} disabled={!stepOk.every(Boolean)} icon={<Check className="w-4 h-4" />}>
              {compact ? 'Save & connect LinkedIn' : 'Save profile'}
            </LoadingButton>}
      </div>
    </div>
  );
}

export function BrandModal({ onClose, onSaved }: { onClose: () => void; onSaved: (b: Brand) => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-start sm:items-center justify-center p-3 sm:p-6 bg-black/60 backdrop-blur-sm overflow-y-auto">
      <GlassCard className="w-full max-w-2xl p-5 sm:p-6 my-6">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div>
            <h2 className="text-lg font-bold text-offwhite">Before you connect LinkedIn</h2>
            <p className="text-xs text-ice/55 mt-1">Tell us whose LinkedIn this is and about their business. The AI reads all of it before writing every post, so it writes as them, about their real work, and never invents facts.</p>
          </div>
          <button onClick={onClose} className="text-ice/40 hover:text-offwhite"><X className="w-5 h-5" /></button>
        </div>
        <BrandForm compact onCancel={onClose} onSaved={onSaved} />
      </GlassCard>
    </div>
  );
}

export function BrandTab({ setNotice, onSaved }: {
  setNotice: (s: string) => void; onSaved: () => void;
}) {
  return (
    <GlassCard className="p-5 max-w-3xl">
      <p className="text-xs font-semibold uppercase tracking-wide text-ice/40 mb-3">Brand profile - what the AI knows</p>
      <BrandForm onSaved={() => { setNotice('Brand profile saved. The AI uses it on every task.'); onSaved(); }} />
    </GlassCard>
  );
}
