import axios from 'axios';
import { supabase } from './supabase';

const envApiUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
const defaultApiUrl = 'http://localhost:8000';
const canUseWindow = typeof window !== 'undefined';
const shouldForceHttps =
  canUseWindow &&
  window.location.protocol === 'https:' &&
  !!envApiUrl &&
  envApiUrl.startsWith('http://') &&
  !envApiUrl.includes('localhost') &&
  !envApiUrl.includes('127.0.0.1');

const apiBaseUrl = shouldForceHttps
  ? envApiUrl.replace('http://', 'https://')
  : envApiUrl || defaultApiUrl;

const api = axios.create({
  baseURL: apiBaseUrl,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10000,
});

// Request interceptor — attach Supabase auth token
api.interceptors.request.use(
  async (config) => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.access_token) {
        config.headers.Authorization = `Bearer ${session.access_token}`;
      }
    } catch {
      // Fail silently — request will proceed without auth
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor — handle 401
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      // Only redirect if we're in browser
      if (typeof window !== 'undefined' && !window.location.pathname.startsWith('/login')) {
        await supabase.auth.signOut();
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
