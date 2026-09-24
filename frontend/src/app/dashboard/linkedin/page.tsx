'use client';

import { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import api from '@/lib/api';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { formatDateTime } from '@/lib/utils';
import {
  Bot, CalendarClock, Check, ChevronDown, ClipboardCheck, ExternalLink, FileText, Image as ImageIcon, Layers,
  Lightbulb, Linkedin, Lock, Paperclip, PenLine, RefreshCw, Send, Sparkles, Trash2, UserRound, Wand2, Wrench, X,
} from 'lucide-react';
import { Banner, Checks, CopyButton, IssueList, VerdictBadge, errText, inputCls } from './_components/shared';
import { BrandModal, BrandTab } from './_components/BrandProfile';
import { Seed, SkillsPanel } from './_components/SkillsPanel';

/* ----------------------------------------------------------------- types */

interface Account {
  id: string; kind: 'person' | 'organization'; name: string | null; avatar_url: string | null;
  app: string; status: string; days_left: number | null; needs_reconnect_soon: boolean;
}
interface PlanInfo { plan_id: string; enabled: boolean; limit: number; used: number; scheduled: number; remaining: number }
interface Status { plan: PlanInfo; accounts: Account[]; brand_complete: boolean; member_app_configured: boolean; pages_enabled: boolean }
interface Media { type: 'image' | 'document'; storage_path: string; title: string; alt: string; preview?: string }
interface Post {
  id: string; account_id: string | null; status: string; commentary: string; media: Media[];
  visibility: 'PUBLIC' | 'CONNECTIONS'; scheduled_at: string | null; published_at: string | null;
  post_url: string | null; error: string | null; source: string;
}
interface Slide { title: string; body: string }
type Goal = 'comments' | 'reposts' | 'likes' | 'saves' | 'leads';
const GOALS: [Goal, string][] = [['comments', 'Start a conversation'], ['leads', 'Get inbound leads'], ['saves', 'Teach something (saves)'], ['reposts', 'Reach more people'], ['likes', 'Tell a story']];
interface Variant { hook_style: string; post: string; why?: string; first_comment?: string; chars?: number; checks?: Checks }
interface Autopilot {
  enabled: boolean; auto_approve: boolean; consent_at?: string | null; account_id?: string | null;
  timezone: string; slots: { dow: number; time: string }[]; pillars: string[];
  audience?: string | null; voice_profile?: string | null; lookahead_days: number;
}
type Tab = 'create' | 'queue' | 'autopilot' | 'tools' | 'brand';

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

/* ------------------------------------------------------------------ page */

function Studio() {
  const params = useSearchParams();
  const [status, setStatus] = useState<Status | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<Tab>('create');
  const [brandFor, setBrandFor] = useState<'member' | 'pages' | null>(null);
  const [seed, setSeed] = useState<Seed | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [posts, setPosts] = useState<Post[]>([]);

  // composer state (lives here so "Edit" from the queue can fill it)
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

  async function connect(app: 'member' | 'pages', skipCheck = false) {
    setError('');
    // "On whose behalf" form first: the AI needs it and it records the user's authorization.
    if (!skipCheck && !status?.brand_complete) { setBrandFor(app); return; }
    try {
      const r = await api.get(`/api/linkedin/connect?app=${app}`);
      window.location.href = r.data.url;
    } catch (e) {
      if ((e as { response?: { status?: number } })?.response?.status === 409) { setBrandFor(app); return; }
      setError(errText(e, 'Could not start the LinkedIn connection.'));
    }
  }

  function draftFrom(s: Omit<Seed, 'nonce'>) {
    if (s.text) { setText(s.text); setEditingId(null); }
    setSeed({ ...s, nonce: Date.now() });
    setTab('create');
    window.scrollTo({ top: 0, behavior: 'smooth' });
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
    setTab('create');
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

  const setupDone = !!status?.brand_complete && activeAccounts.length > 0;
  const upcoming = posts.filter((p) => ['scheduled', 'publishing'].includes(p.status)).length;
  const problems = posts.filter((p) => ['failed', 'needs_reconnect'].includes(p.status)).length;

  return (
    <div className="space-y-5 animate-in fade-in duration-500">
      {/* header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-offwhite flex items-center gap-2"><Linkedin className="w-6 h-6 text-sky-400" /> LinkedIn Studio</h1>
          <p className="text-ice/50 text-sm mt-1">Write, schedule and auto-post to LinkedIn with AI.</p>
        </div>
        <div className="flex items-center gap-2">
          {plan && (
            <div className="text-xs text-ice/60 bg-navy/60 border border-ocean/25 rounded-xl px-3 py-2" title="Published this month / monthly limit">
              <span className="text-offwhite font-semibold">{plan.used}</span>/{plan.limit} posts this month
            </div>
          )}
          <button onClick={() => setTab('brand')}
                  className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border ${tab === 'brand' ? 'bg-steel/20 border-steel/40 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/70 hover:text-offwhite'}`}>
            <UserRound className="w-4 h-4" /> Brand &amp; voice
          </button>
        </div>
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

      {brandFor && (
        <BrandModal onClose={() => setBrandFor(null)}
                    onSaved={() => { const app = brandFor; setBrandFor(null); refresh(); connect(app, true); }} />
      )}

      {setupDone
        ? <AccountStrip accounts={status?.accounts || []} pagesEnabled={!!status?.pages_enabled} onConnect={connect} onDisconnect={disconnect} />
        : <SetupSteps brandDone={!!status?.brand_complete} connected={activeAccounts.length > 0}
                      onBrand={() => setBrandFor('member')} onConnect={() => connect('member')} />}

      {/* tabs */}
      <div className="grid grid-cols-4 sm:flex gap-1 p-1 rounded-2xl bg-navy/60 border border-ocean/25 w-full sm:w-fit">
        {([['create', 'Create', PenLine, 0], ['queue', 'Scheduled', CalendarClock, upcoming + problems], ['autopilot', 'Autopilot', Bot, 0],
           ['tools', 'Tools', Wrench, 0]] as const).map(([k, label, Icon, count]) => (
          <button key={k} onClick={() => setTab(k)}
                  className={`inline-flex flex-col sm:flex-row items-center justify-center gap-0.5 sm:gap-2 px-1 sm:px-4 py-1.5 sm:py-2 rounded-xl text-[11px] sm:text-sm font-semibold transition-colors ${tab === k ? 'bg-steel text-offwhite shadow' : 'text-ice/55 hover:text-offwhite'}`}>
            <Icon className="w-4 h-4" /> <span className="inline-flex items-center gap-1">{label}
            {count > 0 && <span className={`text-[10px] px-1.5 rounded-full ${problems && k === 'queue' ? 'bg-rose-500/30 text-rose-100' : 'bg-white/15'}`}>{count}</span>}</span>
          </button>
        ))}
      </div>

      {tab === 'create' && (
        <Composer key={seed?.nonce || 0}
          accounts={activeAccounts} accountId={accountId} setAccountId={setAccountId}
          text={text} setText={setText} media={media} setMedia={setMedia}
          visibility={visibility} setVisibility={setVisibility} when={when} setWhen={setWhen}
          editing={!!editingId} onReset={resetComposer} onSave={save} busy={busy} setError={setError} seed={seed}
          onConnect={() => connect('member')}
        />
      )}
      {tab === 'queue' && <Queue posts={posts} accounts={status?.accounts || []} onEdit={editPost} onChanged={refresh} setError={setError} setNotice={setNotice} onCreate={() => setTab('create')} />}
      {tab === 'autopilot' && <AutopilotPanel accounts={activeAccounts} setError={setError} setNotice={setNotice} onChanged={refresh} />}
      {tab === 'tools' && <SkillsPanel onDraft={draftFrom} setError={setError} setNotice={setNotice} />}
      {tab === 'brand' && <BrandTab setNotice={setNotice} onSaved={refresh} />}
    </div>
  );
}

/* ------------------------------------------------------------ components */

function SetupSteps({ brandDone, connected, onBrand, onConnect }: {
  brandDone: boolean; connected: boolean; onBrand: () => void; onConnect: () => void;
}) {
  const steps = [
    { done: brandDone, title: 'Tell the AI about you', desc: 'Your business, audience and stories. Takes 2 minutes.', action: onBrand, cta: brandDone ? 'Edit' : 'Start' },
    { done: connected, title: 'Connect LinkedIn', desc: 'Secure sign-in with LinkedIn. We only post what you approve.', action: onConnect, cta: 'Connect', locked: !brandDone },
    { done: false, title: 'Write your first post', desc: 'Type a topic below and let the AI write it.', locked: !connected },
  ];
  return (
    <GlassCard className="p-5">
      <p className="text-sm font-semibold text-offwhite mb-3">Get started in 3 steps</p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {steps.map((s, i) => (
          <div key={s.title} className={`rounded-xl border p-4 ${s.done ? 'bg-emerald-500/5 border-emerald-500/25' : s.locked ? 'bg-navy/30 border-ocean/15 opacity-60' : 'bg-navy/60 border-steel/40'}`}>
            <div className="flex items-center gap-2 mb-1">
              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${s.done ? 'bg-emerald-500 text-navy' : 'bg-steel/25 text-offwhite'}`}>
                {s.done ? <Check className="w-3.5 h-3.5" /> : i + 1}
              </span>
              <p className="text-sm font-semibold text-offwhite">{s.title}</p>
            </div>
            <p className="text-xs text-ice/55 mb-3">{s.desc}</p>
            {s.action && !s.locked && (!s.done || i === 0) && (
              <button onClick={s.action}
                      className={`text-xs font-semibold px-3 py-1.5 rounded-lg ${s.done ? 'text-ice/60 hover:text-offwhite' : 'bg-steel text-offwhite hover:bg-steel/80'}`}>
                {s.cta}
              </button>
            )}
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

function AccountStrip({ accounts, pagesEnabled, onConnect, onDisconnect }: {
  accounts: Account[]; pagesEnabled: boolean; onConnect: (a: 'member' | 'pages') => void; onDisconnect: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-ice/45">Posting as</span>
      {accounts.map((a) => (
        <div key={a.id} className="flex items-center gap-2 pl-1 pr-2 py-1 rounded-full bg-navy/60 border border-ocean/25">
          {a.avatar_url
            // eslint-disable-next-line @next/next/no-img-element
            ? <img src={a.avatar_url} alt="" className="w-6 h-6 rounded-full object-cover" />
            : <div className="w-6 h-6 rounded-full bg-sky-500/15 flex items-center justify-center"><Linkedin className="w-3 h-3 text-sky-400" /></div>}
          <span className="text-xs font-semibold text-offwhite">{a.name || 'LinkedIn'}</span>
          <span className={`w-1.5 h-1.5 rounded-full ${a.status === 'active' ? 'bg-emerald-400' : 'bg-rose-400'}`} title={a.status === 'active' ? 'Connected' : 'Reconnect needed'} />
          <button onClick={() => onDisconnect(a.id)} title="Disconnect" className="text-ice/35 hover:text-rose-300"><X className="w-3 h-3" /></button>
        </div>
      ))}
      <button onClick={() => onConnect('member')} className="text-xs text-sky-300 hover:text-sky-200 font-semibold">+ Add account</button>
      {pagesEnabled && <button onClick={() => onConnect('pages')} className="text-xs text-sky-300 hover:text-sky-200 font-semibold">+ Company page</button>}
    </div>
  );
}

type Feedback =
  | { kind: 'check'; data: Checks & { score: number; summary: string; info?: { timing: string } } }
  | { kind: 'improve'; changes: string[]; confidence: string; notes: string };

function Composer(props: {
  accounts: Account[]; accountId: string; setAccountId: (v: string) => void;
  text: string; setText: (v: string) => void; media: Media[]; setMedia: (m: Media[]) => void;
  visibility: 'PUBLIC' | 'CONNECTIONS'; setVisibility: (v: 'PUBLIC' | 'CONNECTIONS') => void;
  when: string; setWhen: (v: string) => void; editing: boolean; onReset: () => void;
  onSave: (a: 'draft' | 'schedule' | 'publish_now') => void; busy: string; setError: (s: string) => void;
  seed: Seed | null; onConnect: () => void;
}) {
  const { text, setText, media, setMedia, setError, seed } = props;
  // a seed (from Tools / the planner) remounts the composer via `key`
  const [topic, setTopic] = useState(seed?.topic?.slice(0, 600) || '');
  const [goal, setGoal] = useState<Goal>(GOALS.find(([v]) => v === seed?.goal)?.[0] || 'comments');
  const [length, setLength] = useState<'short' | 'medium' | 'long'>('medium');
  const [formula, setFormula] = useState(seed?.formula || '');
  const [showOptions, setShowOptions] = useState(false);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [ideas, setIdeas] = useState<{ topic: string; goal: string; why: string }[]>([]);
  const [rewriteOpen, setRewriteOpen] = useState(false);
  const [instruction, setInstruction] = useState('');
  const [aiBusy, setAiBusy] = useState('');
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [firstComment, setFirstComment] = useState('');
  const [liveRaw, setLive] = useState<(Checks & { hook_chars: number }) | null>(null);
  const live = text.trim().length >= 20 ? liveRaw : null;
  const [slides, setSlides] = useState<Slide[]>([]);
  const [deckTitle, setDeckTitle] = useState('');
  const [mode, setMode] = useState<'publish_now' | 'schedule' | 'draft'>(props.editing ? 'schedule' : 'publish_now');
  const account = props.accounts.find((a) => a.id === props.accountId);

  // free, instant rule check (no AI credit) while typing
  useEffect(() => {
    if (text.trim().length < 20) return;
    const t = setTimeout(() => {
      api.post('/api/linkedin/lint', { post: text }).then((r) => setLive(r.data)).catch(() => undefined);
    }, 900);
    return () => clearTimeout(t);
  }, [text]);

  async function run<T>(key: string, fn: () => Promise<T>): Promise<T | undefined> {
    setError(''); setAiBusy(key);
    try { return await fn(); } catch (e) { setError(errText(e, 'The AI request failed.')); return undefined; } finally { setAiBusy(''); }
  }

  const suggest = () => run('topics', async () => {
    const r = await api.post('/api/linkedin/ai/topics', { hint: topic.trim().length >= 3 && !ideas.some((i) => i.topic === topic) ? topic : '' });
    setIdeas(r.data.topics || []);
  });
  const pickIdea = (i: { topic: string; goal: string }) => {
    setTopic(i.topic);
    if (GOALS.some(([v]) => v === i.goal)) setGoal(i.goal as Goal);
  };
  const generate = () => run('draft', async () => {
    const r = await api.post('/api/linkedin/ai/draft', { topic, goal, length, formula, variants: 3 });
    setVariants(r.data.variants || []);
  });
  const improve = () => run('improve', async () => {
    const r = await api.post('/api/linkedin/ai/humanize', { post: text, tier: 'all' });
    setText(r.data.post);
    setFeedback({ kind: 'improve', changes: r.data.changes || [], confidence: r.data.reader_confidence, notes: r.data.notes });
  });
  const check = () => run('check', async () => {
    const r = await api.post('/api/linkedin/ai/audit', { post: text, goal });
    setFeedback({ kind: 'check', data: r.data });
  });
  const rewrite = () => run('rewrite', async () => {
    const r = await api.post('/api/linkedin/ai/rewrite', { post: text, instruction });
    setText(r.data.post); setRewriteOpen(false); setInstruction('');
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
  const pickVariant = (v: Variant) => {
    setText(v.post); setFeedback(null); setFirstComment(v.first_comment || '');
  };

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setError('');
    const next = [...media];
    for (const f of Array.from(files)) {
      if (f.type === 'application/pdf' && next.length) { setError('A PDF carousel must be the only attachment.'); continue; }
      if (f.type.startsWith('image/') && next.some((m) => m.type === 'document')) { setError('Remove the PDF before adding images.'); continue; }
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
  const canPublish = !over && (text.trim().length > 0 || media.length > 0);
  const noAccount = props.accounts.length === 0;
  const primaryLabel = mode === 'publish_now' ? 'Post now' : mode === 'schedule' ? 'Schedule post' : 'Save draft';

  return (
    <div className="grid grid-cols-1 xl:grid-cols-5 gap-4">
      <div className="xl:col-span-3 space-y-4">
        {/* 1. ask the AI */}
        <GlassCard className="p-5 space-y-3">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <label className="text-sm font-semibold text-offwhite flex items-center gap-2"><Sparkles className="w-4 h-4 text-sky-300" /> What do you want to post about?</label>
            <LoadingButton size="sm" variant="secondary" isLoading={aiBusy === 'topics'} onClick={suggest}
                           icon={<Lightbulb className="w-3.5 h-3.5" />} title="Topic ideas from your brand profile and stories">
              {ideas.length ? 'More ideas' : 'Suggest topics'}
            </LoadingButton>
          </div>
          <textarea value={topic} onChange={(e) => setTopic(e.target.value)} rows={2} maxLength={600}
                    placeholder="e.g. 3 mistakes founders make when hiring their first salesperson - or tap Suggest topics"
                    className={`${inputCls} text-[15px]`} />
          {ideas.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[11px] text-ice/50">Ideas from your brand profile - tap one to use it:</p>
              <div className="flex flex-col gap-1.5">
                {ideas.map((i) => (
                  <button key={i.topic} onClick={() => pickIdea(i)} title={i.why}
                          className={`text-left text-xs px-3 py-2 rounded-xl border transition-colors ${topic === i.topic ? 'bg-steel/20 border-steel/50 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/75 hover:border-steel/40 hover:text-offwhite'}`}>
                    {i.topic}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="flex flex-wrap gap-2 items-center">
            <LoadingButton isLoading={aiBusy === 'draft'} disabled={topic.trim().length < 3} onClick={generate} icon={<Sparkles className="w-4 h-4" />}>Write 3 posts</LoadingButton>
            <LoadingButton variant="secondary" isLoading={aiBusy === 'carousel'} disabled={topic.trim().length < 3} onClick={carousel} icon={<Layers className="w-4 h-4" />}>Make a carousel</LoadingButton>
            <button onClick={() => setShowOptions(!showOptions)} className="text-xs text-ice/55 hover:text-offwhite inline-flex items-center gap-1 ml-auto">
              More options <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showOptions ? 'rotate-180' : ''}`} />
            </button>
          </div>
          {showOptions && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1">
              <label className="text-xs text-ice/55">Goal
                <select value={goal} onChange={(e) => setGoal(e.target.value as Goal)} className={`${inputCls} mt-1`}>
                  {GOALS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              <label className="text-xs text-ice/55">Length
                <select value={length} onChange={(e) => setLength(e.target.value as typeof length)} className={`${inputCls} mt-1`}>
                  <option value="short">Short</option>
                  <option value="medium">Medium (recommended)</option>
                  <option value="long">Long</option>
                </select>
              </label>
            </div>
          )}
          {formula && (
            <p className="text-[11px] text-ice/55">Using hook style <b className="text-offwhite">{formula}</b>
              <button onClick={() => setFormula('')} className="ml-2 text-ice/40 hover:text-rose-300">remove</button></p>
          )}
          {variants.length > 0 && (
            <div className="space-y-2 pt-1">
              <p className="text-xs text-ice/55">Pick one to edit:</p>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                {variants.map((v, i) => (
                  <button key={i} onClick={() => pickVariant(v)}
                          className={`text-left p-3 rounded-xl border transition-colors flex flex-col ${text === v.post ? 'bg-steel/15 border-steel/50' : 'bg-navy/60 border-ocean/25 hover:border-steel/40'}`}>
                    <div className="flex items-center justify-between gap-1 mb-1.5">
                      <p className="text-[11px] font-semibold text-offwhite">Option {i + 1}</p>
                      {v.checks && <VerdictBadge verdict={v.checks.verdict} />}
                    </div>
                    <p className="text-xs text-ice/70 line-clamp-6 whitespace-pre-line flex-1">{v.post}</p>
                    <p className="text-[11px] text-emerald-300 font-semibold mt-2">{text === v.post ? 'Selected' : 'Use this'}</p>
                  </button>
                ))}
              </div>
            </div>
          )}
        </GlassCard>

        {/* 2. edit */}
        <GlassCard className="p-5 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-offwhite">{props.editing ? 'Edit post' : 'Your post'}</p>
            <div className="flex items-center gap-3">
              {live && <VerdictBadge verdict={live.verdict} />}
              <span className={`text-xs ${over ? 'text-rose-300' : 'text-ice/45'}`}>{text.length}/{MAX}</span>
              {(props.editing || text) && <button onClick={() => { props.onReset(); setFeedback(null); setVariants([]); }} className="text-xs text-ice/50 hover:text-offwhite">Clear</button>}
            </div>
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={11}
                    placeholder="Write here, or let the AI write it above."
                    className={`${inputCls} font-[inherit] leading-relaxed text-[15px]`} />

          <div className="flex flex-wrap items-center gap-2">
            <LoadingButton size="sm" variant="secondary" isLoading={aiBusy === 'improve'} disabled={text.trim().length < 10} onClick={improve}
                           icon={<Wand2 className="w-3.5 h-3.5" />} title="Remove AI-sounding phrases and tighten the writing">Improve</LoadingButton>
            <LoadingButton size="sm" variant="secondary" isLoading={aiBusy === 'check'} disabled={text.trim().length < 10} onClick={check}
                           icon={<ClipboardCheck className="w-3.5 h-3.5" />} title="Full review before posting">Check</LoadingButton>
            <LoadingButton size="sm" variant="secondary" disabled={text.trim().length < 10} onClick={() => setRewriteOpen(!rewriteOpen)}
                           icon={<RefreshCw className="w-3.5 h-3.5" />}>Rewrite</LoadingButton>
            <label className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-semibold border cursor-pointer bg-ocean/60 border-steel/30 text-ice hover:text-offwhite ${hasDoc ? 'opacity-40 pointer-events-none' : ''}`}>
              <Paperclip className="w-3.5 h-3.5" /> {aiBusy === 'upload' ? 'Uploading…' : 'Add image / PDF'}
              <input type="file" accept="image/jpeg,image/png,image/gif,application/pdf" multiple className="hidden" onChange={(e) => { upload(e.target.files); e.target.value = ''; }} />
            </label>
          </div>
          {rewriteOpen && (
            <div className="flex flex-wrap gap-2">
              {['Shorter', 'More casual', 'Stronger hook', 'More specific'].map((q) => (
                <button key={q} onClick={() => setInstruction(q)} className={`text-xs px-2.5 py-1 rounded-lg border ${instruction === q ? 'bg-steel/25 border-steel/50 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/60'}`}>{q}</button>
              ))}
              <input value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="or describe the change" className={`${inputCls} flex-1 min-w-[160px] py-1.5`} />
              <LoadingButton size="sm" isLoading={aiBusy === 'rewrite'} disabled={instruction.trim().length < 2} onClick={rewrite}>Apply</LoadingButton>
            </div>
          )}

          {/* one feedback panel at a time */}
          {feedback?.kind === 'check' && (
            <div className="rounded-xl bg-navy/40 border border-ocean/20 p-3 space-y-2">
              <div className="flex items-center gap-2">
                <span className={`text-sm font-bold ${feedback.data.verdict === 'pass' ? 'text-emerald-300' : 'text-rose-300'}`}>{feedback.data.verdict === 'pass' ? 'Ready to post' : 'Fix before posting'}</span>
                <span className="text-[11px] text-ice/50">{feedback.data.summary}</span>
                <button onClick={() => setFeedback(null)} className="ml-auto text-ice/40 hover:text-offwhite"><X className="w-3.5 h-3.5" /></button>
              </div>
              <IssueList blockers={feedback.data.blockers} warnings={feedback.data.warnings} max={8} />
              {feedback.data.info?.timing && <p className="text-[11px] text-ice/50">Best time to post: {feedback.data.info.timing}</p>}
            </div>
          )}
          {feedback?.kind === 'improve' && (
            <div className="rounded-xl bg-emerald-500/5 border border-emerald-500/20 p-3">
              <div className="flex items-center gap-2 mb-1">
                <p className="text-xs font-semibold text-emerald-300">Improved - {feedback.changes.length} edit(s)</p>
                <button onClick={() => setFeedback(null)} className="ml-auto text-ice/40 hover:text-offwhite"><X className="w-3.5 h-3.5" /></button>
              </div>
              <ul className="text-[11px] text-ice/55 list-disc pl-5 max-h-28 overflow-y-auto">{feedback.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>
              {feedback.notes && <p className="text-[11px] text-amber-300 mt-1">Tip: {feedback.notes}</p>}
            </div>
          )}
          {!feedback && live && live.blockers.length > 0 && (
            <details className="rounded-xl bg-rose-500/5 border border-rose-500/20 p-3">
              <summary className="text-xs text-rose-300 cursor-pointer">{live.blockers.length} thing(s) to fix before posting</summary>
              <div className="mt-2"><IssueList blockers={live.blockers} warnings={[]} /></div>
            </details>
          )}
          {firstComment && (
            <div className="flex items-start gap-2 rounded-xl bg-sky-500/5 border border-sky-500/20 p-3">
              <p className="text-[11px] text-ice/65 flex-1"><b className="text-sky-300">Put this in the first comment</b> (links get less reach inside the post): {firstComment}</p>
              <CopyButton text={firstComment} />
              <button onClick={() => setFirstComment('')} className="text-ice/40 hover:text-rose-300"><X className="w-3.5 h-3.5" /></button>
            </div>
          )}

          {media.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {media.map((m, i) => (
                <div key={m.storage_path} className="relative flex items-center gap-2 pr-7 pl-2 py-2 rounded-lg bg-navy/60 border border-ocean/25 text-xs text-ice/70">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
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

      {/* 3. preview + publish */}
      <div className="xl:col-span-2 space-y-4 xl:sticky xl:top-4 self-start">
        <Preview text={text} account={account} media={media} />
        <GlassCard className="p-5 space-y-3">
          {noAccount ? (
            <div className="text-center py-2">
              <p className="text-sm text-ice/60 mb-3">Connect LinkedIn to publish.</p>
              <LoadingButton onClick={props.onConnect} icon={<Linkedin className="w-4 h-4" />}>Connect LinkedIn</LoadingButton>
              <div className="mt-3"><LoadingButton variant="secondary" size="sm" isLoading={props.busy === 'draft'} onClick={() => props.onSave('draft')} disabled={!canPublish}>Save as draft</LoadingButton></div>
            </div>
          ) : (
            <>
              <div className="grid grid-cols-3 gap-1 p-1 rounded-xl bg-navy/60 border border-ocean/25">
                {([['publish_now', 'Post now'], ['schedule', 'Schedule'], ['draft', 'Draft']] as const).map(([k, l]) => (
                  <button key={k} onClick={() => setMode(k)}
                          className={`py-1.5 rounded-lg text-xs font-semibold ${mode === k ? 'bg-steel text-offwhite' : 'text-ice/55 hover:text-offwhite'}`}>{l}</button>
                ))}
              </div>
              {mode === 'schedule' && (
                <input type="datetime-local" value={props.when} onChange={(e) => props.setWhen(e.target.value)} className={inputCls} />
              )}
              {props.accounts.length > 1 && (
                <select value={props.accountId} onChange={(e) => props.setAccountId(e.target.value)} className={inputCls}>
                  {props.accounts.map((a) => <option key={a.id} value={a.id}>{a.name} ({a.kind === 'organization' ? 'page' : 'profile'})</option>)}
                </select>
              )}
              <label className="flex items-center gap-2 text-xs text-ice/55 cursor-pointer">
                <input type="checkbox" checked={props.visibility === 'CONNECTIONS'} onChange={(e) => props.setVisibility(e.target.checked ? 'CONNECTIONS' : 'PUBLIC')} className="accent-emerald-500" />
                Only my connections can see it
              </label>
              <LoadingButton fullWidth isLoading={props.busy === mode} onClick={() => props.onSave(mode)}
                             disabled={!canPublish || (mode !== 'draft' && !props.accountId)}
                             icon={mode === 'publish_now' ? <Send className="w-4 h-4" /> : mode === 'schedule' ? <CalendarClock className="w-4 h-4" /> : undefined}>
                {primaryLabel}
              </LoadingButton>
            </>
          )}
        </GlassCard>
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
        {/* eslint-disable-next-line @next/next/no-img-element */}
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
      <p className="text-[10px] text-[#999] mt-3">Only the first ~{SEE_MORE} characters show before &ldquo;…see more&rdquo;, so lead with the hook.</p>
    </div>
  );
}

function Queue({ posts, accounts, onEdit, onChanged, setError, setNotice, onCreate }: {
  posts: Post[]; accounts: Account[]; onEdit: (p: Post) => void; onChanged: () => void;
  setError: (s: string) => void; setNotice: (s: string) => void; onCreate: () => void;
}) {
  const [filter, setFilter] = useState<'upcoming' | 'drafts' | 'published' | 'problems'>('upcoming');
  const names = useMemo(() => Object.fromEntries(accounts.map((a) => [a.id, a.name])), [accounts]);
  const groups = {
    upcoming: posts.filter((p) => ['scheduled', 'publishing'].includes(p.status)),
    drafts: posts.filter((p) => p.status === 'draft'),
    published: posts.filter((p) => p.status === 'published'),
    problems: posts.filter((p) => ['failed', 'needs_reconnect', 'cancelled'].includes(p.status)),
  };
  const shown = [...groups[filter]].sort((a, b) => (filter === 'published' ? -1 : 1) * String(a.scheduled_at || a.published_at || '').localeCompare(String(b.scheduled_at || b.published_at || '')));

  async function act(fn: () => Promise<unknown>, ok: string) {
    setError('');
    try { await fn(); setNotice(ok); } catch (e) { setError(errText(e, 'Action failed.')); } finally { onChanged(); }
  }

  const byDay: Record<string, Post[]> = {};
  for (const p of shown) {
    const key = p.scheduled_at || p.published_at ? new Date((p.published_at && filter === 'published' ? p.published_at : p.scheduled_at) || p.published_at!).toDateString() : 'No date';
    (byDay[key] ||= []).push(p);
  }
  const EMPTY: Record<typeof filter, string> = {
    upcoming: 'Nothing scheduled yet.', drafts: 'No drafts.', published: 'Nothing published yet.', problems: 'All good - nothing needs attention.',
  };

  return (
    <GlassCard className="p-5">
      <div className="flex gap-1.5 mb-4 flex-wrap">
        {([['upcoming', 'Upcoming'], ['drafts', 'Drafts'], ['published', 'Published'], ['problems', 'Needs attention']] as const).map(([k, label]) => (
          <button key={k} onClick={() => setFilter(k)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold border ${filter === k ? 'bg-steel/20 border-steel/40 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/55'}`}>
            {label} <span className="opacity-60">{groups[k].length}</span>
          </button>
        ))}
      </div>
      {shown.length === 0 && (
        <div className="text-center py-10">
          <p className="text-sm text-ice/45 mb-3">{EMPTY[filter]}</p>
          {filter !== 'problems' && <LoadingButton size="sm" onClick={onCreate} icon={<PenLine className="w-3.5 h-3.5" />}>Write a post</LoadingButton>}
        </div>
      )}
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
                    {accounts.length > 1 && <span className="text-[11px] text-ice/45">{p.account_id ? names[p.account_id] || 'account' : 'no account'}</span>}
                    <span className="text-[11px] text-ice/45 ml-auto">{p.status === 'published' ? `Published ${formatDateTime(p.published_at)}` : p.scheduled_at ? formatDateTime(p.scheduled_at) : ''}</span>
                  </div>
                  <p className="text-sm text-ice/75 line-clamp-3 whitespace-pre-line">{p.commentary || <em className="text-ice/40">(media only)</em>}</p>
                  {p.error && p.status !== 'published' && <p className="text-[11px] text-rose-300 mt-1">{p.error}</p>}
                  <div className="flex flex-wrap gap-3 mt-2">
                    {['draft', 'scheduled', 'failed', 'needs_reconnect', 'cancelled'].includes(p.status) && (
                      <button onClick={() => onEdit(p)} className="text-xs text-steel hover:text-offwhite">Edit</button>
                    )}
                    {['draft', 'scheduled', 'failed'].includes(p.status) && (
                      <button onClick={() => act(() => api.post(`/api/linkedin/posts/${p.id}/publish-now`), 'Published on LinkedIn.')} className="text-xs text-emerald-300 hover:text-emerald-200">Post now</button>
                    )}
                    {['scheduled', 'failed', 'needs_reconnect'].includes(p.status) && (
                      <button onClick={() => act(() => api.post(`/api/linkedin/posts/${p.id}/cancel`), 'Cancelled.')} className="text-xs text-ice/50 hover:text-offwhite">Cancel</button>
                    )}
                    {p.post_url && <a href={p.post_url} target="_blank" rel="noopener noreferrer" className="text-xs text-sky-300 inline-flex items-center gap-1">View <ExternalLink className="w-3 h-3" /></a>}
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

const SLOT_PRESETS: { label: string; days: number[]; time: string }[] = [
  { label: '3× a week (Tue, Wed, Thu 9:00)', days: [1, 2, 3], time: '09:00' },
  { label: 'Weekdays 9:00', days: [0, 1, 2, 3, 4], time: '09:00' },
  { label: '2× a week (Tue, Thu 8:30)', days: [1, 3], time: '08:30' },
];

function AutopilotPanel({ accounts, setError, setNotice, onChanged }: {
  accounts: Account[]; setError: (s: string) => void; setNotice: (s: string) => void; onChanged: () => void;
}) {
  const [cfg, setCfg] = useState<Autopilot | null>(null);
  const [pillars, setPillars] = useState('');
  const [consent, setConsent] = useState(false);
  const [custom, setCustom] = useState(false);
  const [newTime, setNewTime] = useState('09:30');
  const [newDays, setNewDays] = useState<number[]>([1, 3]);
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
  const slotsOf = (days: number[], time: string) => days.map((d) => ({ dow: d, time }));
  const sameSlots = (a: { dow: number; time: string }[], b: { dow: number; time: string }[]) =>
    a.length === b.length && a.every((s) => b.some((x) => x.dow === s.dow && x.time === s.time));

  function addSlots() {
    const merged = [...cfg!.slots, ...slotsOf(newDays, newTime)].filter((s, i, arr) => arr.findIndex((x) => x.dow === s.dow && x.time === s.time) === i)
      .sort((a, b) => a.dow - b.dow || a.time.localeCompare(b.time));
    set({ slots: merged });
  }

  async function save(patch: Partial<Autopilot> = {}) {
    setError(''); setBusy('save');
    const c = { ...cfg!, ...patch };
    try {
      const r = await api.put('/api/linkedin/autopilot', {
        enabled: c.enabled, auto_approve: c.auto_approve, consent, account_id: c.account_id || accounts[0]?.id || null,
        timezone: c.timezone, slots: c.slots, pillars: pillars.split('\n').map((p) => p.trim()).filter(Boolean),
        audience: c.audience || null, voice_profile: c.voice_profile || null, lookahead_days: c.lookahead_days || 7,
      });
      setCfg(r.data); setNotice(r.data.enabled ? 'Autopilot is on.' : 'Autopilot saved.');
    } catch (e) {
      setError(errText(e, 'Could not save autopilot.'));
    } finally { setBusy(''); }
  }

  async function runNow() {
    setError(''); setBusy('run');
    try {
      const r = await api.post('/api/linkedin/autopilot/run');
      setNotice(r.data.created ? `Autopilot wrote ${r.data.created} post(s). See the Scheduled tab.` : 'All upcoming slots already have posts.');
      onChanged();
    } catch (e) { setError(errText(e, 'Autopilot could not run.')); } finally { setBusy(''); }
  }

  const preset = SLOT_PRESETS.find((p) => sameSlots(slotsOf(p.days, p.time), cfg.slots));

  return (
    <div className="space-y-4">
      <GlassCard className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-base font-semibold text-offwhite flex items-center gap-2"><Bot className="w-5 h-5 text-sky-300" /> Autopilot</p>
            <p className="text-sm text-ice/55 mt-1 max-w-xl">The AI writes posts for your posting times using your brand profile and topics. You approve each one in the Scheduled tab (unless you turn on auto-publish below).</p>
          </div>
          <button onClick={() => save({ enabled: !cfg.enabled })} disabled={busy === 'save'}
                  className={`shrink-0 relative w-12 h-7 rounded-full transition-colors ${cfg.enabled ? 'bg-emerald-500' : 'bg-ocean/60'}`} aria-label="Toggle autopilot">
            <span className={`absolute top-1 w-5 h-5 rounded-full bg-white transition-all ${cfg.enabled ? 'left-6' : 'left-1'}`} />
          </button>
        </div>
      </GlassCard>

      <GlassCard className="p-5 space-y-3">
        <p className="text-sm font-semibold text-offwhite">1. When should it post?</p>
        <div className="flex flex-wrap gap-2">
          {SLOT_PRESETS.map((p) => (
            <button key={p.label} onClick={() => { setCustom(false); set({ slots: slotsOf(p.days, p.time) }); }}
                    className={`px-3 py-2 rounded-xl text-xs font-semibold border ${preset === p && !custom ? 'bg-steel/25 border-steel/50 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/60 hover:text-offwhite'}`}>{p.label}</button>
          ))}
          <button onClick={() => setCustom(true)}
                  className={`px-3 py-2 rounded-xl text-xs font-semibold border ${custom || (!preset && cfg.slots.length) ? 'bg-steel/25 border-steel/50 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/60 hover:text-offwhite'}`}>Custom</button>
        </div>
        {(custom || (!preset && cfg.slots.length > 0)) && (
          <div className="space-y-2 rounded-xl bg-navy/40 border border-ocean/20 p-3">
            <div className="flex flex-wrap gap-1 items-center">
              {DAYS.map((d, i) => (
                <button key={d} type="button" onClick={() => setNewDays(newDays.includes(i) ? newDays.filter((x) => x !== i) : [...newDays, i])}
                        className={`px-2 py-1 rounded-lg text-xs border ${newDays.includes(i) ? 'bg-steel/20 border-steel/40 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/50'}`}>{d}</button>
              ))}
              <input type="time" value={newTime} onChange={(e) => setNewTime(e.target.value)} className={`${inputCls} w-28 py-1`} />
              <button onClick={addSlots} className="px-3 py-1 rounded-lg text-xs font-semibold bg-steel/15 text-steel border border-steel/25">Add</button>
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
        )}
        <p className="text-[11px] text-ice/40">Times are in {cfg.timezone}.</p>
      </GlassCard>

      <GlassCard className="p-5 space-y-2">
        <p className="text-sm font-semibold text-offwhite">2. What should it write about?</p>
        <textarea value={pillars} onChange={(e) => setPillars(e.target.value)} rows={4} className={inputCls}
                  placeholder={'One topic per line, e.g.\nLessons from growing my agency\nMistakes clients make with their website\nBehind the scenes of our projects'} />
        <p className="text-[11px] text-ice/40">Leave empty to use the topics from your brand profile.</p>
      </GlassCard>

      <GlassCard className="p-5 space-y-3">
        <p className="text-sm font-semibold text-offwhite">3. Approval</p>
        {accounts.length > 1 && (
          <select value={cfg.account_id || accounts[0]?.id || ''} onChange={(e) => set({ account_id: e.target.value })} className={inputCls}>
            {accounts.map((a) => <option key={a.id} value={a.id}>Post as {a.name}</option>)}
          </select>
        )}
        <label className="flex items-start gap-2 text-sm text-offwhite cursor-pointer">
          <input type="checkbox" checked={!cfg.auto_approve} onChange={(e) => set({ auto_approve: !e.target.checked })} className="w-4 h-4 mt-0.5 accent-emerald-500" />
          <span>Ask me to approve every post <span className="text-ice/45">(recommended)</span></span>
        </label>
        {cfg.auto_approve && !cfg.consent_at && (
          <label className="flex items-start gap-2 text-xs text-amber-200/90 cursor-pointer rounded-xl bg-amber-500/5 border border-amber-500/25 p-3">
            <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="w-3.5 h-3.5 mt-0.5 accent-amber-500" />
            <span>I understand AI-written posts will be published on my LinkedIn at the times above without review. I can pause autopilot or cancel any post at any time.</span>
          </label>
        )}
      </GlassCard>

      <div className="flex flex-wrap gap-2">
        <LoadingButton isLoading={busy === 'save'} onClick={() => save()} disabled={cfg.enabled && cfg.slots.length === 0}>Save autopilot</LoadingButton>
        <LoadingButton variant="secondary" isLoading={busy === 'run'} disabled={!cfg.enabled || !accounts.length} onClick={runNow} icon={<Sparkles className="w-4 h-4" />}>Write upcoming posts now</LoadingButton>
      </div>
      {cfg.enabled && cfg.slots.length === 0 && <p className="text-xs text-amber-300">Pick when it should post first.</p>}
    </div>
  );
}

export default function LinkedInStudioPage() {
  return (
    <Suspense fallback={<div className="h-96" />}>
      <Studio />
    </Suspense>
  );
}
