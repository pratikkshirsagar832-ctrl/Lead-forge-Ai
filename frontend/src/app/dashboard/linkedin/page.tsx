'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import api from '@/lib/api';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { formatDateTime } from '@/lib/utils';
import {
  AlertCircle, Bot, CalendarClock, Check, ExternalLink, FileText, Image as ImageIcon, Layers,
  Linkedin, Lock, Plus, RefreshCw, Send, Sparkles, Trash2, Wand2, X,
} from 'lucide-react';

/* ----------------------------------------------------------------- types */

interface Account {
  id: string; kind: 'person' | 'organization'; name: string | null; avatar_url: string | null;
  app: string; status: string; days_left: number | null; needs_reconnect_soon: boolean;
}
interface PlanInfo { plan_id: string; enabled: boolean; limit: number; used: number; scheduled: number; remaining: number }
interface Status { plan: PlanInfo; accounts: Account[]; member_app_configured: boolean; pages_enabled: boolean }
interface Media { type: 'image' | 'document'; storage_path: string; title: string; alt: string; preview?: string }
interface Post {
  id: string; account_id: string | null; status: string; commentary: string; media: Media[];
  visibility: 'PUBLIC' | 'CONNECTIONS'; scheduled_at: string | null; published_at: string | null;
  post_url: string | null; error: string | null; source: string;
}
interface Slide { title: string; body: string }
interface Autopilot {
  enabled: boolean; auto_approve: boolean; consent_at?: string | null; account_id?: string | null;
  timezone: string; slots: { dow: number; time: string }[]; pillars: string[];
  audience?: string | null; voice_profile?: string | null; lookahead_days: number;
}

const MAX = 3000;
const SEE_MORE = 210;
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const STATUS_STYLE: Record<string, string> = {
  draft: 'bg-steel/15 text-steel border-steel/25',
  scheduled: 'bg-sky-500/10 text-sky-300 border-sky-500/25',
  publishing: 'bg-amber-500/10 text-amber-300 border-amber-500/25',
  published: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25',
  failed: 'bg-rose-500/10 text-rose-300 border-rose-500/25',
  needs_reconnect: 'bg-rose-500/10 text-rose-300 border-rose-500/25',
  cancelled: 'bg-white/5 text-ice/40 border-white/10',
};

function errText(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (d && typeof d === 'object' && 'message' in d) return String((d as { message: string }).message);
  return fallback;
}

function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function defaultScheduleInput(): string {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setMinutes(0, 0, 0);
  return toLocalInput(d.toISOString());
}

const inputCls = 'w-full px-3 py-2 rounded-xl border border-ocean/30 bg-navy/60 text-offwhite text-sm outline-none focus:ring-2 focus:ring-steel/40 placeholder-ice/30';

/* ------------------------------------------------------------------ page */

