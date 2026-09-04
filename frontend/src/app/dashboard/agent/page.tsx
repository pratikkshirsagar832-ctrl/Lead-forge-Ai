'use client';

import { useEffect, useRef, useState } from 'react';
import api from '@/lib/api';
import { API_ROUTES } from '@/lib/constants';
import type {
  AgentChatResponse,
  AgentChatState,
  AgentRun,
  AgentRunDetail,
} from '@/lib/types';
import { GlassCard } from '@/components/shared/GlassCard';
import { Badge } from '@/components/shared/Badge';
import { EmptyState } from '@/components/dashboard/EmptyState';
import { formatDistanceToNow } from 'date-fns';
import {
  Bot,
  Send,
  Linkedin,
  Sparkles,
  MapPin,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Copy,
  ChevronRight,
  Cookie,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import Link from 'next/link';

const LEAD_TYPE_LABELS: Record<string, string> = {
  freelancer_needed: 'Freelancer Needed',
  hiring: 'Hiring',
  agency_wanted: 'Agency Wanted',
};

const COOKIE_GUIDE = {
  title: 'Connect LinkedIn',
  what: 'The agent browses LinkedIn as YOU so it can read posts that are hidden from guests.',
  steps: [
    'Install the Cookie-Editor extension (Chrome/Edge/Firefox).',
    'Log into LinkedIn in that browser (linkedin.com).',
    'Open the page, click the Cookie-Editor icon.',
    'Click Export → Export JSON. Copy the whole JSON array.',
    'Paste it into the cookie box below (or save as sessions/linkedin_cookies.json).',
  ],
  why: "It stays on YOUR device / server. We never ask for your LinkedIn password.",
  does: 'Lets the agent read post & people search results, qualify leads, and save them for you.',
};

function safeDistance(date?: string) {
  if (!date) return '—';
  try {
    return formatDistanceToNow(new Date(date), { addSuffix: true });
  } catch {
    return '—';
  }
}

interface Message {
  role: 'user' | 'agent';
  text: string;
  options?: string[];
  guide?: AgentChatState['guide'];
  run?: AgentRunDetail | null;
  runId?: string;
}

export default function AgentPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [step, setStep] = useState('cookies');
  const [cookieStatus, setCookieStatus] = useState<any>(null);
  const [isThinking, setIsThinking] = useState(false);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [hasSentCookie, setHasSentCookie] = useState(false);

  const scrollToBottom = () => {
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50);
  };

  const fetchChatState = async () => {
    try {
      const { data } = await api.get(API_ROUTES.agent.chat);
      setCookieStatus(data.cookie_status);
      if (data.step === 'cookies' && !messages.length) {
        setStep('cookies');
        setMessages([
          {
            role: 'agent',
            text: data.cookie_status?.configured && !data.cookie_status?.expired
              ? 'Your LinkedIn connection is active. What service are you looking for?'
              : 'To find leads on LinkedIn, first let me connect your account.',
            guide: data.guide || undefined,
          },
        ]);
      }
    } catch (e) {
      // If the chat state can't load, still show a usable welcome so the page
      // is never a blank chat area.
      console.error('Failed to load agent chat state', e);
      if (!messages.length) {
        setMessages([{
          role: 'agent',
          text: 'Hi! I\'m your HyperAgent. Tell me what service you need leads for and I\'ll hunt LinkedIn for you.',
          guide: COOKIE_GUIDE,
        }]);
      }
    }
  };

  const fetchRuns = async () => {
    try {
      setRunsLoading(true);
      const { data } = await api.get(API_ROUTES.agent.runs, { params: { per_page: 20 } });
      const active = (data.items || []).filter((r: AgentRun) =>
        ['queued', 'scraping', 'analyzing'].includes(r.status));
      if (active.length) {
        setRuns(data.items || []);
        startStatusPolling(data.items || []);
      } else {
        setRuns(data.items || []);
      }
    } catch (e) {
      console.error('Failed to load agent runs', e);
    } finally {
      setRunsLoading(false);
    }
  };

  const pollTimers = useRef<any[]>([]);
  const startStatusPolling = async (initial: AgentRun[]) => {
    const active = (initial || runs).filter((r: AgentRun) =>
      ['queued', 'scraping', 'analyzing'].includes(r.status));
    active.forEach((r) => {
      const t = setInterval(async () => {
        try {
          const { data } = await api.get(API_ROUTES.agent.runStatus(r.id));
          setRuns((prev) => prev.map((x) => (x.id === r.id ? { ...x, ...data } : x)));
          if (['completed', 'failed', 'cancelled'].includes(data.status)) clearInterval(t);
          setMessages((prev: Message[]) => prev.map((m) =>
            m.runId === r.id ? { ...m, run: { ...(m.run as any), ...data } } : m));
        } catch (e) {
          clearInterval(t);
        }
      }, 2500);
      pollTimers.current.push(t);
    });
  };

  useEffect(() => {
    fetchChatState();
    fetchRuns();
    return () => pollTimers.current.forEach(clearInterval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSend = async (text?: string) => {
    const value = (text ?? input).trim();
    if (!value || isThinking) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', text: value }]);
    setIsThinking(true);
    scrollToBottom();
    try {
      const { data } = await api.post(API_ROUTES.agent.chat, {
        message: value,
        step,
      });
      setStep(data.next_step || data.step || step);
      const newMessage: Message = {
        role: 'agent',
        text: data.message,
        options: data.options,
        guide: data.guide,
        runId: data.run?.id,
      };
      if (data.run?.id) {
        newMessage.run = data.run as any;
        const { data: detail } = await api.get(API_ROUTES.agent.runStatus(data.run.id));
        newMessage.run = { ...(data.run as any), ...detail };
        fetchRuns();
        startStatusPolling([]);
      }
      setMessages((m) => [...m, newMessage]);
      if (data.guide) setHasSentCookie(true);
    } catch (e: any) {
      setMessages((m) => [...m, {
        role: 'agent',
        text: e?.response?.data?.detail || 'Something went wrong. Please try again.',
      }]);
    } finally {
      setIsThinking(false);
      scrollToBottom();
    }
  };

  const handleCookieSubmit = async (cookiesJson: string) => {
    if (!cookiesJson.trim() || isThinking) return;
    setHasSentCookie(true);
    setMessages((m) => [...m, { role: 'user', text: 'Pasted LinkedIn cookies' }]);
    setIsThinking(true);
    try {
      const { data } = await api.post(API_ROUTES.agent.chat, {
        message: cookiesJson,
        step: 'cookies',
        action: 'submit_cookies',
      });
      setStep(data.next_step || data.step || 'service');
      setMessages((m) => [...m, { role: 'agent', text: data.message, options: data.options }]);
    } catch (e: any) {
      setMessages((m) => [...m, {
        role: 'agent',
        text: e?.response?.data?.detail || 'Could not connect. Please re-export a fresh cookie JSON.',
      }]);
    } finally {
      setIsThinking(false);
      scrollToBottom();
    }
  };

  const copyToClipboardGuide = () => {
    if (navigator.clipboard) navigator.clipboard.writeText('Paste the Cookie-Editor JSON array here');
  };

  // Determine if we're at the cookie step (show the cookie form + guide).
  const needsCookies = step === 'cookies' && !hasSentCookie && (!cookieStatus?.configured || cookieStatus?.expired);

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-primary to-brand-accent flex items-center justify-center shadow-lg shadow-primary/20">
              <Bot className="w-6 h-6 text-offwhite" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-offwhite tracking-tight flex items-center gap-2">
                HyperAgent <Sparkles className="w-5 h-5 text-brand-accent" />
              </h1>
              <p className="text-ice/50 mt-1 text-sm">
                Your autonomous LinkedIn lead-finder. I browse LinkedIn as you, find genuine buyers, and save them to your leads.
              </p>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs">
            <Badge variant={cookieStatus?.configured && !cookieStatus?.expired ? 'success' : 'warning'} dot>
              <span className="flex items-center gap-1.5">
                <Cookie className="w-3.5 h-3.5" />
                {cookieStatus?.expired ? 'Session expired — reconnect' : cookieStatus?.configured ? 'LinkedIn connected' : 'Not connected'}
              </span>
            </Badge>
            <Badge variant="outline" className="text-ice/60">
              <span className="flex items-center gap-1.5"><Linkedin className="w-3.5 h-3.5 text-sky-400" /> LinkedIn</span>
            </Badge>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Chat column */}
        <div className="lg:col-span-2 space-y-4">
          <GlassCard className="p-0 overflow-hidden">
            {/* Chat header */}
            <div className="px-6 py-4 border-b border-ocean/30 flex items-center justify-between bg-gradient-to-r from-primary/10 to-transparent">
              <div className="flex items-center gap-2">
                <div className="relative">
                  <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-brand-accent flex items-center justify-center">
                    <Bot className="w-4 h-4 text-offwhite" />
                  </div>
                  <span className="absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full bg-emerald-500 border-2 border-navy" />
                </div>
                <span className="font-semibold text-offwhite">HyperAgent</span>
                <span className="text-[11px] text-ice/40">· always learning</span>
              </div>
              <button
                onClick={() => {
                  setMessages([]);
                  setStep('cookies');
                  setHasSentCookie(false);
                  fetchChatState();
                }}
                className="flex items-center gap-1.5 text-xs text-ice/50 hover:text-offwhite transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" /> Restart
              </button>
            </div>

            {/* Messages */}
            <div className="p-6 space-y-5 h-[46vh] overflow-y-auto">
              <AnimatePresence>
                {messages.map((msg, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25 }}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div className={`max-w-[85%] flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
                      {msg.role === 'agent' && (
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-brand-accent flex items-center justify-center shrink-0 mt-0.5">
                          <Bot className="w-4 h-4 text-offwhite" />
                        </div>
                      )}
                      <div
                        className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                          msg.role === 'user'
                            ? 'bg-gradient-to-br from-primary to-primary-dark text-offwhite rounded-br-sm'
                            : 'bg-ocean/30 border border-ocean/20 text-ice/90 rounded-bl-sm'
                        }`}
                      >
                        {/* Guide card */}
                        {msg.guide && (
                          <div className="mb-3 rounded-xl border border-brand-accent/30 bg-navy/40 p-4">
                            <div className="flex items-center gap-2 mb-2">
                              <Cookie className="w-4 h-4 text-brand-accent" />
                              <span className="font-semibold text-offwhite">{msg.guide.title}</span>
                            </div>
                            <p className="text-xs text-ice/60 mb-3">{msg.guide.what}</p>
                            <ol className="space-y-1.5">
                              {msg.guide.steps?.map((s, idx) => (
                                <li key={idx} className="flex gap-2 text-xs text-ice/70">
                                  <span className="flex-shrink-0 w-5 h-5 rounded-full bg-brand-accent/15 border border-brand-accent/30 flex items-center justify-center text-[10px] font-bold text-brand-accent">
                                    {idx + 1}
                                  </span>
                                  {s}
                                </li>
                              ))}
                            </ol>
                            {msg.guide.why && (
                              <p className="text-[11px] text-ice/40 mt-3 italic">💡 {msg.guide.why}</p>
                            )}
                            {/* Cookie paste box — always available during the cookie step */}
                            {(step === 'cookies') && (
                              <div className="mt-3">
                                <textarea
                                  placeholder='Paste the Cookie-Editor JSON here (starts with [ ... ])'
                                  className="w-full h-24 px-3 py-2 rounded-lg bg-navy/60 border border-ocean/30 text-xs text-ice/90 placeholder-ice/30 focus:border-steel/50 outline-none"
                                  onChange={(e) => setInput(e.target.value)}
                                />
                                <button
                                  onClick={() => handleCookieSubmit(input)}
                                  disabled={!input.trim() || isThinking}
                                  className="mt-2 inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-primary to-brand-accent text-offwhite text-sm font-semibold disabled:opacity-50 hover:opacity-90 transition-opacity"
                                >
                                  {isThinking ? <Loader2 className="w-4 h-4 animate-spin" /> : <Copy className="w-4 h-4" />}
                                  Connect LinkedIn
                                </button>
                              </div>
                            )}
                          </div>
                        )}

                        {/* Live run status */}
                        {msg.run && (
                          <div className="mb-3 rounded-xl border border-steel/20 bg-navy/40 p-4">
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-xs font-semibold text-offwhite flex items-center gap-2">
                                <Loader2 className="w-3.5 h-3.5 animate-spin text-steel" /> Agent is working…
                              </span>
                              <Badge variant="info" className="text-[10px]">{msg.run.status}</Badge>
                            </div>
                            <p className="text-[11px] text-ice/60 mb-2">{msg.run.message || 'Scanning LinkedIn for qualified leads…'}</p>
                            <div className="h-1.5 rounded-full bg-ocean/30 overflow-hidden">
                              <motion.div
                                className="h-full rounded-full bg-gradient-to-r from-steel to-brand-accent"
                                initial={{ width: 0 }}
                                animate={{ width: `${msg.run.progress_percent || 5}%` }}
                                transition={{ duration: 0.6 }}
                              />
                            </div>
                            <div className="mt-2 flex gap-4 text-[11px] text-ice/60">
                              <span>Found <span className="text-offwhite font-bold">{msg.run.total_results || 0}</span></span>
                              <span>Hot <span className="text-rose-400 font-bold">{msg.run.hot_leads || 0}</span></span>
                              <span>Warm <span className="text-amber-400 font-bold">{msg.run.warm_leads || 0}</span></span>
                            </div>
                          </div>
                        )}

                        {msg.text}
                        {msg.options && (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {msg.options.map((opt) => (
                              <button
                                key={opt}
                                onClick={() => handleSend(opt)}
                                className="px-3 py-1.5 rounded-full bg-steel/10 border border-steel/20 text-steel text-xs font-medium hover:bg-steel/20 transition-colors"
                              >
                                {opt}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </motion.div>
                ))}
                {isThinking && (
                  <div className="flex items-center gap-2 text-ice/40 text-sm">
                    <Loader2 className="w-4 h-4 animate-spin" /> HyperAgent is thinking…
                  </div>
                )}
              </AnimatePresence>
              <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="px-6 py-4 border-t border-ocean/30 bg-navy/20">
              <div className="flex items-center gap-3">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                  placeholder="Type your answer… (e.g. video editing, 10 leads, United States)"
                  className="flex-1 px-4 py-3 rounded-xl bg-navy/60 border border-ocean/30 text-offwhite placeholder-ice/30 outline-none focus:border-steel/50 focus:bg-navy/80 transition-all"
                />
                <button
                  onClick={() => handleSend()}
                  disabled={!input.trim() || isThinking}
                  className="flex items-center gap-2 px-5 py-3 rounded-xl bg-gradient-to-r from-primary to-brand-accent text-offwhite font-semibold disabled:opacity-50 hover:opacity-90 transition-opacity"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </GlassCard>
        </div>

        {/* Runs history column */}
        <div className="space-y-4">
          <GlassCard className="p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-bold text-offwhite text-lg flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-brand-accent" /> Agent Runs
              </h2>
              <Badge variant="outline" className="text-[10px]">HyperAgent</Badge>
            </div>

            {runsLoading ? (
              <div className="flex items-center justify-center py-8 text-ice/40">
                <Loader2 className="w-5 h-5 animate-spin" />
              </div>
            ) : runs.length === 0 ? (
              <EmptyState
                title="No runs yet"
                description="Chat with the agent above to start your first LinkedIn lead hunt."
              />
            ) : (
              <div className="space-y-3">
                {runs.map((run, idx) => {
                  const isActive = ['queued', 'scraping', 'analyzing'].includes(run.status);
                  return (
                    <Link key={run.id} href={`/dashboard/leads?search_id=${run.id}`}>
                      <motion.div
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.25, delay: idx * 0.04 }}
                        className="p-4 rounded-xl border border-ocean/20 bg-navy/30 hover:border-steel/30 hover:bg-ocean/30 transition-all group"
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="font-semibold text-offwhite text-sm truncate">{run.service}</span>
                          <Badge variant={
                            run.status === 'completed' ? 'success' :
                            run.status === 'failed' ? 'error' :
                            run.status === 'cancelled' ? 'outline' : 'info'
                          } className="text-[10px] capitalize">
                            {isActive ? 'Running' : run.status}
                          </Badge>
                        </div>
                        <div className="flex items-center gap-3 text-[11px] text-ice/50 mb-2">
                          {run.lead_type && (
                            <span className="flex items-center gap-1">
                              <Sparkles className="w-3 h-3 text-brand-accent" />
                              {LEAD_TYPE_LABELS[run.lead_type] || run.lead_type}
                            </span>
                          )}
                          <span className="flex items-center gap-1">
                            <MapPin className="w-3 h-3" />
                            {run.country || 'Any'}
                          </span>
                          <span>{safeDistance(run.created_at)}</span>
                        </div>
                        <div className="flex items-center justify-between text-xs">
                          <div className="flex gap-3">
                            <span className="text-ice/50">Found <span className="text-offwhite font-bold">{run.total_results}</span></span>
                            <span className="text-rose-400">{run.hot_leads} hot</span>
                            <span className="text-amber-400">{run.warm_leads} warm</span>
                          </div>
                          <ChevronRight className="w-4 h-4 text-ice/30 group-hover:text-steel group-hover:translate-x-0.5 transition-all" />
                        </div>
                      </motion.div>
                    </Link>
                  );
                })}
              </div>
            )}
          </GlassCard>

          {/* Cookie health card */}
          <GlassCard className="p-5">
            <div className="flex items-center gap-2 mb-2">
              <Cookie className="w-4 h-4 text-brand-accent" />
              <h3 className="font-semibold text-offwhite text-sm">LinkedIn Connection</h3>
            </div>
            <div className="text-xs text-ice/60 space-y-1.5">
              {cookieStatus?.configured && !cookieStatus?.expired ? (
                <>
                  <p className="flex items-center gap-1.5 text-emerald-400"><CheckCircle2 className="w-4 h-4" /> Active</p>
                  <p>Session valid. The agent browses LinkedIn as you.</p>
                </>
              ) : cookieStatus?.expired ? (
                <>
                  <p className="flex items-center gap-1.5 text-rose-400"><AlertTriangle className="w-4 h-4" /> Expired</p>
                  <p>Re-export cookies with Cookie-Editor and reconnect.</p>
                </>
              ) : (
                <>
                  <p className="flex items-center gap-1.5 text-amber-400"><AlertTriangle className="w-4 h-4" /> Not connected</p>
                  <p>No cookies set — the agent runs in guest mode (Jobs + company pages only).</p>
                </>
              )}
            </div>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
