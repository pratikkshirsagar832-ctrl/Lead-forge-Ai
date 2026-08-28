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
      const { data } = await refreshPromise!;
      if (data?.session) {
        error.config.headers.Authorization = `Bearer ${data.session.access_token}`;
        return api(error.config);
      }
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
