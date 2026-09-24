'use client';

import { useState } from 'react';
import api from '@/lib/api';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import {
  CalendarDays, ClipboardCheck, Megaphone, MessageSquare, Mic, Repeat2, Reply, ScanSearch, UserRound,
} from 'lucide-react';
import { CopyButton, Issue, IssueList, VerdictBadge, errText, inputCls, labelCls } from './shared';

export interface Seed { topic: string; goal?: string; formula?: string; text?: string; nonce: number }

type ToolKey = 'audit' | 'repurpose' | 'hook' | 'plan' | 'profile' | 'interview' | 'comment' | 'replies' | 'advocacy';

const TOOLS: { k: ToolKey; label: string; skill: string; desc: string; Icon: typeof ClipboardCheck }[] = [
  { k: 'audit', label: 'Check a post', skill: 'humanizer · post-audit', Icon: ClipboardCheck,
    desc: 'Paste any post and get a ready / fix-first verdict with exact fixes.' },
  { k: 'plan', label: 'Plan my week', skill: 'content-planner', Icon: CalendarDays,
    desc: 'A 7-day plan: what to post each day, when, and who to comment on.' },
  { k: 'interview', label: 'Interview me', skill: 'interviewer', Icon: Mic,
    desc: 'Answer a few questions; your real stories and numbers are saved so posts sound like you.' },
  { k: 'repurpose', label: 'Repurpose', skill: 'repurposer', Icon: Repeat2,
    desc: 'Turn a blog, tweet, newsletter or video script into a LinkedIn post.' },
  { k: 'hook', label: 'Learn from a viral post', skill: 'hook-extractor', Icon: ScanSearch,
    desc: 'See why a post worked and get the same structure for your topic.' },
  { k: 'comment', label: 'Write a comment', skill: 'comment-drafter', Icon: MessageSquare,
    desc: 'Smart comments on other people\'s posts, or a short take for resharing.' },
  { k: 'replies', label: 'Reply to comments', skill: 'reply-handler', Icon: Reply,
    desc: 'Paste the comments on your post and get a reply for each one worth answering.' },
  { k: 'profile', label: 'Improve my profile', skill: 'profile-optimizer', Icon: UserRound,
    desc: 'Score your profile and get a better headline, About section and more.' },
  { k: 'advocacy', label: 'Team advocacy', skill: 'employee-advocacy', Icon: Megaphone,
    desc: 'A 14-day plan to get your whole team posting on LinkedIn.' },
];

export function SkillsPanel({ onDraft, setError, setNotice }: {
  onDraft: (s: Omit<Seed, 'nonce'>) => void; setError: (s: string) => void; setNotice: (s: string) => void;
}) {
  const [tool, setTool] = useState<ToolKey | null>(null);
  const t = TOOLS.find((x) => x.k === tool);

  if (!t) {
    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {TOOLS.map(({ k, label, desc, Icon }) => (
          <button key={k} onClick={() => setTool(k)}
                  className="text-left flex flex-col items-start justify-start h-full rounded-2xl bg-navy/60 border border-ocean/25 hover:border-steel/50 hover:bg-navy/80 transition-colors p-4">
            <div className="w-9 h-9 rounded-xl bg-sky-500/10 flex items-center justify-center mb-3"><Icon className="w-4.5 h-4.5 text-sky-300" /></div>
            <p className="text-sm font-semibold text-offwhite">{label}</p>
            <p className="text-xs text-ice/55 mt-1 leading-relaxed">{desc}</p>
          </button>
        ))}
      </div>
    );
  }
  return (
    <GlassCard className="p-5 space-y-4">
      <div>
        <button onClick={() => setTool(null)} className="text-xs text-ice/55 hover:text-offwhite mb-2">&larr; All tools</button>
        <h2 className="text-base font-bold text-offwhite flex items-center gap-2"><t.Icon className="w-4 h-4 text-sky-300" /> {t.label}</h2>
        <p className="text-xs text-ice/55 mt-1">{t.desc}</p>
        <p className="text-[10px] text-ice/35 mt-1">Uses your brand profile, voice and story bank · 1 AI credit per run</p>
      </div>
      {tool === 'audit' && <AuditTool setError={setError} />}
      {tool === 'plan' && <PlanTool setError={setError} onDraft={onDraft} />}
      {tool === 'interview' && <InterviewTool setError={setError} setNotice={setNotice} onDraft={onDraft} />}
      {tool === 'repurpose' && <RepurposeTool setError={setError} onDraft={onDraft} />}
      {tool === 'hook' && <HookTool setError={setError} onDraft={onDraft} />}
      {tool === 'comment' && <CommentTool setError={setError} />}
      {tool === 'replies' && <RepliesTool setError={setError} />}
      {tool === 'profile' && <ProfileTool setError={setError} />}
      {tool === 'advocacy' && <AdvocacyTool setError={setError} />}
    </GlassCard>
  );
}

