'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { Loader2 } from 'lucide-react';

function isGuestSession(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem('hyperclients_guest') === 'true';
}

function clearGuestSession() {
  if (typeof window !== 'undefined') {
    localStorage.removeItem('hyperclients_guest');
  }
}

export { clearGuestSession };

function Loading({ label }: { label: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-navy font-sans">
      <div className="flex items-center gap-3">
        <Loader2 className="w-6 h-6 text-steel animate-spin" />
        <p className="text-ice/60">{label}</p>
      </div>
    </div>
  );
}

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<'checking' | 'in' | 'out'>('checking');
  const pathRef = useRef(pathname);
  useEffect(() => { pathRef.current = pathname; }, [pathname]);

  // Subscribe ONCE (not on every navigation): the session lives in this
  // browser's storage and Supabase refreshes it in the background.
  useEffect(() => {
    let alive = true;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    const toLogin = () => {
      if (!alive) return;
      setState('out');
      router.replace(`/login?redirect=${encodeURIComponent(pathRef.current || '/dashboard')}`);
    };

    (async () => {
      if (isGuestSession()) { setState('in'); return; }
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!alive) return;
        if (session) { setState('in'); return; }
        // One short re-check covers a session written a moment ago (OAuth
        // callback, another tab signing in) without keeping users waiting.
        retryTimer = setTimeout(async () => {
          const { data: { session: again } } = await supabase.auth.getSession().catch(() => ({ data: { session: null } }));
          if (!alive) return;
          if (again) setState('in'); else toLogin();
        }, 600);
      } catch (err) {
        console.error('AuthGuard: session check failed', err);
        toLogin();
      }
    })();

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (!alive) return;
      if (event === 'SIGNED_OUT') {
        clearGuestSession();
        toLogin();
      } else if (session) {
        if (retryTimer) clearTimeout(retryTimer);
        setState('in');
      }
    });

    return () => {
      alive = false;
      if (retryTimer) clearTimeout(retryTimer);
      subscription.unsubscribe();
    };
  }, [router]);

  if (state === 'in') return <>{children}</>;
  return <Loading label={state === 'out' ? 'Redirecting to login…' : 'Loading…'} />;
}
