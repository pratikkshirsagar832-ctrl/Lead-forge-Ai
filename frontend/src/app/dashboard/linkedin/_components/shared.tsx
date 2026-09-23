'use client';

import { useState } from 'react';
import { AlertCircle, Check, Copy, X } from 'lucide-react';

export const inputCls = 'w-full px-3 py-2 rounded-xl border border-ocean/30 bg-navy/60 text-offwhite text-sm outline-none focus:ring-2 focus:ring-steel/40 placeholder-ice/30';
export const labelCls = 'block text-xs font-semibold text-ice/60 mb-1';

export function errText(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d) && d[0] && typeof d[0] === 'object' && 'msg' in d[0]) return String((d[0] as { msg: string }).msg);
  if (d && typeof d === 'object' && 'message' in d) return String((d as { message: string }).message);
  return fallback;
}

export function Banner({ kind, children, onClose }: { kind: 'ok' | 'error'; children: React.ReactNode; onClose?: () => void }) {
  const cls = kind === 'ok' ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-300' : 'bg-rose-500/10 border-rose-500/25 text-rose-300';
  return (
    <div className={`flex items-start gap-2 p-3 rounded-xl border text-sm ${cls}`}>
      {kind === 'ok' ? <Check className="w-4 h-4 mt-0.5 shrink-0" /> : <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />}
      <div className="flex-1">{children}</div>
      {onClose && <button onClick={onClose} className="opacity-60 hover:opacity-100"><X className="w-4 h-4" /></button>}
    </div>
  );
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button"
            onClick={() => { navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }); }}
            className="inline-flex items-center gap-1 text-[11px] font-semibold text-ice/55 hover:text-offwhite">
      {done ? <Check className="w-3 h-3 text-emerald-300" /> : <Copy className="w-3 h-3" />} {done ? 'Copied' : label}
    </button>
  );
}

/* ---------------------------------------------------- pre-publish checks */

export interface Issue { rule: string; quote: string; fix: string }
export interface Checks { verdict: 'pass' | 'warn' | 'fail'; blockers: Issue[]; warnings: Issue[] }

const VERDICT: Record<string, { cls: string; label: string }> = {
  pass: { cls: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25', label: 'Ready to post' },
  warn: { cls: 'bg-amber-500/10 text-amber-300 border-amber-500/25', label: 'Minor fixes' },
  fail: { cls: 'bg-rose-500/10 text-rose-300 border-rose-500/25', label: 'Fix before posting' },
};

export function VerdictBadge({ verdict }: { verdict: string }) {
  const v = VERDICT[verdict] || VERDICT.warn;
  return <span className={`inline-flex px-2 py-0.5 rounded-md border text-[10px] font-semibold ${v.cls}`}>{v.label}</span>;
}

export function IssueList({ blockers = [], warnings = [], max = 20 }: { blockers?: Issue[]; warnings?: Issue[]; max?: number }) {
  const all = [...blockers.map((i) => ({ ...i, b: true })), ...warnings.map((i) => ({ ...i, b: false }))].slice(0, max);
  if (!all.length) return <p className="text-[11px] text-emerald-300">No issues found.</p>;
  return (
    <ul className="space-y-1.5">
      {all.map((i, k) => (
        <li key={k} className="text-[11px] leading-snug">
          <span className={`font-semibold ${i.b ? 'text-rose-300' : 'text-amber-300'}`}>{i.b ? 'Blocker' : 'Warning'}: {i.rule}</span>
          {i.quote && <span className="text-ice/45"> — “{i.quote}”</span>}
          {i.fix && <span className="block text-ice/65">→ {i.fix}</span>}
        </li>
      ))}
    </ul>
  );
}

export function TagInput({ value, onChange, placeholder, max = 10 }: {
  value: string[]; onChange: (v: string[]) => void; placeholder?: string; max?: number;
}) {
  const [draft, setDraft] = useState('');
  const add = () => {
    const parts = draft.split(',').map((s) => s.trim()).filter(Boolean);
    if (parts.length) onChange([...value, ...parts.filter((p) => !value.includes(p))].slice(0, max));
    setDraft('');
  };
  return (
    <div className="flex flex-wrap gap-1.5 p-1.5 rounded-xl border border-ocean/30 bg-navy/60">
      {value.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 pl-2 pr-1 py-0.5 rounded-lg bg-steel/15 text-xs text-offwhite">
          {t}<button type="button" onClick={() => onChange(value.filter((x) => x !== t))} className="text-ice/50 hover:text-rose-300"><X className="w-3 h-3" /></button>
        </span>
      ))}
      <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={value.length >= max ? '' : placeholder}
             onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(); } }} onBlur={add}
             disabled={value.length >= max}
             className="flex-1 min-w-[120px] bg-transparent text-sm text-offwhite outline-none px-1 placeholder-ice/30" />
    </div>
  );
}

export function Chips<T extends string>({ options, value, onChange }: {
  options: readonly { v: T; label: string }[]; value: T[]; onChange: (v: T[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o.v);
        return (
          <button type="button" key={o.v} onClick={() => onChange(on ? value.filter((x) => x !== o.v) : [...value, o.v])}
                  className={`px-2.5 py-1 rounded-lg text-xs font-semibold border ${on ? 'bg-steel/25 border-steel/50 text-offwhite' : 'bg-navy/60 border-ocean/25 text-ice/55 hover:text-offwhite'}`}>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