/* ---------------------------------------------------------------- helpers */

function useRun(setError: (s: string) => void) {
  const [busy, setBusy] = useState(false);
  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setError(''); setBusy(true);
    try { return await fn(); } catch (e) { setError(errText(e, 'The AI request failed.')); return undefined; } finally { setBusy(false); }
  }
  return { busy, run };
}

function Box({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-navy/50 border border-ocean/20 p-3">
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-[10px] uppercase tracking-wide text-ice/40 font-semibold">{title}</p>{action}
      </div>
      {children}
    </div>
  );
}

function List({ items }: { items: string[] }) {
  if (!items?.length) return null;
  return <ul className="list-disc pl-4 space-y-0.5 text-xs text-ice/75">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>;
}

function PostCard({ label, text, meta, onUse, extra }: { label: string; text: string; meta?: React.ReactNode; onUse?: () => void; extra?: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-navy/50 border border-ocean/20 p-3 space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-[10px] uppercase tracking-wide text-steel font-semibold">{label}</p>
        <div className="flex items-center gap-3">{meta}<CopyButton text={text} />
          {onUse && <button onClick={onUse} className="text-[11px] font-semibold text-emerald-300 hover:text-emerald-200">Open in composer</button>}
        </div>
      </div>
      <p className="text-xs text-ice/80 whitespace-pre-line leading-relaxed">{text}</p>
      {extra}
    </div>
  );
}

const GOAL_OPTS = [['comments', 'Comments'], ['reposts', 'Reposts'], ['likes', 'Likes'], ['saves', 'Saves'], ['leads', 'Inbound leads']] as const;

/* ------------------------------------------------------------------ tools */

interface AuditRes {
  verdict: string; score: number; summary: string; blockers: Issue[]; warnings: Issue[]; strengths: string[];
  info: { primary_goal: string; timing: string; format: string };
  numbers: { chars: number; words: number; hook_chars: number; em_dashes: number; hashtags: number; fragments: number };
  density: { paragraph: number; markers: number; found: string[] }[];
}

function AuditTool({ setError }: { setError: (s: string) => void }) {
  const [post, setPost] = useState('');
  const [goal, setGoal] = useState('');
  const [res, setRes] = useState<AuditRes | null>(null);
  const { busy, run } = useRun(setError);
  const go = () => run(async () => setRes((await api.post('/api/linkedin/ai/audit', { post, goal })).data));
  return (
    <div className="space-y-3">
      <textarea rows={8} className={inputCls} value={post} onChange={(e) => setPost(e.target.value)} maxLength={3000} placeholder="Paste the draft to audit" />
      <div className="flex flex-wrap gap-2 items-center">
        <select className={`${inputCls} w-auto`} value={goal} onChange={(e) => setGoal(e.target.value)}>
          <option value="">Goal: let the AI judge</option>
          {GOAL_OPTS.map(([v, l]) => <option key={v} value={v}>Goal: {l}</option>)}
        </select>
        <LoadingButton onClick={go} isLoading={busy} disabled={post.trim().length < 10}>Run audit</LoadingButton>
      </div>
      {res && (
        <div className="space-y-3">
          <div className="flex items-center gap-3 flex-wrap">
            <span className={`text-2xl font-bold ${res.verdict === 'pass' ? 'text-emerald-300' : 'text-rose-300'}`}>{res.verdict === 'pass' ? 'PASS' : 'FAIL'}</span>
            <span className="text-sm text-ice/60">score {res.score}/100</span>
            <span className="text-xs text-ice/60">{res.summary}</span>
          </div>
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 text-center">
            {([['chars', 'characters'], ['words', 'words'], ['hook_chars', 'hook chars'], ['em_dashes', 'em dashes'], ['hashtags', 'hashtags'], ['fragments', 'fragments']] as const).map(([k, l]) => (
              <div key={k} className="rounded-lg bg-navy/50 border border-ocean/20 py-1.5">
                <p className="text-sm font-bold text-offwhite">{res.numbers[k]}</p><p className="text-[10px] text-ice/40">{l}</p>
              </div>
            ))}
          </div>
          <Box title="Issues"><IssueList blockers={res.blockers} warnings={res.warnings} /></Box>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Box title="AI-tell density per paragraph">
              <div className="flex flex-wrap gap-1">
                {res.density.map((d) => (
                  <span key={d.paragraph} title={d.found.join(', ')}
                        className={`px-2 py-0.5 rounded text-[11px] font-semibold ${d.markers >= 3 ? 'bg-rose-500/15 text-rose-300' : d.markers === 2 ? 'bg-amber-500/15 text-amber-300' : 'bg-emerald-500/10 text-emerald-300'}`}>
                    ¶{d.paragraph}: {d.markers}
                  </span>
                ))}
              </div>
            </Box>
            <Box title="Timing & format">
              <p className="text-xs text-ice/75">{res.info.timing}</p><p className="text-xs text-ice/60 mt-1">{res.info.format}</p>
              {res.info.primary_goal && <p className="text-[11px] text-ice/45 mt-1">Primary goal: {res.info.primary_goal}</p>}
            </Box>
          </div>
          {res.strengths.length > 0 && <Box title="What works"><List items={res.strengths} /></Box>}
        </div>
      )}
    </div>
  );
}

