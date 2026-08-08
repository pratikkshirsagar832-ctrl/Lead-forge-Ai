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

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const redirectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const mountedRef = useRef(true);

  const safeRedirect = (url: string) => {
    if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
    redirectTimerRef.current = setTimeout(() => {
      if (mountedRef.current) router.replace(url);
    }, 1500);
  };

  useEffect(() => {
    mountedRef.current = true;

    const checkSession = async () => {
      try {
        if (isGuestSession()) {
          setIsAuthenticated(true);
          setIsLoading(false);
          return;
        }

        const { data: { session } } = await supabase.auth.getSession();
        if (!mountedRef.current) return;

        if (session) {
          setIsAuthenticated(true);
          setIsLoading(false);
          return;
        }

        redirectTimerRef.current = setTimeout(async () => {
          if (!mountedRef.current) return;
          try {
            const { data: { session: retrySession } } = await supabase.auth.getSession();
            if (retrySession) {
              setIsAuthenticated(true);
              setIsLoading(false);
              return;
            }
          } catch {}
          if (mountedRef.current) {
            router.replace(`/login?redirect=${encodeURIComponent(pathname)}`);
          }
        }, 3000);
      } catch (err: any) {
        console.error('AuthGuard: session check failed', err);
        if (err?.message?.includes('Invalid API key') || err?.status === 401) {
          router.replace('/login?error=auth_config');
        } else {
          safeRedirect('/login');
        }
      }
    };

    checkSession();

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (event, session) => {
        if (!mountedRef.current) return;
        if (event === 'SIGNED_OUT') {
          clearGuestSession();
          safeRedirect('/login');
        } else if (session) {
          if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
          setIsAuthenticated(true);
          setIsLoading(false);
        }
      }
    );

    return () => {
      mountedRef.current = false;
      if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
      subscription.unsubscribe();
    };
  }, [router, pathname]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-navy font-sans">
        <div className="flex items-center gap-3">
          <Loader2 className="w-6 h-6 text-steel animate-spin" />
          <p className="text-ice/60">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) return null;

  return <>{children}</>;
}
