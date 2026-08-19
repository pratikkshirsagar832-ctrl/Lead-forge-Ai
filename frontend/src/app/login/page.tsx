'use client';

export const dynamic = 'force-dynamic';

import { useEffect, useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import Image from 'next/image';
import { supabase } from '@/lib/supabase';
import { Mail, Lock, Eye, EyeOff, Loader2, WifiOff } from 'lucide-react';
import { GlassCard } from '@/components/shared/GlassCard';
import { LoadingButton } from '@/components/shared/LoadingButton';
import { Footer } from '@/components/landing/Footer';
import Header from '@/components/landing/Header';

function LoginContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isGoogleLoading, setIsGoogleLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [mode, setMode] = useState<'login' | 'signup'>('login');

  const authConfigError = searchParams.get('error') === 'auth_config';

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) router.replace('/dashboard');
    });
  }, [router]);

  const enterGuestMode = () => {
    localStorage.setItem('hyperclients_guest', 'true');
    router.replace('/dashboard');
  };

  const handleEmailAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');
    setSuccessMessage('');

    try {
      if (mode === 'signup') {
        const { error: signUpError } = await supabase.auth.signUp({
          email,
          password,
          options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
        });
        if (signUpError) throw signUpError;
        setSuccessMessage('Check your email for the confirmation link!');
        setIsLoading(false);
        return;
      }

      const { data, error: signInError } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (signInError) throw signInError;
      if (data?.session) {
        router.replace('/dashboard');
      }
    } catch (err: any) {
      setError(err.message || 'Authentication failed');
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    setIsGoogleLoading(true);
    setError('');

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

  return (
    <div className="min-h-screen flex flex-col bg-navy font-sans relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-violet/20 via-navy to-navy pointer-events-none" />
      <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.02)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.02)_1px,transparent_1px)] bg-[size:64px_64px] pointer-events-none" />
      <Header />
      <div className="flex-1 flex items-center justify-center p-4 relative z-10">

      <GlassCard className="w-full max-w-md p-8 relative z-10">
        <div className="flex flex-col items-center mb-8">
          <div className="bg-steel/15 rounded-xl p-2 mb-4">
            <Image src="/hyperclients-icon.png" alt="Hyperclients" width={48} height={48} className="object-contain" />
          </div>
          <h1 className="text-2xl font-bold text-offwhite">Welcome to Hyperclients</h1>
          <p className="text-sm text-ice/60 mt-1">AI-powered lead generation</p>
        </div>

        <div className="flex mb-6 bg-ocean/20 rounded-lg p-1">
          <button
            onClick={() => { setMode('login'); setError(''); setSuccessMessage(''); }}
            className={`flex-1 py-2 text-sm font-semibold rounded-md transition-colors ${mode === 'login' ? 'bg-steel text-offwhite' : 'text-ice/60 hover:text-offwhite'}`}
          >
            Sign In
          </button>
          <button
            onClick={() => { setMode('signup'); setError(''); setSuccessMessage(''); }}
            className={`flex-1 py-2 text-sm font-semibold rounded-md transition-colors ${mode === 'signup' ? 'bg-steel text-offwhite' : 'text-ice/60 hover:text-offwhite'}`}
          >
            Sign Up
          </button>
        </div>

        <form onSubmit={handleEmailAuth} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-ice/60 mb-1.5">Email</label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ice/40" />
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-ocean/20 border border-ocean/40 text-ice placeholder-ice/30 text-sm focus:outline-none focus:border-steel focus:ring-1 focus:ring-steel/50 transition-all"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-ice/60 mb-1.5">Password</label>
            <div className="relative">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ice/40" />
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                minLength={6}
                className="w-full pl-10 pr-10 py-2.5 rounded-lg bg-ocean/20 border border-ocean/40 text-ice placeholder-ice/30 text-sm focus:outline-none focus:border-steel focus:ring-1 focus:ring-steel/50 transition-all"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-ice/40 hover:text-ice/60"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>

          {successMessage && (
            <p className="text-sm text-center text-emerald-400">
              {successMessage}
            </p>
          )}
          {error && (
            <p className="text-sm text-center text-rose-400">
              {error}
            </p>
          )}

          <LoadingButton fullWidth type="submit" isLoading={isLoading}>
            {mode === 'login' ? 'Sign In' : 'Create Account'}
          </LoadingButton>
        </form>

        <div className="relative my-6">
          <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-ocean/40" /></div>
          <div className="relative flex justify-center"><span className="px-3 bg-navy text-xs text-ice/40">or continue with</span></div>
        </div>

        <LoadingButton
          fullWidth
          variant="outline"
          onClick={handleGoogleLogin}
          isLoading={isGoogleLoading}
          className="border-ocean/40 text-ice hover:bg-ocean/30"
        >
          <svg className="w-5 h-5 mr-2" viewBox="0 0 24 24"><path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" /><path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" /><path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" /><path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" /></svg>
          Google
        </LoadingButton>

        {authConfigError && (
          <div className="mt-6 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30">
            <div className="flex items-start gap-3">
              <WifiOff className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-amber-300">Auth service unavailable</p>
                <p className="text-xs text-amber-400/70 mt-1 mb-3">
                  Authentication service is temporarily down. Continue as guest to explore the dashboard.
                </p>
                <button
                  onClick={enterGuestMode}
                  className="text-sm font-bold text-offwhite bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 px-4 py-2 rounded-lg transition-all"
                >
                  Continue as Guest
                </button>
              </div>
            </div>
          </div>
        )}

        <p className="text-xs text-center text-ice/40 mt-6">
          By continuing, you agree to our Terms of Service and Privacy Policy.
        </p>
      </GlassCard>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <>
      <Suspense fallback={
        <div className="min-h-screen flex flex-col bg-navy font-sans">
          <Header />
          <div className="flex-1 flex items-center justify-center">
            <Loader2 className="w-6 h-6 text-steel animate-spin" />
          </div>
        </div>
      }>
        <LoginContent />
      </Suspense>
      <Footer />
    </>
  );
}
