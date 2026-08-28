"use client"

/**
 * Supabase client — ONLY used for Google OAuth sign-in.
 * All other auth goes through local JWT (stored in localStorage).
 */

import { createClient, SupabaseClient } from "@supabase/supabase-js"

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ""
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ""

function createSupabaseClient(): SupabaseClient {
  if (!supabaseUrl || !supabaseAnonKey) {
    // Return stub client when env vars missing
    return {
      auth: {
        getSession: async () => ({ data: { session: null }, error: null }),
        getUser: async () => ({ data: { user: null }, error: null }),
        signOut: async () => ({ error: null }),
        signInWithPassword: async () => ({ data: null, error: new Error("Supabase not configured") }),
        signUp: async () => ({ data: null, error: new Error("Supabase not configured") }),
        signInWithOAuth: async () => ({ data: null, error: new Error("Supabase not configured") }),
        exchangeCodeForSession: async () => ({ data: null, error: new Error("Supabase not configured") }),
        setSession: async () => ({ data: null, error: new Error("Supabase not configured") }),
        onAuthStateChange: () => ({ data: { subscription: { unsubscribe: () => {} } } }),
      },
    } as unknown as SupabaseClient
  }
  return createClient(supabaseUrl, supabaseAnonKey, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    },
  })
}

let _client: SupabaseClient | null = null

function getClient(): SupabaseClient {
  if (!_client) _client = createSupabaseClient()
  return _client
}

export const supabase = new Proxy({} as SupabaseClient, {
  get(_, prop: string) {
    return (getClient() as any)[prop]
  },
})
