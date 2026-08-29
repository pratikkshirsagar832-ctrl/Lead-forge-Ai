'use client';

import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  Globe,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ArrowRight,
  Gauge,
  FileSearch,
  RefreshCw,
} from 'lucide-react';
import { BlogBackground } from '@/components/blog-background';
import { Footer } from '@/components/landing/Footer';
import Header from '@/components/landing/Header';

interface SeoCheck {
  id: string;
  label: string;
  passed: boolean;
  points: number;
  max: number;
  detail: string;
}

interface SeoResult {
  score: number;
  grade: string;
  url: string;
  title: string;
  metaDescription: string;
  wordCount: number;
  checks: SeoCheck[];
}

const GRADE_STYLES: Record<string, { text: string; ring: string; glow: string }> = {
  A: { text: 'text-emerald-400', ring: '#10B981', glow: 'shadow-emerald-500/20' },
  B: { text: 'text-brand-accent-light', ring: '#FFB020', glow: 'shadow-brand-accent/20' },
  C: { text: 'text-amber-400', ring: '#F59E0B', glow: 'shadow-amber-500/20' },
  D: { text: 'text-orange-400', ring: '#FB923C', glow: 'shadow-orange-500/20' },
  F: { text: 'text-rose-400', ring: '#F43F5E', glow: 'shadow-rose-500/20' },
};

const GRADE_LABEL: Record<string, string> = {
  A: 'Excellent',
  B: 'Good',
  C: 'Average',
  D: 'Needs work',
  F: 'Poor',
};

