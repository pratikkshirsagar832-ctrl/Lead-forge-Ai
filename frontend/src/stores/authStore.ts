import { create } from 'zustand';
import { supabase } from '@/lib/supabase';
import api from '@/lib/api';
import { API_ROUTES } from '@/lib/constants';

export interface User {
  id: string;
  email: string;
  first_name?: string;
  last_name?: string;
  user_metadata?: any;
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  setUser: (user: User | null) => void;
  setLoading: (loading: boolean) => void;
  logout: () => void;
  initialize: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true,
  setUser: (user) => set({ user, isAuthenticated: !!user }),
  setLoading: (isLoading) => set({ isLoading }),
  logout: () => set({ user: null, isAuthenticated: false, isLoading: false }),
  initialize: async () => {
    // Fast path: if already authenticated, just background-verify without locking UI
    const state = useAuthStore.getState();
    if (state.isAuthenticated && state.user) {
      api.get(API_ROUTES.auth.me)
        .then(res => set({ user: res.data }))
        .catch(() => {});
      return;
    }

    set({ isLoading: true });
    console.log('[Auth] initialize start');
    
    try {
      const { data: { session } } = await supabase.auth.getSession();

      if (!session) {
        set({
          user: null,
          isAuthenticated: false,
          isLoading: false,
        });
        console.log('[Auth] initialize finished: No session');
        return;
      }

      try {
        const response = await api.get(API_ROUTES.auth.me);
        set({
          user: response.data,
          isAuthenticated: true,
          isLoading: false,
        });
        console.log('[Auth] initialize finished: Success');
      } catch (error) {
        console.error('[Auth] /api/auth/me failed:', error);
        set({
          user: {
            id: session.user.id,
            email: session.user.email || '',
            user_metadata: session.user.user_metadata || {},
          },
          isAuthenticated: true,
          isLoading: false,
        });
      }
    } catch (error) {
      console.error('[Auth] getSession failed:', error);
      set({
        user: null,
        isAuthenticated: false,
        isLoading: false,
      });
    }
  }
}));
