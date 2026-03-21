import { useEffect, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import api from '@/lib/api';
import { API_ROUTES } from '@/lib/constants';
import { useAuthStore } from '@/stores/authStore';
import { useToast } from './useToast';
import { useRouter } from 'next/navigation';

export function useAuth() {
  const { user, isLoading, isAuthenticated, initialize, logout, setLoading } = useAuthStore();
  const { showToast } = useToast();
  const router = useRouter();

  const fetchProfile = useCallback(async () => {
    await initialize();
  }, [initialize]);

  const signOut = async () => {
    try {
      setLoading(true);
      await supabase.auth.signOut();
      logout();
      router.push('/');
      showToast('Logged out successfully', 'success');
    } catch (e: any) {
      showToast(e.message || 'Failed to logout', 'error');
    } finally {
      setLoading(false);
    }
  };

  const signInWithGoogle = async () => {
    try {
      setLoading(true);
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
        },
      });
      if (error) throw error;
    } catch (e: any) {
      showToast(e.message || 'Failed to login with Google', 'error');
      setLoading(false);
    }
  };

  return {
    user,
    isLoading,
    fetchProfile,
    signOut,
    signInWithGoogle,
    isAuthenticated,
  };
}