function normalizeUrl(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return '';
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

export default function SeoScoreCheckerPage() {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<SeoResult | null>(null);

  async function runCheck(e?: React.FormEvent) {
    e?.preventDefault();
    const normalized = normalizeUrl(url);
    if (!normalized) {
      setError('Please enter a website URL.');
      return;
    }
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await fetch('/api/tools/seo-score', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: normalized }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.error || 'Something went wrong. Try again.');
        return;
      }
      setResult(data);
    } catch {
      setError('Could not reach the checker. Try again.');
    } finally {
      setLoading(false);
    }
  }

  const gs = result ? GRADE_STYLES[result.grade] || GRADE_STYLES.F : null;
  const circumference = 2 * Math.PI * 64;

  return (
    <div className="relative min-h-screen bg-navy text-ice font-sans overflow-hidden">
      <BlogBackground />
      <Header />
      <div className="container relative z-10 mx-auto px-6 pt-28 pb-20 max-w-4xl">
        <p className="text-xs font-semibold uppercase tracking-widest text-brand-accent-light mb-2 flex items-center gap-2">
          <Gauge className="w-4 h-4" /> Free Website Audit Tool
        </p>
        <h1 className="text-4xl md:text-5xl font-bold text-offwhite font-heading mb-3">
          Website <span className="gradient-text-premium">Audit</span>
        </h1>
        <p className="text-ice/80 text-lg mb-10">
          Paste any website URL and get an instant on-page audit — title, headings, alt text, meta
          tags, robots.txt, sitemap and more. Free, no login required.
        </p>

        <form
          onSubmit={runCheck}
          className="glass-card rounded-2xl p-3 flex flex-col sm:flex-row gap-3 mb-10"
        >
          <div className="flex-1 flex items-center gap-3 bg-navy/50 rounded-xl px-4 border border-steel/20 focus-within:border-brand-accent/50 transition-colors">
            <Globe className="w-4.5 h-4.5 text-ice/40 shrink-0" />
            <input
              type="text"
              inputMode="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com"
              className="w-full bg-transparent py-3.5 text-sm text-offwhite placeholder:text-text-muted/60 outline-none"
              aria-label="Website URL"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="btn-gradient-cyan rounded-xl px-8 py-3.5 text-sm inline-flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-not-allowed shrink-0"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" /> Analyzing…
              </>
            ) : (
              <>
                Check Score <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </form>

        {error && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-start gap-3 glass-card rounded-xl px-5 py-4 border-rose/30 mb-8"
          >
            <AlertTriangle className="w-5 h-5 text-rose shrink-0 mt-0.5" />
            <p className="text-sm text-ice/85">{error}</p>
          </motion.div>
        )}

        {result && gs && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            className="glass-card-premium rounded-2xl overflow-hidden"
          >
            <div className="p-6 md:p-10 grid md:grid-cols-[auto_1fr] gap-8 items-center border-b border-steel/10">
              <div className="relative w-40 h-40 mx-auto md:mx-0">
                <svg viewBox="0 0 160 160" className="w-full h-full -rotate-90">
                  <circle cx="80" cy="80" r="64" fill="none" stroke="rgba(42,53,224,0.15)" strokeWidth="12" />
                  <motion.circle
                    cx="80"
                    cy="80"
                    r="64"
                    fill="none"
                    stroke={gs.ring}
                    strokeWidth="12"
                    strokeLinecap="round"
                    strokeDasharray={circumference}
                    initial={{ strokeDashoffset: circumference }}
                    animate={{ strokeDashoffset: circumference * (1 - result.score / 100) }}
                    transition={{ duration: 1.2, ease: 'easeOut' }}
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-5xl font-bold font-heading text-offwhite">{result.score}</span>
                  <span className={`text-xs font-bold mt-1 ${gs.text}`}>GRADE {result.grade}</span>
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-text-muted mb-1.5">
                  {GRADE_LABEL[result.grade]}
                </p>
                <h2 className="text-2xl md:text-3xl font-bold font-heading text-offwhite mb-3 break-words">
                  {result.title || 'No page title'}
                </h2>
                <p className="text-ice/70 text-sm mb-5 break-words">{result.url}</p>
                {result.metaDescription && (
                  <p className="text-sm text-ice/60 leading-relaxed mb-4">{result.metaDescription}</p>
                )}
                <div className="flex flex-wrap gap-2 text-xs text-text-muted">
                  <span className="px-2.5 py-1 rounded-full bg-ocean/40 border border-steel/15">
                    {result.wordCount.toLocaleString()} words
                  </span>
                  <span className="px-2.5 py-1 rounded-full bg-ocean/40 border border-steel/15">
                    {result.checks.length} checks
                  </span>
                </div>
                <button
                  onClick={runCheck}
                  disabled={loading}
                  className="mt-6 inline-flex items-center gap-2 text-xs font-semibold text-brand-accent hover:text-brand-accent-light transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Re-run check
                </button>
              </div>
            </div>

            <div className="p-6 md:p-10">
              <h3 className="flex items-center gap-2 text-sm font-bold uppercase tracking-widest text-brand-accent-light mb-6">
                <FileSearch className="w-4 h-4" /> Audit Breakdown
              </h3>
              <div className="space-y-4">
                {result.checks.map((check, i) => (
                  <motion.div
                    key={check.id}
                    initial={{ opacity: 0, x: -8 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.5 + i * 0.06, duration: 0.3 }}
                    className="flex items-start gap-4"
                  >
                    {check.passed ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                    ) : check.points > 0 ? (
                      <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                    ) : (
                      <XCircle className="w-5 h-5 text-rose shrink-0 mt-0.5" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-3 mb-1.5">
                        <span className="text-sm font-semibold text-offwhite">{check.label}</span>
                        <span className="text-xs font-bold text-text-muted shrink-0">
                          {check.points}/{check.max}
                        </span>
                      </div>
                      <div className="h-1.5 rounded-full bg-ocean/40 overflow-hidden mb-1.5">
                        <motion.div
                          className="h-full rounded-full"
                          style={{
                            background: check.passed
                              ? 'linear-gradient(90deg, #10B981, #34D399)'
                              : check.points > 0
                                ? 'linear-gradient(90deg, #F59E0B, #FBBF24)'
                                : '#F43F5E',
                          }}
                          initial={{ width: 0 }}
                          animate={{ width: `${(check.points / check.max) * 100}%` }}
                          transition={{ delay: 0.7 + i * 0.06, duration: 0.5, ease: 'easeOut' }}
                        />
                      </div>
                      <p className="text-xs text-ice/55 leading-relaxed break-words">{check.detail}</p>
                    </div>
                  </motion.div>
                ))}
              </div>

              <div className="mt-10 glass-card rounded-2xl p-6 md:p-8">
                <h3 className="text-xl font-bold text-offwhite font-heading mb-2">
                  Want ready-to-buy leads instead of audits?
                </h3>
                <p className="text-ice/80 leading-relaxed text-sm mb-5">
                  Hyperclients finds local businesses with weak or missing websites and scores them by
                  opportunity — so you pitch the ones ready to buy a redesign or website retainer.
                </p>
                <a href="/login" className="btn-gradient-cyan rounded-xl px-6 py-3 text-sm inline-flex items-center gap-2">
                  Try It Free <ArrowRight className="w-4 h-4" />
                </a>
              </div>
            </div>
          </motion.div>
        )}
      </div>
      <Footer />
    </div>
  );
}