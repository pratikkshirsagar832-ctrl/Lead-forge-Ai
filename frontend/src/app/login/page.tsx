'use client';

export const dynamic = 'force-dynamic';

import { useEffect, useState, useSyncExternalStore, Suspense } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { useRouter, useSearchParams } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import api from '@/lib/api';
import {
  Mail, Lock, Eye, EyeOff, Loader2, WifiOff, User, ArrowLeft,
  CheckCircle2, Users, MapPin,
} from 'lucide-react';
import { clearGuestSession } from '@/components/auth/AuthGuard';

type Mode = 'login' | 'signup' | 'forgot' | 'reset';

// Set before a reset email is sent (also read by /auth/callback): a PKCE
// callback carries no `type=recovery`, so this tells the callback to land on
// the "set new password" form.
const RESET_FLAG = 'hc_password_reset';

const TITLES: Record<Mode, { title: string; subtitle: string }> = {
  login: { title: 'Log in', subtitle: 'Welcome back. Your buyers are waiting.' },
  signup: { title: 'Create account', subtitle: 'Start finding people who need your service today.' },
  forgot: { title: 'Reset password', subtitle: "Enter your email and we'll send you a reset link." },
  reset: { title: 'Set a new password', subtitle: 'Choose a password with at least 6 characters.' },
};

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialMode = searchParams.get('mode');
  const [mode, setMode] = useState<Mode>(
    initialMode === 'signup' || initialMode === 'reset' ? initialMode : 'login',
  );
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  // true only once React has hydrated (a tap before that would be a native
  // form submit that reloads the page and wipes the fields on slow phones).
  const hydrated = useSyncExternalStore(() => () => {}, () => true, () => false);

  const authConfigError = searchParams.get('error') === 'auth_config';
  // Only same-site paths (never an open redirect).
  const redirectParam = searchParams.get('redirect') || '';
  const nextPath = redirectParam.startsWith('/') && !redirectParam.startsWith('//') ? redirectParam : '/dashboard';

  useEffect(() => {
    // The reset form NEEDS the recovery session, so never bounce it away.
    if (mode === 'reset') return;
    // Already signed in on this device? Verify with the server first so a
    // revoked/expired session never bounces between /login and /dashboard.
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (!session) return;
      const { data: { user } } = await supabase.auth.getUser();
      if (user) router.replace(nextPath);
      else await supabase.auth.signOut({ scope: 'local' });
    }).catch(() => undefined);
  }, [router, nextPath, mode]);

  const switchMode = (next: Mode) => {
    setMode(next);
    setError('');
    setSuccessMessage('');
    setPassword('');
  };

  const enterGuestMode = () => {
    localStorage.setItem('hyperclients_guest', 'true');
    router.replace('/dashboard');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    setSuccessMessage('');

    // Mobile keyboards capitalise the first letter and add a trailing space.
    const identifier = email.trim();
    const cleanEmail = identifier.toLowerCase();

    try {
      if (mode === 'signup') {
        localStorage.removeItem(RESET_FLAG);
        const { error: signUpError } = await supabase.auth.signUp({
          email: cleanEmail,
          password,
          options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
        });
        if (signUpError) throw signUpError;
        setSuccessMessage('Check your email for the confirmation link!');
        return;
      }

      if (mode === 'forgot') {
        localStorage.setItem(RESET_FLAG, '1');
        const { error: resetError } = await supabase.auth.resetPasswordForEmail(cleanEmail, {
          redirectTo: `${window.location.origin}/auth/callback`,
        });
        if (resetError) throw resetError;
        setSuccessMessage('If an account exists for that email, a reset link is on its way.');
        return;
      }

      if (mode === 'reset') {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) {
          setMode('forgot');
          throw new Error('This reset link has expired. Request a new one below.');
        }
        const { error: updateError } = await supabase.auth.updateUser({ password });
        if (updateError) throw updateError;
        localStorage.removeItem(RESET_FLAG);
        clearGuestSession();
        router.replace('/dashboard');
        return;
      }

      // Team members log in with a USERNAME (no email). Resolve it to the
      // underlying account email first, then sign in with the password.
      let loginEmail = cleanEmail;
      if (!identifier.includes('@')) {
        const { data: resolved } = await api.post('/api/auth/team-resolve', { username: cleanEmail });
        loginEmail = resolved.email;
      }

      const { data, error: signInError } = await supabase.auth.signInWithPassword({
        email: loginEmail,
        password,
      });
      if (signInError) throw signInError;
      if (data?.session) {
        clearGuestSession();
        router.replace(nextPath);
      }
    } catch (err: any) {
      const msg = String(err?.response?.data?.detail || err?.message || '');
      if (/fetch|network|timeout|load failed/i.test(msg)) {
        setError('Network problem - check your connection and try again.');
      } else {
        setError(msg || 'Authentication failed');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    setIsGoogleLoading(true);
    setError('');
    localStorage.removeItem(RESET_FLAG); // a plain login, not a password reset

    try {
      const { error: oAuthError } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
        },
      });
      if (oAuthError) throw oAuthError;
    } catch (err: any) {
      setError(err.message || 'Google login failed');
      setIsGoogleLoading(false);
    }
  };

  const showEmail = mode !== 'reset';
  const showPasswordField = mode !== 'forgot';
  const submitLabel = { login: 'Log in', signup: 'Create account', forgot: 'Send reset link', reset: 'Save password' }[mode];

  return (
    <div className="min-h-screen flex bg-white font-sans">
      {/* ── Form panel ── */}
      <div className="w-full lg:w-[42%] xl:w-[38%] flex flex-col bg-white text-slate-900 px-6 sm:px-12 py-8">
        <Link href="/" className="flex items-center gap-2.5 w-fit" aria-label="Hyperclients home">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-deep">
            <Image src="/hyperclients-icon.png" alt="" width={24} height={24} className="object-contain" />
          </span>
          <span className="font-heading text-xl font-bold tracking-tight">
            <span className="text-brand-teal">Hyper</span><span className="text-secondary-dark">clients</span>
          </span>
        </Link>

        <div className="flex-1 flex items-center">
          <div className="w-full max-w-sm mx-auto lg:mx-0 py-10">
            {(mode === 'forgot' || mode === 'reset') && (
              <button
                type="button"
                onClick={() => switchMode('login')}
                className="mb-6 inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-brand-teal transition-colors"
              >
                <ArrowLeft className="w-4 h-4" /> Back to log in
              </button>
            )}

            <h1 className="font-heading text-3xl font-bold text-brand-deep">{TITLES[mode].title}</h1>
            <p className="mt-2 text-sm text-slate-500">{TITLES[mode].subtitle}</p>

            <form onSubmit={handleSubmit} method="post" action="#" className="mt-8 space-y-5">
              {showEmail && (
                <label className="group block">
                  <span className="sr-only">{mode === 'login' ? 'Email or username' : 'Email address'}</span>
                  <span className="flex items-center gap-3 border-b-2 border-slate-200 pb-2 transition-colors group-focus-within:border-brand-teal">
                    {mode === 'login'
                      ? <User className="w-4 h-4 shrink-0 text-brand-teal" />
                      : <Mail className="w-4 h-4 shrink-0 text-brand-teal" />}
                    <input
                      type={mode === 'login' ? 'text' : 'email'}
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder={mode === 'login' ? 'Email address or username*' : 'Email address*'}
                      required
                      autoComplete={mode === 'login' ? 'username' : 'email'}
                      autoCapitalize="none"
                      autoCorrect="off"
                      spellCheck={false}
                      inputMode="email"
                      className="w-full bg-transparent text-[15px] text-slate-900 placeholder-slate-400 focus:outline-none"
                    />
                  </span>
                </label>
              )}

              {showPasswordField && (
                <label className="group block">
                  <span className="sr-only">{mode === 'reset' ? 'New password' : 'Password'}</span>
                  <span className="flex items-center gap-3 border-b-2 border-slate-200 pb-2 transition-colors group-focus-within:border-brand-teal">
                    <Lock className="w-4 h-4 shrink-0 text-brand-teal" />
                    <input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder={mode === 'reset' ? 'New password*' : 'Password*'}
                      required
                      minLength={6}
                      autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                      className="w-full bg-transparent text-[15px] text-slate-900 placeholder-slate-400 focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      className="shrink-0 text-slate-400 hover:text-slate-600"
                    >
                      {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </span>
                </label>
              )}

              {mode === 'login' && (
                <div className="flex justify-end -mt-1">
                  <button
                    type="button"
                    onClick={() => switchMode('forgot')}
                    className="text-sm font-semibold text-secondary-dark hover:text-brand-teal transition-colors"
                  >
                    Forgot password?
                  </button>
                </div>
              )}

              {successMessage && (
                <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700">{successMessage}</p>
              )}
              {error && (
                <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
              )}

              <button
                type="submit"
                disabled={!hydrated || isLoading}
                className="w-full h-12 inline-flex items-center justify-center rounded-lg bg-brand-accent font-bold text-brand-deep shadow-sm shadow-amber-500/30 transition-all hover:bg-brand-accent-light active:scale-[0.99] disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal focus-visible:ring-offset-2"
              >
                {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : submitLabel}
              </button>
            </form>

            {(mode === 'login' || mode === 'signup') && (
              <>
                <div className="my-6 flex items-center gap-3 text-sm text-slate-400">
                  <span className="h-px flex-1 bg-slate-200" /> or <span className="h-px flex-1 bg-slate-200" />
                </div>

                <button
                  type="button"
                  onClick={handleGoogleLogin}
                  disabled={!hydrated || isGoogleLoading}
                  className="w-full h-12 inline-flex items-center justify-center gap-3 rounded-lg border border-slate-300 bg-white text-[15px] font-semibold text-slate-700 transition-colors hover:bg-slate-50 hover:border-slate-400 disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-teal focus-visible:ring-offset-2"
                >
                  {isGoogleLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : (
                    <>
                      <svg className="w-5 h-5" viewBox="0 0 24 24" aria-hidden="true">
                        <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" />
                        <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                        <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                        <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                      </svg>
                      {mode === 'login' ? 'Log in with Google' : 'Sign up with Google'}
                    </>
                  )}
                </button>

                <p className="mt-6 text-center text-sm text-slate-500">
                  {mode === 'login' ? "Don't have an account? " : 'Already have an account? '}
                  <button
                    type="button"
                    onClick={() => switchMode(mode === 'login' ? 'signup' : 'login')}
                    className="font-semibold text-secondary-dark hover:text-brand-teal transition-colors"
                  >
                    {mode === 'login' ? 'Sign up for free' : 'Log in'}
                  </button>
                </p>
              </>
            )}

            {authConfigError && (
              <div className="mt-6 p-4 rounded-xl bg-amber-50 border border-amber-200">
                <div className="flex items-start gap-3">
                  <WifiOff className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <p className="text-sm font-semibold text-amber-800">Auth service unavailable</p>
                    <p className="text-xs text-amber-700 mt-1 mb-3">
                      Authentication service is temporarily down. Continue as guest to explore the dashboard.
                    </p>
                    <button
                      type="button"
                      onClick={enterGuestMode}
                      className="text-sm font-bold text-amber-900 bg-amber-100 hover:bg-amber-200 border border-amber-300 px-4 py-2 rounded-lg transition-colors"
                    >
                      Continue as Guest
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        <p className="text-xs text-slate-400">
          By continuing, you agree to our{' '}
          <Link href="/terms" className="underline hover:text-slate-600">Terms</Link> and{' '}
          <Link href="/privacy-policy" className="underline hover:text-slate-600">Privacy Policy</Link>.
        </p>
      </div>

      <ShowcasePanel />
    </div>
  );
}

/* ── Right-hand showcase ──────────────────────────────────────────────── */

// Illustrative examples of the buyer-intent posts the engine finds.
const SAMPLE_POSTS = [
  { who: 'Founder, D2C brand', ago: '2h', text: 'Can anyone recommend a good CA for a small startup in Pune? GST filings are eating my weekends.' },
  { who: 'COO, logistics startup', ago: '5h', text: 'Looking for a Shopify developer to rebuild our store before the festive sale. DMs open.' },
  { who: 'Marketing head, SaaS', ago: '1h', text: 'We need a performance marketing agency for Q4. Who have you worked with and loved?' },
  { who: 'Founder, fintech', ago: '3h', text: 'Anyone know a reliable UI/UX designer for a fintech app? Budget approved, starting next week.' },
  { who: 'Creator, 120k subs', ago: '8h', text: 'Hiring a freelance video editor for weekly YouTube content. Drop your portfolio below.' },
  { who: 'Owner, dental clinic', ago: '4h', text: 'Our traffic dropped 40% after the last Google update. Need an SEO expert who actually explains things.' },
  { who: 'Co-founder, US LLC', ago: '6h', text: 'Recommendations for a bookkeeping service that handles a US LLC run from India?' },
  { who: 'Product lead, edtech', ago: '30m', text: 'Looking for someone to build a React Native MVP in 6 weeks. Serious budget, tag people!' },
  { who: 'CEO, consulting firm', ago: '2h', text: 'Any good LinkedIn ghostwriters here? I have ideas but zero time to write.' },
  { who: 'Owner, restaurant chain', ago: '7h', text: 'Our WordPress site is painfully slow. Who can fix page speed without a full rebuild?' },
  { who: 'CTO, healthtech', ago: '1h', text: 'Seeking a cloud consultant to cut our AWS bill. It doubled in 3 months.' },
  { who: 'Founder, skincare brand', ago: '9h', text: 'Can someone suggest a lawyer for trademark registration? Launching in 2 months.' },
];

const FEATURES = [
  {
    icon: Users,
    title: 'LinkedIn Buyer Leads',
    points: ['People asking for your service right now', 'Every post qualified by AI', 'Exactly as many leads as you ask for'],
  },
  {
    icon: MapPin,
    title: 'Google Maps Leads',
    points: ['Local businesses in any city', 'Website analysis on demand', 'Pipeline, notes and CSV export'],
  },
];

function PostCard({ post }: { post: (typeof SAMPLE_POSTS)[number] }) {
  return (
    <div className="rounded-xl bg-white/95 p-4 shadow-lg shadow-black/10">
      <div className="flex items-center gap-2.5">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand-teal/10 text-xs font-bold text-brand-teal">
          {post.who.charAt(0)}
        </span>
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold text-slate-800">{post.who}</p>
          <p className="text-[11px] text-slate-400">{post.ago} ago</p>
        </div>
      </div>
      <p className="mt-3 text-[13px] leading-relaxed text-slate-600">{post.text}</p>
      <span className="mt-3 inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Buyer intent
      </span>
    </div>
  );
}

function ShowcasePanel() {
  // Three columns, each a doubled list so the vertical loop is seamless.
  const columns = [0, 1, 2].map((c) => SAMPLE_POSTS.filter((_, i) => i % 3 === c));

  return (
    <div aria-hidden="true" className="relative hidden lg:flex flex-1 overflow-hidden bg-brand-deep">
      <div className="absolute inset-0 grid grid-cols-3 gap-5 px-6 opacity-80">
        {columns.map((posts, c) => (
          <div key={c} className={c === 1 ? '-mt-40' : c === 2 ? '-mt-16' : ''}>
            <div
              className="flex flex-col gap-5 motion-safe:animate-[login-marquee_linear_infinite]"
              style={{ animationDuration: `${60 + c * 12}s` }}
            >
              {[...posts, ...posts, ...posts, ...posts].map((p, i) => <PostCard key={i} post={p} />)}
            </div>
          </div>
        ))}
      </div>

      {/* Brand wash: teal tint over the wall, deepening toward the bottom. */}
      <div className="absolute inset-0 bg-gradient-to-b from-brand-teal/40 via-brand-teal/70 to-brand-deep" />

      <div className="relative z-10 flex w-full flex-col justify-between p-10 xl:p-14">
        <div />

        <div className="relative mx-auto w-full max-w-2xl">
          <FeatureCard feature={FEATURES[0]} className="w-[62%]" />
          <FeatureCard feature={FEATURES[1]} className="ml-auto -mt-3 w-[58%]" />
        </div>

        <div className="text-center">
          <p className="font-heading text-2xl xl:text-3xl font-bold text-white">
            Find people asking for your service. <span className="text-brand-accent">Right now.</span>
          </p>
          <p className="mt-2 inline-flex items-center gap-2 text-sm text-white/70">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 motion-safe:animate-ping" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>
            Fresh buyer posts, newest first
          </p>
        </div>
      </div>
    </div>
  );
}

function FeatureCard({ feature, className = '' }: { feature: (typeof FEATURES)[number]; className?: string }) {
  const Icon = feature.icon;
  return (
    <div className={`relative rounded-2xl border border-white/10 bg-brand-deep/90 p-6 shadow-2xl shadow-black/40 backdrop-blur ${className}`}>
      <div className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-brand-accent/15 ring-2 ring-brand-accent/40">
          <Icon className="h-5 w-5 text-brand-accent" />
        </span>
        <h2 className="font-heading text-lg font-bold text-white">{feature.title}</h2>
      </div>
      <ul className="mt-4 space-y-2.5">
        {feature.points.map((pt) => (
          <li key={pt} className="flex items-start gap-2.5 text-sm text-white/85">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-brand-accent" />
            {pt}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-white">
        <Loader2 className="w-6 h-6 text-brand-teal animate-spin" />
      </div>
    }>
      <LoginContent />
    </Suspense>
  );
}
