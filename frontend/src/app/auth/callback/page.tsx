'use client';

export const dynamic = 'force-dynamic';

import { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { Loader2 } from 'lucide-react';

function hasGuestSession(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem('hyperclients_guest') === 'true';
}

export default function AuthCallbackPage() {
  const router = useRouter();
  const [error, setError] = useState('');
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    const redirectToLogin = () => {
      if (mountedRef.current) router.replace('/login?error=auth_config');
    };

    const handleCallback = async () => {
      try {
        if (hasGuestSession()) {
          router.replace('/dashboard');
          return;
        }

        const hashParams = new URLSearchParams(window.location.hash.replace('#', '?'));
        const queryParams = new URLSearchParams(window.location.search);

        const code = queryParams.get('code');
        if (code) {
          await supabase.auth.exchangeCodeForSession(code);
          if (mountedRef.current) router.replace('/dashboard');
          return;
        }

        const accessToken = hashParams.get('access_token');
        const refreshToken = hashParams.get('refresh_token');
        if (accessToken && refreshToken) {
          const { error: sessionError } = await supabase.auth.setSession({
            access_token: accessToken,
            refresh_token: refreshToken,
          } as { access_token: string; refresh_token: string });
          if (!sessionError && mountedRef.current) router.replace('/dashboard');
          else redirectToLogin();
          return;
        }

        const { data: { session } } = await supabase.auth.getSession();
        if (mountedRef.current && session) {
          router.replace('/dashboard');
          return;
        }

        redirectToLogin();
      } catch (err) {
        console.error('Auth callback error:', err);
        redirectToLogin();
      }
    };

    handleCallback();
  }, [router]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-navy font-sans">
        <div className="text-center">
           <p className="text-rose-400 mb-4">{String(error)}</p>
          <button
            onClick={() => router.push('/login?error=auth_config')}
            className="px-6 py-2 rounded-lg bg-steel text-offwhite font-semibold hover:opacity-90 transition-opacity"
          >
            Back to Login
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
