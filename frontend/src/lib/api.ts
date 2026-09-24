import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { supabase } from './supabase';

const envApiUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
const isBrowser = typeof window !== 'undefined';
const apiBaseUrl = isBrowser ? '' : (envApiUrl || 'http://localhost:8000');

// 120s = the reverse proxy's read timeout; anything longer only turns into a
// 504 after a spinner. Long-running work (searches) is polled, not awaited.
const api = axios.create({
  baseURL: apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
  timeout: 120000,
});

type RetryConfig = InternalAxiosRequestConfig & { _retry?: boolean; _busyRetry?: boolean };

// ONE refresh for every request that got a 401 at the same moment (a dashboard
// load fires many requests; parallel refreshes race and can revoke each other).
let refreshPromise: ReturnType<typeof supabase.auth.refreshSession> | null = null;

function refreshOnce() {
  refreshPromise ??= supabase.auth.refreshSession().finally(() => { refreshPromise = null; });
  return refreshPromise;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

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
  async (error: AxiosError) => {
    const config = error.config as RetryConfig | undefined;
    const statusCode = error.response?.status;
    if (!isBrowser || !config) return Promise.reject(error);

    // 503 from the auth check = sign-in service briefly busy (common on mobile
    // networks). Retry once instead of treating it as a logout.
    if (statusCode === 503 && !config._busyRetry) {
      config._busyRetry = true;
      await sleep(1500);
      return api(config);
    }

    if (statusCode === 401 && !config._retry) {
      config._retry = true;
      const { data: { session } } = await supabase.auth.getSession();
      const isGuest = localStorage.getItem('hyperclients_guest') === 'true';
      if (!session) {
        // No local session at all: genuinely logged out (guests stay put).
        if (!isGuest) window.location.href = '/login';
        return Promise.reject(error);
      }
      const { data, error: refreshError } = await refreshOnce();
      if (data?.session) {
        config.headers.Authorization = `Bearer ${data.session.access_token}`;
        return api(config);
      }
      // Only a REAL auth failure (refresh token revoked/expired) logs the user
      // out. A network error during refresh keeps the session: the next
      // request simply tries again.
      const refreshStatus = (refreshError as { status?: number } | null)?.status;
      if (refreshStatus && refreshStatus >= 400 && refreshStatus < 500) {
        await supabase.auth.signOut({ scope: 'local' }).catch(() => undefined);
        if (!isGuest) window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