interface PlanDay {
  day: string; type: string; time: string; pillar: string; format: string; formula: string; angle: string; cta: string;
  goal: string; comment_targets: string[]; comment_pattern: string; comment_count: string; repeat_formula: boolean;
}
function PlanTool({ setError, onDraft }: { setError: (s: string) => void; onDraft: (s: Omit<Seed, 'nonce'>) => void }) {
  const [theme, setTheme] = useState('');
  const [edition, setEdition] = useState<'general' | 'founder'>('general');
  const [ppw, setPpw] = useState(4);
  const [res, setRes] = useState<{ days: PlanDay[]; pillar_mix: { pillar: string; share: string }[]; readiness: { check: string; ok: boolean }[]; notes: string[] } | null>(null);
  const { busy, run } = useRun(setError);
  const go = () => run(async () => setRes((await api.post('/api/linkedin/ai/plan', { theme, days: 7, edition, posts_per_week: ppw })).data));
  return (
    <div className="space-y-3">
      <input className={inputCls} value={theme} onChange={(e) => setTheme(e.target.value)} maxLength={400} placeholder="Theme for the week (optional) - e.g. launch of our new audit service" />
      <div className="flex flex-wrap gap-2 items-center">
        <select className={`${inputCls} w-auto`} value={edition} onChange={(e) => setEdition(e.target.value as 'general' | 'founder')}>
          <option value="general">General pillars (Authority / Narrative / Community)</option>
          <option value="founder">Founder edition (Conviction / Building / Math / Proof)</option>
        </select>
        <select className={`${inputCls} w-auto`} value={ppw} onChange={(e) => setPpw(Number(e.target.value))}>
          {[3, 4, 5].map((n) => <option key={n} value={n}>{n} posts / week</option>)}
        </select>
        <LoadingButton onClick={go} isLoading={busy}>Plan my week</LoadingButton>
      </div>
      {res && (
        <div className="space-y-3">
          {res.pillar_mix.length > 0 && (
            <div className="flex flex-wrap gap-1.5">{res.pillar_mix.map((p) => <span key={p.pillar} className="px-2 py-0.5 rounded-lg bg-steel/15 text-xs text-offwhite">{p.pillar} {p.share}</span>)}</div>
          )}
          <div className="space-y-2">
            {res.days.map((d, i) => (
              <div key={i} className={`rounded-xl border p-3 ${d.type === 'post' ? 'bg-navy/50 border-ocean/25' : 'bg-navy/25 border-ocean/15'}`}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-bold text-offwhite w-10">{d.day}</span>
                  {d.type === 'post' ? (
                    <>
                      <span className="text-[11px] text-ice/50">{d.time}</span>
                      <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300 text-[10px]">{d.pillar}</span>
                      <span className="px-1.5 py-0.5 rounded bg-steel/15 text-[10px] text-offwhite">{d.formula}</span>
                      <span className="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 text-[10px]">goal: {d.goal}</span>
                      <span className="text-[10px] text-ice/45">{d.format}</span>
                      {d.repeat_formula && <span className="text-[10px] text-amber-300">formula repeated</span>}
                      <button onClick={() => onDraft({ topic: d.angle, goal: d.goal, formula: d.formula })}
                              className="ml-auto text-[11px] font-semibold text-emerald-300 hover:text-emerald-200">Draft this post →</button>
                    </>
                  ) : <span className="text-[11px] text-ice/45">Commenting day</span>}
                </div>
                {d.type === 'post' && <p className="text-xs text-ice/80 mt-1.5">{d.angle} <span className="text-ice/45">· CTA: {d.cta}</span></p>}
                {d.comment_targets.length > 0 && (
                  <p className="text-[11px] text-ice/50 mt-1">Comment on: {d.comment_targets.join(' · ')} {d.comment_pattern && `(${d.comment_pattern}`}{d.comment_count && `, ${d.comment_count})`}</p>
                )}
              </div>
            ))}
          </div>
          <Box title="Inbound-readiness check">
            <ul className="space-y-0.5">{res.readiness.map((r, i) => <li key={i} className={`text-xs ${r.ok ? 'text-emerald-300' : 'text-amber-300'}`}>{r.ok ? '✓' : '✗'} {r.check}</li>)}</ul>
          </Box>
          {res.notes.length > 0 && <Box title="Notes"><List items={res.notes} /></Box>}
        </div>
      )}
    </div>
  );
}

