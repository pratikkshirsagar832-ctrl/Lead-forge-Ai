'use client';

export const dynamic = 'force-dynamic';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { clearGuestSession } from '@/components/auth/AuthGuard';
import { Loader2 } from 'lucide-react';

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState('');
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return; // the code can only be exchanged once
    ran.current = true;

    const query = new URLSearchParams(window.location.search);
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    // Password-reset links sign the user in with a recovery session; send them
    // to the "set new password" form instead of the dashboard. Implicit links
    // say so in the hash; PKCE links rely on the flag /login set.
    const isRecovery = hash.get('type') === 'recovery' || localStorage.getItem('hc_password_reset') === '1';

    const done = () => {
      // A real login always wins over an old "continue as guest" flag.
      clearGuestSession();
      if (isRecovery) {
        localStorage.removeItem('hc_password_reset');
        router.replace('/login?mode=reset');
        return;
      }
      router.replace('/dashboard');
    };

    (async () => {
      try {
        const providerError = query.get('error_description') || hash.get('error_description');
        if (providerError) {
          setError(providerError);
          return;
        }

        const code = query.get('code');
        if (code) {
          const { error: exchangeError } = await supabase.auth.exchangeCodeForSession(code);
          if (exchangeError) {
            // Already exchanged (e.g. page reloaded) but a session exists: fine.
            const { data: { session } } = await supabase.auth.getSession();
            if (session) return done();
            setError(exchangeError.message || 'Could not complete sign in.');
            return;
          }
          return done();
        }

        const accessToken = hash.get('access_token');
        const refreshToken = hash.get('refresh_token');
        if (accessToken && refreshToken) {
          const { error: sessionError } = await supabase.auth.setSession({
            access_token: accessToken,
            refresh_token: refreshToken,
          });
          if (sessionError) {
            setError(sessionError.message || 'Could not complete sign in.');
            return;
          }
          return done();
        }

        const { data: { session } } = await supabase.auth.getSession();
        if (session) return done();
        setError('This sign-in link has expired or was already used. Please sign in again.');
      } catch (err) {
        console.error('Auth callback error:', err);
        setError('Could not complete sign in. Please check your connection and try again.');
      }
    })();
  }, [router]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-navy font-sans p-4">
        <div className="text-center max-w-sm">
          <p className="text-rose-400 mb-4">{error}</p>
          <button
            onClick={() => router.replace('/login')}
            className="px-6 py-2 rounded-lg bg-steel text-offwhite font-semibold hover:opacity-90 transition-opacity"
          >
            Back to login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-navy font-sans">
      <div className="flex items-center gap-3">
        <Loader2 className="w-6 h-6 text-steel animate-spin" />
        <p className="text-ice/60">Completing sign in...</p>
      </div>
    </div>
  );
}
