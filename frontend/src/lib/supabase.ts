import { createClient, type SupabaseClient } from '@supabase/supabase-js';

let _supabase: SupabaseClient | null = null;

function getOrCreateClient(): SupabaseClient {
  if (!_supabase) {
    const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim();
    const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY?.trim();

    if (!supabaseUrl || !supabaseAnonKey) {
      console.error(
        '[supabase] Not configured: set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY. Auth features will fail.'
      );
      return createUnconfiguredClient();
    }

    _supabase = createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: false,
      },
    });
  }
  return _supabase;
}

function createUnconfiguredClient(): SupabaseClient {
  const notConfigured = () =>
    new Error(
      'Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY environment variables.'
    );
  const methods: Record<string, () => Promise<unknown>> = {
    getSession: async () => ({ data: { session: null }, error: null }),
    getUser: async () => ({ data: { user: null }, error: null }),
    signOut: async () => ({ error: null }),
    signUp: async () => ({ data: null, error: notConfigured() }),
    signInWithPassword: async () => ({ data: null, error: notConfigured() }),
    signInWithOAuth: async () => ({ data: null, error: notConfigured() }),
    exchangeCodeForSession: async () => ({ data: null, error: notConfigured() }),
    setSession: async () => ({ data: null, error: notConfigured() }),
  };
  const namespace = () =>
    new Proxy({} as Record<string, unknown>, {
      get: (_t, key) =>
        key === 'onAuthStateChange'
          ? () => ({ data: { subscription: { unsubscribe() {} } }, error: null })
          : (methods[key] ?? (async () => ({ data: null, error: notConfigured() }))),
    });
  return new Proxy({} as SupabaseClient, {
    get: () => namespace(),
  });
}

export const supabase = new Proxy<SupabaseClient>({} as SupabaseClient, {
  get(_, prop) {
    return getOrCreateClient()[prop as keyof SupabaseClient];
  },
});