function Studio() {
  const params = useSearchParams();
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<'compose' | 'queue' | 'autopilot'>('compose');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [posts, setPosts] = useState<Post[]>([]);

  // composer state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [accountId, setAccountId] = useState('');
  const [text, setText] = useState('');
  const [media, setMedia] = useState<Media[]>([]);
  const [visibility, setVisibility] = useState<'PUBLIC' | 'CONNECTIONS'>('PUBLIC');
  const [when, setWhen] = useState(defaultScheduleInput());
  const [busy, setBusy] = useState('');

  const refresh = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api.get('/api/linkedin/status'), api.get('/api/linkedin/posts')]);
      setStatus(s.data);
      setPosts(p.data.posts || []);
      const active = (s.data.accounts as Account[]).filter((a) => a.status === 'active');
      setAccountId((cur) => cur || active[0]?.id || '');
    } catch (e) {
      setError(errText(e, 'Could not load LinkedIn Studio.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (params.get('connected')) setNotice('LinkedIn connected. You can post now.');
    if (params.get('error')) setError(`LinkedIn: ${params.get('error')}`);
  }, [params]);

  const activeAccounts = (status?.accounts || []).filter((a) => a.status === 'active');
  const plan = status?.plan;

  async function connect(app: 'member' | 'pages') {
    setError('');
    try {
      const r = await api.get(`/api/linkedin/connect?app=${app}`);
      window.location.href = r.data.url;
    } catch (e) {
      setError(errText(e, 'Could not start the LinkedIn connection.'));
    }
  }

  async function disconnect(id: string) {
    if (!window.confirm('Disconnect this LinkedIn account? Its scheduled posts will pause.')) return;
    await api.delete(`/api/linkedin/accounts/${id}`).catch((e) => setError(errText(e, 'Could not disconnect.')));
    refresh();
  }

  function resetComposer() {
    setEditingId(null); setText(''); setMedia([]); setVisibility('PUBLIC'); setWhen(defaultScheduleInput());
  }

  function editPost(p: Post) {
    setEditingId(p.id); setText(p.commentary); setMedia(p.media || []); setVisibility(p.visibility);
    if (p.account_id) setAccountId(p.account_id);
    setWhen(p.scheduled_at ? toLocalInput(p.scheduled_at) : defaultScheduleInput());
    setTab('compose');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function save(action: 'draft' | 'schedule' | 'publish_now') {
    setError(''); setNotice(''); setBusy(action);
    const payload = {
      account_id: accountId || null,
      commentary: text,
      media: media.map(({ type, storage_path, title, alt }) => ({ type, storage_path, title, alt })),
      visibility,
      scheduled_at: when ? new Date(when).toISOString() : null,
    };
    try {
      let post: Post;
      if (editingId) {
        post = (await api.patch(`/api/linkedin/posts/${editingId}`, payload)).data;
        if (action === 'schedule') post = (await api.post(`/api/linkedin/posts/${editingId}/schedule`, { scheduled_at: payload.scheduled_at })).data;
        if (action === 'publish_now') post = (await api.post(`/api/linkedin/posts/${editingId}/publish-now`)).data;
      } else {
        post = (await api.post('/api/linkedin/posts', { ...payload, action, source: 'manual' })).data;
      }
      if (post.status === 'published') setNotice('Published on LinkedIn.');
      else if (post.status === 'scheduled') setNotice(`Scheduled for ${formatDateTime(post.scheduled_at)}.`);
      else if (post.status === 'draft') setNotice('Draft saved.');
      else setError(post.error || `Post is ${post.status}.`);
      if (post.status !== 'draft') resetComposer(); else setEditingId(post.id);
      refresh();
    } catch (e) {
      setError(errText(e, 'Could not save the post.'));
    } finally {
      setBusy('');
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-96"><div className="animate-spin rounded-full h-8 w-8 border-t-2 border-steel" /></div>;
  }

  if (plan && !plan.enabled) {
    return (
      <GlassCard className="p-8 max-w-xl mx-auto text-center mt-10">
        <div className="mx-auto mb-4 h-14 w-14 rounded-full bg-steel/15 flex items-center justify-center"><Lock className="h-7 w-7 text-steel" /></div>
        <h1 className="text-xl font-bold text-offwhite">LinkedIn Studio is on Pro and Agency</h1>
        <p className="text-ice/55 text-sm mt-2">
          Write posts with AI, build carousels, schedule them and let autopilot keep your LinkedIn active,
          published through LinkedIn&apos;s official API.
        </p>
        <Link href="/dashboard/billing" className="inline-flex mt-5 px-5 py-2.5 rounded-xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-semibold text-sm">
          Upgrade plan
        </Link>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-offwhite flex items-center gap-2"><Linkedin className="w-6 h-6 text-sky-400" /> LinkedIn Studio</h1>
          <p className="text-ice/50 text-sm mt-1">AI-written posts, carousels and scheduling, published via LinkedIn&apos;s official API.</p>
        </div>
        {plan && (
          <div className="text-xs text-ice/60 bg-navy/60 border border-ocean/25 rounded-xl px-3 py-2">
            <span className="text-offwhite font-semibold">{plan.used}</span> published · <span className="text-offwhite font-semibold">{plan.scheduled}</span> scheduled · limit {plan.limit}/month
          </div>
        )}
      </div>

      {error && <Banner kind="error" onClose={() => setError('')}>{error}</Banner>}
      {notice && <Banner kind="ok" onClose={() => setNotice('')}>{notice}</Banner>}
      {status && !status.member_app_configured && (
        <Banner kind="error">LinkedIn is not configured on the server yet (LINKEDIN_CLIENT_ID / SECRET).</Banner>
      )}
      {status?.accounts.filter((a) => a.needs_reconnect_soon || a.status !== 'active').map((a) => (
        <Banner key={a.id} kind="error">
          {a.status !== 'active'
            ? <>LinkedIn connection for <b>{a.name}</b> expired, and its scheduled posts are paused. </>
            : <>LinkedIn connection for <b>{a.name}</b> expires in {a.days_left} day(s). </>}
          <button className="underline font-semibold" onClick={() => connect(a.app === 'pages' ? 'pages' : 'member')}>Reconnect now</button>
        </Banner>
      ))}

      <AccountsCard status={status} onConnect={connect} onDisconnect={disconnect} />

      <div className="flex gap-1.5">
        {([['compose', 'Compose', Wand2], ['queue', 'Queue & calendar', CalendarClock], ['autopilot', 'Autopilot', Bot]] as const).map(([k, label, Icon]) => (
          <button key={k} onClick={() => setTab(k)}
                  className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold border ${tab === k ? 'bg-steel/20 border-steel/40 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/55 hover:text-offwhite'}`}>
            <Icon className="w-4 h-4" /> {label}
          </button>
        ))}
      </div>

      {tab === 'compose' && (
        <Composer
          accounts={activeAccounts} accountId={accountId} setAccountId={setAccountId}
          text={text} setText={setText} media={media} setMedia={setMedia}
          visibility={visibility} setVisibility={setVisibility} when={when} setWhen={setWhen}
          editing={!!editingId} onReset={resetComposer} onSave={save} busy={busy} setError={setError}
        />
      )}
      {tab === 'queue' && <Queue posts={posts} accounts={status?.accounts || []} onEdit={editPost} onChanged={refresh} setError={setError} setNotice={setNotice} />}
      {tab === 'autopilot' && <AutopilotPanel accounts={activeAccounts} setError={setError} setNotice={setNotice} onChanged={refresh} />}
    </div>
  );
}

/* ------------------------------------------------------------ components */

function Banner({ kind, children, onClose }: { kind: 'ok' | 'error'; children: React.ReactNode; onClose?: () => void }) {
  const cls = kind === 'ok' ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-300' : 'bg-rose-500/10 border-rose-500/25 text-rose-300';
  return (
    <div className={`flex items-start gap-2 p-3 rounded-xl border text-sm ${cls}`}>
      {kind === 'ok' ? <Check className="w-4 h-4 mt-0.5 shrink-0" /> : <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />}
      <div className="flex-1">{children}</div>
      {onClose && <button onClick={onClose} className="opacity-60 hover:opacity-100"><X className="w-4 h-4" /></button>}
    </div>
  );
}

function AccountsCard({ status, onConnect, onDisconnect }: {
  status: Status | null; onConnect: (a: 'member' | 'pages') => void; onDisconnect: (id: string) => void;
}) {
  const accounts = status?.accounts || [];
  return (
    <GlassCard className="p-5">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {accounts.length === 0 && <p className="text-sm text-ice/50">Connect your LinkedIn profile to start posting.</p>}
          {accounts.map((a) => (
            <div key={a.id} className="flex items-center gap-2 pl-1.5 pr-2 py-1.5 rounded-xl bg-navy/60 border border-ocean/25">
              {a.avatar_url
                ? <img src={a.avatar_url} alt="" className="w-7 h-7 rounded-full object-cover" />
                : <div className="w-7 h-7 rounded-full bg-sky-500/15 flex items-center justify-center"><Linkedin className="w-3.5 h-3.5 text-sky-400" /></div>}
              <div className="leading-tight">
                <p className="text-xs font-semibold text-offwhite">{a.name || 'LinkedIn'}</p>
                <p className="text-[10px] text-ice/45">{a.kind === 'organization' ? 'Company page' : 'Personal profile'} · {a.status === 'active' ? `active${a.days_left != null ? `, ${a.days_left}d left` : ''}` : 'reconnect needed'}</p>
              </div>
              <button onClick={() => onDisconnect(a.id)} title="Disconnect" className="ml-1 text-ice/35 hover:text-rose-300"><X className="w-3.5 h-3.5" /></button>
            </div>
          ))}
        </div>
        <div className="flex gap-2 shrink-0">
          <button onClick={() => onConnect('member')}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold bg-sky-500/15 text-sky-300 border border-sky-500/30 hover:bg-sky-500/25">
            <Plus className="w-4 h-4" /> Connect profile
          </button>
          <button onClick={() => status?.pages_enabled && onConnect('pages')} disabled={!status?.pages_enabled}
                  title={status?.pages_enabled ? '' : 'Company pages are awaiting LinkedIn approval'}
                  className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold bg-navy/60 text-ice/70 border border-ocean/25 disabled:opacity-50 disabled:cursor-not-allowed">
            <Plus className="w-4 h-4" /> Company pages{!status?.pages_enabled && <span className="text-[10px] ml-1">(soon)</span>}
          </button>
        </div>
      </div>
    </GlassCard>
  );
}

function Composer(props: {
  accounts: Account[]; accountId: string; setAccountId: (v: string) => void;
  text: string; setText: (v: string) => void; media: Media[]; setMedia: (m: Media[]) => void;
  visibility: 'PUBLIC' | 'CONNECTIONS'; setVisibility: (v: 'PUBLIC' | 'CONNECTIONS') => void;
  when: string; setWhen: (v: string) => void; editing: boolean; onReset: () => void;
  onSave: (a: 'draft' | 'schedule' | 'publish_now') => void; busy: string; setError: (s: string) => void;
}) {
  const { text, setText, media, setMedia, setError } = props;
  const [topic, setTopic] = useState('');
  const [goal, setGoal] = useState<'engagement' | 'authority' | 'leads'>('engagement');
  const [variants, setVariants] = useState<{ hook_style: string; post: string }[]>([]);
  const [instruction, setInstruction] = useState('');
  const [aiBusy, setAiBusy] = useState('');
  const [changes, setChanges] = useState<string[]>([]);
  const [slides, setSlides] = useState<Slide[]>([]);
  const [deckTitle, setDeckTitle] = useState('');
  const account = props.accounts.find((a) => a.id === props.accountId);

  async function run<T>(key: string, fn: () => Promise<T>): Promise<T | undefined> {
    setError(''); setAiBusy(key);
    try { return await fn(); } catch (e) { setError(errText(e, 'The AI request failed.')); return undefined; } finally { setAiBusy(''); }
  }

  const generate = () => run('draft', async () => {
    const r = await api.post('/api/linkedin/ai/draft', { topic, goal, variants: 3 });
    setVariants(r.data.variants || []);
  });
  const humanize = () => run('humanize', async () => {
    const r = await api.post('/api/linkedin/ai/humanize', { post: text });
    setText(r.data.post); setChanges(r.data.changes || []);
  });
  const rewrite = () => run('rewrite', async () => {
    const r = await api.post('/api/linkedin/ai/rewrite', { post: text, instruction });
    setText(r.data.post);
  });
  const carousel = () => run('carousel', async () => {
    const r = await api.post('/api/linkedin/ai/carousel', { topic, slides: 8 });
    setSlides(r.data.slides); setDeckTitle(r.data.title);
    setMedia([r.data.media]);
    if (!text.trim() && r.data.caption) setText(r.data.caption);
  });
  const rerender = () => run('render', async () => {
    const r = await api.post('/api/linkedin/carousel/render', { title: deckTitle || 'Carousel', slides });
    setMedia([r.data.media]);
  });

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setError('');
    const next = [...media];
    for (const f of Array.from(files)) {
      const fd = new FormData();
      fd.append('file', f);
      setAiBusy('upload');
      try {
        const r = await api.post('/api/linkedin/media', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
        next.push({ ...r.data, preview: f.type.startsWith('image/') ? URL.createObjectURL(f) : undefined });
      } catch (e) {
        setError(errText(e, `Could not upload ${f.name}.`));
      }
    }
    setAiBusy('');
    setMedia(next);
  }

  const over = text.length > MAX;
  const hasDoc = media.some((m) => m.type === 'document');

  return (
    <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">
      <div className="xl:col-span-3 space-y-4">
        {/* AI */}
        <GlassCard className="p-5 space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-ice/40 flex items-center gap-2"><Sparkles className="w-4 h-4" /> Write with AI</p>
          <textarea value={topic} onChange={(e) => setTopic(e.target.value)} rows={2} maxLength={600}
                    placeholder="What should the post be about? e.g. 3 mistakes I see founders make when hiring a video editor"
                    className={inputCls} />
          <div className="flex flex-wrap gap-2 items-center">
            <select value={goal} onChange={(e) => setGoal(e.target.value as typeof goal)} className={`${inputCls} w-auto`}>
              <option value="engagement">Goal: comments &amp; discussion</option>
              <option value="authority">Goal: authority &amp; saves</option>
              <option value="leads">Goal: inbound leads</option>
            </select>
            <LoadingButton isLoading={aiBusy === 'draft'} disabled={topic.trim().length < 3} onClick={generate} icon={<Sparkles className="w-4 h-4" />}>Generate 3 posts</LoadingButton>
            <LoadingButton variant="secondary" isLoading={aiBusy === 'carousel'} disabled={topic.trim().length < 3} onClick={carousel} icon={<Layers className="w-4 h-4" />}>AI carousel</LoadingButton>
          </div>
          {variants.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              {variants.map((v, i) => (
                <button key={i} onClick={() => { setText(v.post); setChanges([]); }}
                        className="text-left p-3 rounded-xl bg-navy/60 border border-ocean/25 hover:border-steel/40 transition-colors">
                  <p className="text-[10px] uppercase tracking-wide text-steel mb-1">{v.hook_style || `Variant ${i + 1}`}</p>
                  <p className="text-xs text-ice/70 line-clamp-6 whitespace-pre-line">{v.post}</p>
                  <p className="text-[11px] text-emerald-300 mt-2 font-semibold">Use this</p>
                </button>
              ))}
            </div>
          )}
        </GlassCard>

        {/* Editor */}
        <GlassCard className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs font-semibold uppercase tracking-wide text-ice/40">{props.editing ? 'Edit post' : 'Post'}</p>
            {props.editing && <button onClick={props.onReset} className="text-xs text-ice/50 hover:text-offwhite">New post instead</button>}
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12}
                    placeholder="Write your post, or generate one above."
                    className={`${inputCls} font-[inherit] leading-relaxed`} />
          <div className="flex flex-wrap items-center gap-2">
            <span className={`text-xs ${over ? 'text-rose-300' : 'text-ice/45'}`}>{text.length}/{MAX}</span>
            <LoadingButton size="sm" variant="secondary" isLoading={aiBusy === 'humanize'} disabled={text.trim().length < 10} onClick={humanize} icon={<Wand2 className="w-3.5 h-3.5" />}>Humanize</LoadingButton>
            <input value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="Rewrite: e.g. shorter, more casual"
                   className={`${inputCls} flex-1 min-w-[160px]`} />
            <LoadingButton size="sm" variant="secondary" isLoading={aiBusy === 'rewrite'} disabled={text.trim().length < 10 || instruction.trim().length < 2} onClick={rewrite}>Rewrite</LoadingButton>
          </div>
          {changes.length > 0 && (
            <ul className="text-[11px] text-ice/50 list-disc pl-5">{changes.map((c, i) => <li key={i}>{c}</li>)}</ul>
          )}

          {/* Media */}
          <div className="flex flex-wrap gap-2 items-center">
            <label className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold border cursor-pointer ${hasDoc ? 'opacity-40 pointer-events-none' : 'bg-navy/60 border-ocean/25 text-ice/70 hover:text-offwhite'}`}>
              <ImageIcon className="w-3.5 h-3.5" /> Add images
              <input type="file" accept="image/jpeg,image/png,image/gif" multiple className="hidden" onChange={(e) => upload(e.target.files)} />
            </label>
            <label className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold border cursor-pointer ${media.length ? 'opacity-40 pointer-events-none' : 'bg-navy/60 border-ocean/25 text-ice/70 hover:text-offwhite'}`}>
              <FileText className="w-3.5 h-3.5" /> Add PDF / carousel
              <input type="file" accept="application/pdf" className="hidden" onChange={(e) => upload(e.target.files)} />
            </label>
            {aiBusy === 'upload' && <span className="text-xs text-ice/50">Uploading…</span>}
          </div>
          {media.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {media.map((m, i) => (
                <div key={m.storage_path} className="relative flex items-center gap-2 pr-7 pl-2 py-2 rounded-lg bg-navy/60 border border-ocean/25 text-xs text-ice/70">
                  {m.type === 'image' && m.preview ? <img src={m.preview} alt="" className="w-10 h-10 object-cover rounded" /> : m.type === 'image' ? <ImageIcon className="w-4 h-4" /> : <FileText className="w-4 h-4" />}
                  {m.type === 'document'
                    ? <input value={m.title} onChange={(e) => setMedia(media.map((x, j) => j === i ? { ...x, title: e.target.value } : x))}
                             placeholder="Document title" className="bg-transparent border-b border-ocean/30 outline-none w-40 text-offwhite" />
                    : <span>Image {i + 1}</span>}
                  <button onClick={() => setMedia(media.filter((_, j) => j !== i))} className="absolute right-1.5 top-1.5 text-ice/40 hover:text-rose-300"><X className="w-3.5 h-3.5" /></button>
                </div>
              ))}
            </div>
          )}
          {slides.length > 0 && hasDoc && (
            <details className="rounded-xl bg-navy/40 border border-ocean/20 p-3">
              <summary className="text-xs text-ice/60 cursor-pointer">Edit carousel slides ({slides.length})</summary>
              <div className="space-y-2 mt-3">
                <input value={deckTitle} onChange={(e) => setDeckTitle(e.target.value)} className={inputCls} placeholder="Document title" />
                {slides.map((s, i) => (
                  <div key={i} className="grid grid-cols-1 md:grid-cols-3 gap-2">
                    <input value={s.title} onChange={(e) => setSlides(slides.map((x, j) => j === i ? { ...x, title: e.target.value } : x))} className={inputCls} />
                    <input value={s.body} onChange={(e) => setSlides(slides.map((x, j) => j === i ? { ...x, body: e.target.value } : x))} className={`${inputCls} md:col-span-2`} />
                  </div>
                ))}
                <LoadingButton size="sm" variant="secondary" isLoading={aiBusy === 'render'} onClick={rerender} icon={<RefreshCw className="w-3.5 h-3.5" />}>Update PDF</LoadingButton>
              </div>
            </details>
          )}
        </GlassCard>
      </div>

      {/* Publish panel + preview */}
      <div className="xl:col-span-2 space-y-4">
        <GlassCard className="p-5 space-y-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-ice/40">Publish</p>
          <select value={props.accountId} onChange={(e) => props.setAccountId(e.target.value)} className={inputCls}>
            {props.accounts.length === 0 && <option value="">Connect a LinkedIn account first</option>}
            {props.accounts.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.kind === 'organization' ? 'page' : 'profile'})</option>)}
          </select>
          <select value={props.visibility} onChange={(e) => props.setVisibility(e.target.value as 'PUBLIC' | 'CONNECTIONS')} className={inputCls}>
            <option value="PUBLIC">Anyone (public)</option>
            <option value="CONNECTIONS">Connections only</option>
          </select>
          <input type="datetime-local" value={props.when} onChange={(e) => props.setWhen(e.target.value)} className={inputCls} />
          <div className="grid grid-cols-3 gap-2">
            <LoadingButton variant="secondary" isLoading={props.busy === 'draft'} onClick={() => props.onSave('draft')} disabled={over}>Save draft</LoadingButton>
            <LoadingButton isLoading={props.busy === 'schedule'} onClick={() => props.onSave('schedule')} disabled={over || !props.accountId} icon={<CalendarClock className="w-4 h-4" />}>Schedule</LoadingButton>
            <LoadingButton isLoading={props.busy === 'publish_now'} onClick={() => props.onSave('publish_now')} disabled={over || !props.accountId} icon={<Send className="w-4 h-4" />}>Post now</LoadingButton>
          </div>
        </GlassCard>
        <Preview text={text} account={account} media={media} />
      </div>
    </div>
  );
}

function Preview({ text, account, media }: { text: string; account?: Account; media: Media[] }) {
  const [open, setOpen] = useState(false);
  const short = text.length > SEE_MORE && !open;
  const shown = short ? text.slice(0, SEE_MORE).trimEnd() : text;
  return (
    <div className="rounded-2xl bg-white text-[#191919] p-4 shadow-sm">
      <div className="flex items-center gap-2 mb-3">
        {account?.avatar_url ? <img src={account.avatar_url} alt="" className="w-10 h-10 rounded-full object-cover" /> : <div className="w-10 h-10 rounded-full bg-[#0a66c2]/15" />}
        <div>
          <p className="text-sm font-semibold">{account?.name || 'Your name'}</p>
          <p className="text-[11px] text-[#666]">Now · 🌐</p>
        </div>
      </div>
      <p className="text-[14px] leading-[1.45] whitespace-pre-line break-words">
        {shown || <span className="text-[#999]">Your post preview appears here.</span>}
        {short && <button onClick={() => setOpen(true)} className="text-[#666] ml-1">…see more</button>}
      </p>
      {media.length > 0 && (
        <div className="mt-3 rounded-lg bg-[#f3f2ef] p-3 text-xs text-[#666] flex items-center gap-2">
          {media[0].type === 'document' ? <><FileText className="w-4 h-4" /> {media[0].title || 'Document'} (PDF carousel)</> : <><ImageIcon className="w-4 h-4" /> {media.length} image{media.length > 1 ? 's' : ''}</>}
        </div>
      )}
      <p className="text-[10px] text-[#999] mt-3">Text past ~{SEE_MORE} characters is hidden behind &ldquo;…see more&rdquo;, so put the hook first.</p>
    </div>
  );
}

function Queue({ posts, accounts, onEdit, onChanged, setError, setNotice }: {
  posts: Post[]; accounts: Account[]; onEdit: (p: Post) => void; onChanged: () => void;
  setError: (s: string) => void; setNotice: (s: string) => void;
}) {
  const [filter, setFilter] = useState<'upcoming' | 'drafts' | 'published' | 'problems'>('upcoming');
  const names = useMemo(() => Object.fromEntries(accounts.map((a) => [a.id, a.name])), [accounts]);
  const shown = posts.filter((p) => ({
    upcoming: ['scheduled', 'publishing'].includes(p.status),
    drafts: p.status === 'draft',
    published: p.status === 'published',
    problems: ['failed', 'needs_reconnect', 'cancelled'].includes(p.status),
  }[filter])).sort((a, b) => (filter === 'published' ? -1 : 1) * String(a.scheduled_at || a.published_at || '').localeCompare(String(b.scheduled_at || b.published_at || '')));

  async function act(fn: () => Promise<unknown>, ok: string) {
    setError('');
    try { await fn(); setNotice(ok); } catch (e) { setError(errText(e, 'Action failed.')); } finally { onChanged(); }
  }

  const byDay: Record<string, Post[]> = {};
  for (const p of shown) {
    const key = p.scheduled_at || p.published_at ? new Date((p.published_at && filter === 'published' ? p.published_at : p.scheduled_at) || p.published_at!).toDateString() : 'Unscheduled';
    (byDay[key] ||= []).push(p);
  }

  return (
    <GlassCard className="p-5">
      <div className="flex gap-1.5 mb-4 flex-wrap">
        {([['upcoming', 'Scheduled'], ['drafts', 'Drafts'], ['published', 'Published'], ['problems', 'Needs attention']] as const).map(([k, label]) => (
          <button key={k} onClick={() => setFilter(k)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold border ${filter === k ? 'bg-steel/20 border-steel/40 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/55'}`}>
            {label}
          </button>
        ))}
      </div>
      {shown.length === 0 && <p className="text-sm text-ice/45">Nothing here yet.</p>}
      <div className="space-y-5">
        {Object.entries(byDay).map(([day, items]) => (
          <div key={day}>
            <p className="text-[11px] uppercase tracking-wide text-ice/40 mb-2">{day}</p>
            <div className="space-y-2">
              {items.map((p) => (
                <div key={p.id} className="p-3 rounded-xl bg-navy/60 border border-ocean/25">
                  <div className="flex flex-wrap items-center gap-2 mb-1.5">
                    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold capitalize ${STATUS_STYLE[p.status] || ''}`}>{p.status.replace('_', ' ')}</span>
                    {p.source === 'autopilot' && <span className="text-[10px] px-2 py-0.5 rounded-full border bg-violet-500/10 text-violet-300 border-violet-500/25">autopilot</span>}
                    <span className="text-[11px] text-ice/45">{p.account_id ? names[p.account_id] || 'account' : 'no account'}</span>
                    <span className="text-[11px] text-ice/45 ml-auto">{p.status === 'published' ? `Published ${formatDateTime(p.published_at)}` : p.scheduled_at ? formatDateTime(p.scheduled_at) : ''}</span>
                  </div>
                  <p className="text-sm text-ice/75 line-clamp-3 whitespace-pre-line">{p.commentary || <em className="text-ice/40">(media only)</em>}</p>
                  {p.error && p.status !== 'published' && <p className="text-[11px] text-rose-300 mt-1">{p.error}</p>}
                  <div className="flex flex-wrap gap-2 mt-2">
                    {['draft', 'scheduled', 'failed', 'needs_reconnect', 'cancelled'].includes(p.status) && (
                      <button onClick={() => onEdit(p)} className="text-xs text-steel hover:text-offwhite">Edit / reschedule</button>
                    )}
                    {['draft', 'scheduled', 'failed'].includes(p.status) && (
                      <button onClick={() => act(() => api.post(`/api/linkedin/posts/${p.id}/publish-now`), 'Published on LinkedIn.')} className="text-xs text-emerald-300 hover:text-emerald-200">Post now</button>
                    )}
                    {['scheduled', 'failed', 'needs_reconnect', 'draft'].includes(p.status) && (
                      <button onClick={() => act(() => api.post(`/api/linkedin/posts/${p.id}/cancel`), 'Cancelled.')} className="text-xs text-ice/50 hover:text-offwhite">Cancel</button>
                    )}
                    {p.post_url && <a href={p.post_url} target="_blank" rel="noopener noreferrer" className="text-xs text-sky-300 inline-flex items-center gap-1">View on LinkedIn <ExternalLink className="w-3 h-3" /></a>}
                    <button onClick={() => window.confirm(p.status === 'published' ? 'Delete this post from LinkedIn too?' : 'Delete this post?') && act(() => api.delete(`/api/linkedin/posts/${p.id}`), 'Deleted.')}
                            className="text-xs text-rose-300/80 hover:text-rose-300 inline-flex items-center gap-1 ml-auto"><Trash2 className="w-3 h-3" /> Delete</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

function AutopilotPanel({ accounts, setError, setNotice, onChanged }: {
  accounts: Account[]; setError: (s: string) => void; setNotice: (s: string) => void; onChanged: () => void;
}) {
  const [cfg, setCfg] = useState<Autopilot | null>(null);
  const [pillars, setPillars] = useState('');
  const [consent, setConsent] = useState(false);
  const [newTime, setNewTime] = useState('09:30');
  const [newDays, setNewDays] = useState<number[]>([0, 2, 4]);
  const [busy, setBusy] = useState('');

  useEffect(() => {
    api.get('/api/linkedin/autopilot').then((r) => {
      const c: Autopilot = r.data;
      if (!c.timezone || c.timezone === 'Asia/Kolkata') {
        try { c.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Kolkata'; } catch { /* keep */ }
      }
      setCfg(c);
      setPillars((c.pillars || []).join('\n'));
    }).catch((e) => setError(errText(e, 'Could not load autopilot.')));
  }, [setError]);

  if (!cfg) return <GlassCard className="p-5"><p className="text-sm text-ice/50">Loading…</p></GlassCard>;
  const set = (patch: Partial<Autopilot>) => setCfg({ ...cfg, ...patch });

  function addSlots() {
    const add = newDays.map((d) => ({ dow: d, time: newTime }));
    const merged = [...cfg!.slots, ...add].filter((s, i, arr) => arr.findIndex((x) => x.dow === s.dow && x.time === s.time) === i)
      .sort((a, b) => a.dow - b.dow || a.time.localeCompare(b.time));
    set({ slots: merged });
  }

  async function save() {
    setError(''); setBusy('save');
    try {
      const r = await api.put('/api/linkedin/autopilot', {
        enabled: cfg!.enabled, auto_approve: cfg!.auto_approve, consent, account_id: cfg!.account_id || accounts[0]?.id || null,
        timezone: cfg!.timezone, slots: cfg!.slots, pillars: pillars.split('\n').map((p) => p.trim()).filter(Boolean),
        audience: cfg!.audience || null, voice_profile: cfg!.voice_profile || null, lookahead_days: cfg!.lookahead_days || 7,
      });
      setCfg(r.data); setNotice('Autopilot settings saved.');
    } catch (e) {
      setError(errText(e, 'Could not save autopilot.'));
    } finally { setBusy(''); }
  }

  async function runNow() {
    setError(''); setBusy('run');
    try {
      const r = await api.post('/api/linkedin/autopilot/run');
      setNotice(r.data.created ? `Autopilot wrote ${r.data.created} post(s). Check the Queue tab.` : 'All upcoming slots already have posts.');
      onChanged();
    } catch (e) { setError(errText(e, 'Autopilot could not run.')); } finally { setBusy(''); }
  }

  return (
    <GlassCard className="p-5 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-offwhite flex items-center gap-2"><Bot className="w-4 h-4" /> Autopilot</p>
          <p className="text-xs text-ice/50 mt-1 max-w-xl">DeepSeek writes posts for your posting slots from your content topics. By default they wait in the Queue as drafts for your approval.</p>
        </div>
        <label className="inline-flex items-center gap-2 text-sm text-offwhite cursor-pointer">
          <input type="checkbox" checked={cfg.enabled} onChange={(e) => set({ enabled: e.target.checked })} className="w-4 h-4 accent-emerald-500" /> On
        </label>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-xs text-ice/50">Post as</label>
          <select value={cfg.account_id || accounts[0]?.id || ''} onChange={(e) => set({ account_id: e.target.value })} className={inputCls}>
            {accounts.length === 0 && <option value="">Connect a LinkedIn account first</option>}
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <label className="text-xs text-ice/50">Timezone</label>
          <input value={cfg.timezone} onChange={(e) => set({ timezone: e.target.value })} className={inputCls} placeholder="Asia/Kolkata" />
          <label className="text-xs text-ice/50">Plan ahead (days)</label>
          <input type="number" min={1} max={14} value={cfg.lookahead_days} onChange={(e) => set({ lookahead_days: Number(e.target.value) })} className={inputCls} />
        </div>
        <div className="space-y-2">
          <label className="text-xs text-ice/50">Posting days &amp; times</label>
          <div className="flex flex-wrap gap-1">
            {DAYS.map((d, i) => (
              <button key={d} type="button" onClick={() => setNewDays(newDays.includes(i) ? newDays.filter((x) => x !== i) : [...newDays, i])}
                      className={`px-2 py-1 rounded-lg text-xs border ${newDays.includes(i) ? 'bg-steel/20 border-steel/40 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/50'}`}>{d}</button>
            ))}
          </div>
          <div className="flex gap-2">
            <input type="time" value={newTime} onChange={(e) => setNewTime(e.target.value)} className={`${inputCls} w-32`} />
            <button onClick={addSlots} className="px-3 rounded-xl text-xs font-semibold bg-steel/15 text-steel border border-steel/25">Add</button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {cfg.slots.map((s, i) => (
              <span key={i} className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg bg-navy/60 border border-ocean/25 text-ice/70">
                {DAYS[s.dow]} {s.time}
                <button onClick={() => set({ slots: cfg.slots.filter((_, j) => j !== i) })} className="text-ice/40 hover:text-rose-300"><X className="w-3 h-3" /></button>
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label className="text-xs text-ice/50">Content topics (one per line)</label>
          <textarea value={pillars} onChange={(e) => setPillars(e.target.value)} rows={5} className={inputCls}
                    placeholder={'Video editing tips for founders\nBehind the scenes of client projects\nLessons from growing my agency'} />
          <label className="text-xs text-ice/50 mt-2 block">Who you write for</label>
          <input value={cfg.audience || ''} onChange={(e) => set({ audience: e.target.value })} className={inputCls} placeholder="e.g. SaaS founders and marketing leads" />
        </div>
        <div>
          <label className="text-xs text-ice/50">Your voice: paste 1–3 posts you wrote (optional)</label>
          <textarea value={cfg.voice_profile || ''} onChange={(e) => set({ voice_profile: e.target.value })} rows={8} maxLength={3000} className={inputCls}
                    placeholder="AI matches your tone, words and rhythm." />
        </div>
      </div>

      <div className="rounded-xl bg-amber-500/5 border border-amber-500/25 p-4 space-y-2">
        <label className="flex items-start gap-2 text-sm text-offwhite cursor-pointer">
          <input type="checkbox" checked={cfg.auto_approve} onChange={(e) => set({ auto_approve: e.target.checked })} className="w-4 h-4 mt-0.5 accent-amber-500" />
          <span>Publish automatically without my approval</span>
        </label>
        {cfg.auto_approve && !cfg.consent_at && (
          <label className="flex items-start gap-2 text-xs text-amber-200/90 cursor-pointer pl-6">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="w-3.5 h-3.5 mt-0.5 accent-amber-500" />
            <span>I understand AI-written posts will be published on my LinkedIn at my scheduled times without review. I can pause autopilot or cancel any post in the Queue at any time.</span>
          </label>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <LoadingButton isLoading={busy === 'save'} onClick={save}>Save autopilot</LoadingButton>
        <LoadingButton variant="secondary" isLoading={busy === 'run'} disabled={!cfg.enabled} onClick={runNow} icon={<Sparkles className="w-4 h-4" />}>Fill upcoming slots now</LoadingButton>
      </div>
    </GlassCard>
  );
}

export default function LinkedInStudioPage() {
  return (
    <Suspense fallback={<div className="h-96" />}>
      <Studio />
    </Suspense>
  );
}