interface Question { q: string; section: string; hint: string }
function InterviewTool({ setError, setNotice, onDraft }: { setError: (s: string) => void; setNotice: (s: string) => void; onDraft: (s: Omit<Seed, 'nonce'>) => void }) {
  const [mode, setMode] = useState<'bank' | 'post'>('bank');
  const [topic, setTopic] = useState('');
  const [qs, setQs] = useState<Question[]>([]);
  const [focus, setFocus] = useState('');
  const [answers, setAnswers] = useState<string[]>([]);
  const [res, setRes] = useState<{ entries: { section: string; title: string; detail: string }[]; post_angles: { angle: string; hook: string }[]; spine: string[]; thin_sections: string[]; saved_to_story_bank?: boolean } | null>(null);
  const { busy, run } = useRun(setError);
  const ask = () => run(async () => {
    const r = await api.post('/api/linkedin/ai/interview', { topic: mode === 'post' ? topic : '', mode });
    setQs(r.data.questions); setFocus(r.data.focus); setAnswers(r.data.questions.map(() => '')); setRes(null);
  });
  const digest = () => run(async () => {
    const r = await api.post('/api/linkedin/ai/interview/digest', {
      answers: qs.map((q, i) => ({ q: q.q, a: answers[i] || '' })), mode, topic, save_to_story_bank: true,
    });
    setRes(r.data);
    if (r.data.saved_to_story_bank) setNotice(`Saved ${r.data.entries.length} entries to your story bank.`);
  });
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2 items-center">
        <select className={`${inputCls} w-auto`} value={mode} onChange={(e) => setMode(e.target.value as 'bank' | 'post')}>
          <option value="bank">Build my story bank</option>
          <option value="post">Interview me for one post</option>
        </select>
        {mode === 'post' && <input className={`${inputCls} flex-1 min-w-[200px]`} value={topic} onChange={(e) => setTopic(e.target.value)} maxLength={200} placeholder="Post topic" />}
        <LoadingButton onClick={ask} isLoading={busy && !qs.length} disabled={mode === 'post' && topic.trim().length < 3}>Get questions</LoadingButton>
      </div>
      {focus && <p className="text-xs text-ice/55">{focus}</p>}
      {qs.map((q, i) => (
        <div key={i}>
          <label className={labelCls}>{i + 1}. {q.q} {q.section && <span className="text-ice/35 font-normal">({q.section})</span>}</label>
          <textarea rows={2} className={inputCls} value={answers[i] || ''} onChange={(e) => setAnswers(answers.map((a, j) => j === i ? e.target.value : a))}
                    maxLength={1500} placeholder={q.hint || 'Real numbers, dates and names beat adjectives. Skip anything you prefer not to share.'} />
        </div>
      ))}
      {qs.length > 0 && <LoadingButton onClick={digest} isLoading={busy} disabled={!answers.some((a) => a.trim())}>Save answers to story bank</LoadingButton>}
      {res && (
        <div className="space-y-3">
          <Box title={`Story bank entries${res.saved_to_story_bank ? ' (saved)' : ''}`}>
            <ul className="space-y-1">{res.entries.map((e, i) => <li key={i} className="text-xs text-ice/75"><span className="text-steel font-semibold">[{e.section}] {e.title}:</span> {e.detail}</li>)}</ul>
          </Box>
          {res.spine.length > 0 && (
            <Box title="Post spine" action={<button onClick={() => onDraft({ topic: `${topic}\n\nSpine:\n${res.spine.join('\n')}` })} className="text-[11px] font-semibold text-emerald-300">Draft from spine →</button>}>
              <List items={res.spine} />
            </Box>
          )}
          {res.post_angles.length > 0 && (
            <Box title="Posts this unlocks">
              <ul className="space-y-1">{res.post_angles.map((a, i) => (
                <li key={i} className="text-xs text-ice/75 flex items-center justify-between gap-2">
                  <span>{a.angle} <span className="text-ice/40">({a.hook})</span></span>
                  <button onClick={() => onDraft({ topic: a.angle, formula: a.hook })} className="shrink-0 text-[11px] font-semibold text-emerald-300">Draft →</button>
                </li>))}</ul>
            </Box>
          )}
          {res.thin_sections.length > 0 && <p className="text-[11px] text-ice/45">Still thin: {res.thin_sections.join(', ')} - run the interview again anytime.</p>}
        </div>
      )}
    </div>
  );
}

