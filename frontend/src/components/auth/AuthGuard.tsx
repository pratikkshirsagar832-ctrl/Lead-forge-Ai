'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { Loader2 } from 'lucide-react';
import { getLocalToken } from '@/lib/api';

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

    // Check for local JWT token
    const token = getLocalToken();
    if (token || isGuestSession()) {
      setIsAuthenticated(true);
      setIsLoading(false);
      return;
    }

    // No token — redirect to login
    redirectTimerRef.current = setTimeout(() => {
      if (mountedRef.current) {
        router.replace(`/login?redirect=${encodeURIComponent(pathname)}`);
      }
    }, 500);

    return () => {
      mountedRef.current = false;
      if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
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
