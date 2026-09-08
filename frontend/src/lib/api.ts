import axios from 'axios';
import { supabase } from './supabase';

const envApiUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
const isBrowser = typeof window !== 'undefined';
const apiBaseUrl = isBrowser ? '' : (envApiUrl || 'http://localhost:8000');

const api = axios.create({
  baseURL: apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
  timeout: 330000,
});

let refreshPromise: Promise<any> | null = null;

api.interceptors.request.use(async (config) => {
  if (isBrowser) {
    const { data: { session } } = await supabase.auth.getSession();
    if (session?.access_token) {
      config.headers.Authorization = `Bearer ${session.access_token}`;
    }
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401 && isBrowser && !error.config._retry) {
      error.config._retry = true;
      if (!refreshPromise) {
        const { data: { session } } = await supabase.auth.getSession();
        if (session) {
          refreshPromise = supabase.auth.refreshSession().finally(() => {
            refreshPromise = null;
          });
        }
      }
      if (refreshPromise) {
        const { data } = await refreshPromise;
        if (data?.session) {
          error.config.headers.Authorization = `Bearer ${data.session.access_token}`;
          return api(error.config);
        }
      }
      // Guest mode (shown when auth is unavailable) has no session by design —
      // do not bounce the user back to /login in a redirect loop; the backend
      // still enforces auth on every real data call, so guests only see the
      // shell and empty/errored states.
      const isGuest = typeof window !== 'undefined' && localStorage.getItem('hyperclients_guest') === 'true';
      if (!isGuest) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