interface Variant { post: string; hook_style: string; first_comment?: string; chars: number; checks?: { verdict: string; blockers: Issue[]; warnings: Issue[] } }
function VariantCards({ variants, onDraft }: { variants: Variant[]; onDraft: (s: Omit<Seed, 'nonce'>) => void }) {
  return (
    <div className="space-y-2">
      {variants.map((v, i) => (
        <PostCard key={i} label={v.hook_style || `Variant ${i + 1}`} text={v.post}
                  meta={<>{v.checks && <VerdictBadge verdict={v.checks.verdict} />}<span className="text-[10px] text-ice/40">{v.chars} chars</span></>}
                  onUse={() => onDraft({ topic: '', text: v.post })}
                  extra={<>
                    {v.first_comment && <p className="text-[11px] text-ice/55">First comment: {v.first_comment} <CopyButton text={v.first_comment} /></p>}
                    {v.checks && (v.checks.blockers.length + v.checks.warnings.length > 0) && <IssueList blockers={v.checks.blockers} warnings={v.checks.warnings} max={4} />}
                  </>} />
      ))}
    </div>
  );
}

function RepurposeTool({ setError, onDraft }: { setError: (s: string) => void; onDraft: (s: Omit<Seed, 'nonce'>) => void }) {
  const [source, setSource] = useState('');
  const [type, setType] = useState('article');
  const [goal, setGoal] = useState('comments');
  const [res, setRes] = useState<{ spine: string; mapping: { from: string; to: string }[]; variants: Variant[] } | null>(null);
  const { busy, run } = useRun(setError);
  const go = () => run(async () => setRes((await api.post('/api/linkedin/ai/repurpose', { source, source_type: type, goal })).data));
  return (
    <div className="space-y-3">
      <textarea rows={8} className={inputCls} value={source} onChange={(e) => setSource(e.target.value)} maxLength={12000} placeholder="Paste the blog / tweet / thread / newsletter / transcript" />
      <div className="flex flex-wrap gap-2 items-center">
        <select className={`${inputCls} w-auto`} value={type} onChange={(e) => setType(e.target.value)}>
          {['article', 'blog', 'tweet', 'thread', 'newsletter', 'video transcript', 'notes'].map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className={`${inputCls} w-auto`} value={goal} onChange={(e) => setGoal(e.target.value)}>
          {GOAL_OPTS.map(([v, l]) => <option key={v} value={v}>Goal: {l}</option>)}
        </select>
        <LoadingButton onClick={go} isLoading={busy} disabled={source.trim().length < 40}>Repurpose</LoadingButton>
      </div>
      {res && (
        <div className="space-y-3">
          <Box title="Spine kept"><p className="text-xs text-ice/80">{res.spine}</p>
            {res.mapping.length > 0 && <ul className="mt-2 space-y-0.5">{res.mapping.map((m, i) => <li key={i} className="text-[11px] text-ice/55">{m.from} → <span className="text-ice/80">{m.to}</span></li>)}</ul>}
          </Box>
          <VariantCards variants={res.variants} onDraft={onDraft} />
        </div>
      )}
    </div>
  );
}

interface HookRes {
  matches: { formula_id: string; formula_name: string; fit: number }[];
  structure: { hook_lines: string; body: string; close: string; devices: string[] };
  why_it_worked: string[]; template: string; your_version: string; cautions: string[]; injection_flag: string;
}
function HookTool({ setError, onDraft }: { setError: (s: string) => void; onDraft: (s: Omit<Seed, 'nonce'>) => void }) {
  const [post, setPost] = useState('');
  const [res, setRes] = useState<HookRes | null>(null);
  const { busy, run } = useRun(setError);
  const go = () => run(async () => setRes((await api.post('/api/linkedin/ai/hook', { post })).data));
  return (
    <div className="space-y-3">
      <textarea rows={7} className={inputCls} value={post} onChange={(e) => setPost(e.target.value)} maxLength={6000} placeholder="Paste a LinkedIn post that did well" />
      <LoadingButton onClick={go} isLoading={busy} disabled={post.trim().length < 10}>Analyze hook</LoadingButton>
      {res && (
        <div className="space-y-3">
          {res.injection_flag && <p className="text-xs text-amber-300">Heads-up: {res.injection_flag}</p>}
          <div className="flex flex-wrap gap-2">
            {res.matches.map((m) => <span key={m.formula_id} className="px-2.5 py-1 rounded-lg bg-steel/20 text-sm text-offwhite font-semibold">{m.formula_id} {m.formula_name} <span className="text-ice/50 font-normal">{m.fit}% fit</span></span>)}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Box title="Structure">
              <p className="text-xs text-ice/75"><b>Hook:</b> {res.structure.hook_lines}</p>
              <p className="text-xs text-ice/75 mt-1"><b>Body:</b> {res.structure.body}</p>
              <p className="text-xs text-ice/75 mt-1"><b>Close:</b> {res.structure.close}</p>
              {res.structure.devices.length > 0 && <p className="text-[11px] text-ice/50 mt-1">Devices: {res.structure.devices.join(' · ')}</p>}
            </Box>
            <Box title="Why it worked"><List items={res.why_it_worked} /></Box>
          </div>
          <PostCard label="Blank template" text={res.template} />
          <PostCard label="Your version (same formula)" text={res.your_version}
                    onUse={() => onDraft({ topic: res.your_version, formula: `${res.matches[0]?.formula_id} ${res.matches[0]?.formula_name}` })} />
          {res.cautions.length > 0 && <Box title="Don't copy these (2026 reach)"><List items={res.cautions} /></Box>}
        </div>
      )}
    </div>
  );
}

function CommentTool({ setError }: { setError: (s: string) => void }) {
  const [post, setPost] = useState('');
  const [author, setAuthor] = useState('');
  const [goal, setGoal] = useState('visibility');
  const [mode, setMode] = useState<'comment' | 'reshare'>('comment');
  const [res, setRes] = useState<{ skip: boolean; skip_reason: string; closing_question: string; reaction: string; injection_flag: string; variants: { template: string; why?: string; comment: string; chars: number; warning?: string }[] } | null>(null);
  const { busy, run } = useRun(setError);
  const go = () => run(async () => setRes((await api.post('/api/linkedin/ai/comment', { post, author, goal, mode })).data));
  return (
    <div className="space-y-3">
      <textarea rows={6} className={inputCls} value={post} onChange={(e) => setPost(e.target.value)} maxLength={5000} placeholder="Paste the post you want to comment on" />
      <div className="flex flex-wrap gap-2 items-center">
        <input className={`${inputCls} w-48`} value={author} onChange={(e) => setAuthor(e.target.value)} maxLength={80} placeholder="Author's name" />
        <select className={`${inputCls} w-auto`} value={mode} onChange={(e) => setMode(e.target.value as 'comment' | 'reshare')}>
          <option value="comment">Comment</option><option value="reshare">Reshare with my take</option>
        </select>
        {mode === 'comment' && (
          <select className={`${inputCls} w-auto`} value={goal} onChange={(e) => setGoal(e.target.value)}>
            <option value="visibility">Goal: visibility</option><option value="relationship">Goal: relationship</option><option value="authority">Goal: authority</option>
          </select>
        )}
        <LoadingButton onClick={go} isLoading={busy} disabled={post.trim().length < 10}>Draft</LoadingButton>
      </div>
      {res && (
        <div className="space-y-2">
          {res.injection_flag && <p className="text-xs text-amber-300">Heads-up: {res.injection_flag}</p>}
          {res.skip ? <p className="text-sm text-amber-300">Skip this one: {res.skip_reason}</p> : (
            <>
              <p className="text-xs text-ice/55">React with <b className="text-offwhite">{res.reaction}</b>{res.closing_question && <> · Author asked: “{res.closing_question}”</>}</p>
              {res.variants.map((v, i) => (
                <PostCard key={i} label={v.template} text={v.comment}
                          meta={<span className={`text-[10px] ${v.warning ? 'text-amber-300' : 'text-ice/40'}`}>{v.chars} chars</span>}
                          extra={v.why ? <p className="text-[11px] text-ice/45">{v.why}</p> : undefined} />
              ))}
              <p className="text-[10px] text-ice/35">Copy and post it on LinkedIn yourself. LinkedIn&apos;s official API only lets apps post to your own feed.</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function RepliesTool({ setError }: { setError: (s: string) => void }) {
  const [post, setPost] = useState('');
  const [raw, setRaw] = useState('');
  const [res, setRes] = useState<{ total: number; filtered: { index: number; name: string; reason: string }[]; drafts: { index: number; name: string; quote: string; template: string; reply: string; chars: number; reaction: string }[]; note: string } | null>(null);
  const { busy, run } = useRun(setError);
  const comments = raw.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean).map((block) => {
    const m = block.match(/^([^:\n]{1,80}):\s*([\s\S]+)$/);
    return m ? { name: m[1].trim(), text: m[2].trim() } : { name: '', text: block };
  }).slice(0, 100);
  const go = () => run(async () => setRes((await api.post('/api/linkedin/ai/replies', { post, comments })).data));
  return (
    <div className="space-y-3">
      <textarea rows={4} className={inputCls} value={post} onChange={(e) => setPost(e.target.value)} maxLength={4000} placeholder="Your post (the one people commented on)" />
      <textarea rows={7} className={inputCls} value={raw} onChange={(e) => setRaw(e.target.value)}
                placeholder={'Paste the comments, one per block:\n\nRiya Mehta: How did you get to 4 days?\n\nKaran: Great post!'} />
      <div className="flex items-center gap-2">
        <LoadingButton onClick={go} isLoading={busy} disabled={post.trim().length < 10 || !comments.length}>Draft replies</LoadingButton>
        <span className="text-[11px] text-ice/45">{comments.length} comment(s)</span>
      </div>
      {res && (
        <div className="space-y-2">
          <p className="text-xs text-ice/55">{res.total} comments · {res.filtered.length} skipped · {res.drafts.length} replies</p>
          {res.filtered.length > 0 && (
            <Box title="Skipped (no reply needed)">
              <ul className="space-y-0.5">{res.filtered.map((f) => <li key={f.index} className={`text-[11px] ${f.reason.includes('inject') ? 'text-amber-300' : 'text-ice/55'}`}>{f.name || `#${f.index + 1}`}: {f.reason}</li>)}</ul>
            </Box>
          )}
          {res.drafts.map((d) => (
            <PostCard key={d.index} label={`${d.name || `#${d.index + 1}`} · ${d.template}`} text={d.reply}
                      meta={<span className="text-[10px] text-ice/40">react {d.reaction} · {d.chars} chars</span>}
                      extra={<p className="text-[11px] text-ice/40">Replying to: “{d.quote}”</p>} />
          ))}
          {res.note && <p className="text-[11px] text-amber-300">{res.note}</p>}
        </div>
      )}
    </div>
  );
}

interface ProfileRes {
  score: number; scorecard: { section: string; status: string; note: string }[]; priority_fixes: string[];
  headlines: string[]; about: string; featured: string[]; experience_bullets: string[]; skills: string[];
  custom_url: string; recommendation_request: string; banner: string; photo: string; expected_uplift: string;
}
const STATUS_CLS: Record<string, string> = {
  pass: 'text-emerald-300', 'needs-work': 'text-amber-300', fail: 'text-rose-300', unknown: 'text-ice/35',
};
function ProfileTool({ setError }: { setError: (s: string) => void }) {
  const [headline, setHeadline] = useState('');
  const [about, setAbout] = useState('');
  const [extra, setExtra] = useState('');
  const [goal, setGoal] = useState('clients');
  const [res, setRes] = useState<ProfileRes | null>(null);
  const { busy, run } = useRun(setError);
  const go = () => run(async () => setRes((await api.post('/api/linkedin/ai/profile', { headline, about, extra, goal })).data));
  return (
    <div className="space-y-3">
      <input className={inputCls} value={headline} onChange={(e) => setHeadline(e.target.value)} maxLength={300} placeholder="Current headline" />
      <textarea rows={5} className={inputCls} value={about} onChange={(e) => setAbout(e.target.value)} maxLength={4000} placeholder="Current About section" />
      <textarea rows={2} className={inputCls} value={extra} onChange={(e) => setExtra(e.target.value)} maxLength={1500} placeholder="Optional: Featured items, experience, skills, photo/banner, custom URL, recommendations" />
      <div className="flex gap-2 items-center">
        <select className={`${inputCls} w-auto`} value={goal} onChange={(e) => setGoal(e.target.value)}>
          <option value="clients">Goal: win clients</option><option value="authority">Goal: authority</option><option value="job">Goal: job search</option>
        </select>
        <LoadingButton onClick={go} isLoading={busy} disabled={!headline.trim() && !about.trim()}>Audit & rewrite</LoadingButton>
      </div>
      {res && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 sm:grid-cols-9 gap-1.5">
            {res.scorecard.map((s) => (
              <div key={s.section} title={s.note} className="rounded-lg bg-navy/50 border border-ocean/20 p-1.5 text-center">
                <p className="text-[10px] text-ice/50">{s.section}</p><p className={`text-[11px] font-semibold ${STATUS_CLS[s.status]}`}>{s.status}</p>
              </div>
            ))}
          </div>
          <Box title={`Priority fixes · score ${res.score}/100`}><List items={res.priority_fixes} />{res.expected_uplift && <p className="text-[11px] text-emerald-300 mt-1">{res.expected_uplift}</p>}</Box>
          {res.headlines.map((h, i) => <PostCard key={i} label={`Headline option ${i + 1} (${h.length}/220)`} text={h} />)}
          <PostCard label="About (rewritten)" text={res.about} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Box title="Featured"><List items={res.featured} /></Box>
            <Box title="Experience bullets"><List items={res.experience_bullets} /></Box>
            <Box title="Skills (pin the first 3)"><p className="text-xs text-ice/75">{res.skills.join(' · ')}</p></Box>
            <Box title="Banner, photo & URL">
              <p className="text-xs text-ice/75">{res.banner}</p><p className="text-xs text-ice/60 mt-1">{res.photo}</p>
              {res.custom_url && <p className="text-xs text-sky-300 mt-1">{res.custom_url}</p>}
            </Box>
          </div>
          {res.recommendation_request && <PostCard label="Recommendation request" text={res.recommendation_request} />}
        </div>
      )}
    </div>
  );
}

interface AdvocacyRes {
  summary: string; launch_plan: { day: string; action: string }[]; operating_model: { step: string; how: string }[];
  cadence: { role: string; posts_per_week: string; comments_per_day: string }[]; review: string[]; never_review: string[];
  guidelines: string[]; metrics: string[]; touchpoints: string; anti_patterns: string[];
}
function AdvocacyTool({ setError }: { setError: (s: string) => void }) {
  const [size, setSize] = useState(8);
  const [goals, setGoals] = useState('');
  const [state, setState] = useState('');
  const [res, setRes] = useState<AdvocacyRes | null>(null);
  const { busy, run } = useRun(setError);
  const go = () => run(async () => setRes((await api.post('/api/linkedin/ai/advocacy', { team_size: size, goals, current_state: state })).data));
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <div><label className={labelCls}>Team size</label><input type="number" min={2} max={500} className={inputCls} value={size} onChange={(e) => setSize(Number(e.target.value) || 2)} /></div>
        <div className="sm:col-span-2"><label className={labelCls}>Goal</label><input className={inputCls} value={goals} onChange={(e) => setGoals(e.target.value)} maxLength={400} placeholder="e.g. pipeline from LinkedIn + hiring" /></div>
      </div>
      <input className={inputCls} value={state} onChange={(e) => setState(e.target.value)} maxLength={300} placeholder="Current state (optional): e.g. 2 people post, the rest are silent" />
      <LoadingButton onClick={go} isLoading={busy} disabled={goals.trim().length < 3}>Build program</LoadingButton>
      {res && (
        <div className="space-y-3">
          <p className="text-sm text-ice/80">{res.summary}</p>
          <Box title="14-day launch"><ul className="space-y-1">{res.launch_plan.map((s, i) => <li key={i} className="text-xs text-ice/75"><span className="text-steel font-semibold">Day {s.day}:</span> {s.action}</li>)}</ul></Box>
          {res.operating_model.length > 0 && <Box title="Operating model"><ul className="space-y-1">{res.operating_model.map((s, i) => <li key={i} className="text-xs text-ice/75"><b>{s.step}:</b> {s.how}</li>)}</ul></Box>}
          <Box title="Cadence by role">
            <table className="w-full text-xs text-ice/75"><tbody>{res.cadence.map((c, i) => <tr key={i} className="border-t border-ocean/15"><td className="py-1">{c.role}</td><td>{c.posts_per_week} posts/wk</td><td>{c.comments_per_day} comments/day</td></tr>)}</tbody></table>
          </Box>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Box title="Marketing reviews"><List items={res.review} /></Box>
            <Box title="Marketing never reviews"><List items={res.never_review} /></Box>
            <Box title="Metrics"><List items={res.metrics} />{res.touchpoints && <p className="text-[11px] text-emerald-300 mt-1">{res.touchpoints}</p>}</Box>
            <Box title="Avoid"><List items={res.anti_patterns} /></Box>
          </div>
          {res.guidelines.length > 0 && <Box title="Guidelines"><List items={res.guidelines} /></Box>}
        </div>
      )}
    </div>
  );
}
