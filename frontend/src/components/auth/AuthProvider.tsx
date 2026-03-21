'use client';

import { useEffect, useRef } from 'react';
import { useAuth } from '@/hooks/useAuth';
import { supabase } from '@/lib/supabase';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { fetchProfile, logout } = useAuth();
  const initref = useRef(false);

  useEffect(() => {
    if (initref.current) return;
    initref.current = true;

    // Initial fetch
    fetchProfile();

    // Listen for auth changes from Supabase
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      async (event, session) => {
        if (event === 'SIGNED_IN' || event === 'TOKEN_REFRESHED') {
          await fetchProfile();
        } else if (event === 'SIGNED_OUT') {
          logout();
          window.location.href = '/login';
        }
      }
    );

    return () => {
      subscription.unsubscribe();
    };
  }, [fetchProfile, logout]);

  return <>{children}</>;
}
