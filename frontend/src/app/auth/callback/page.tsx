'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { Loader2 } from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';

export default function AuthCallbackPage() {
  const router = useRouter();
  const { fetchProfile } = useAuth();

  useEffect(() => {
    const handleCallback = async () => {
      // Supabase auto-handles the hash fragment if we're using createBrowserClient
      // but we need to wait for session detection
      const { data: { session }, error } = await supabase.auth.getSession();
      
      if (error || !session) {
        console.error('Session error', error);
        router.push('/login');
        return;
      }

      // Sync with backend profile
      await fetchProfile();
      router.push('/dashboard');
    };

    handleCallback();
  }, [router, fetchProfile]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50">
      <Loader2 className="w-10 h-10 text-indigo-600 animate-spin mb-4" />
      <h2 className="text-xl font-medium text-slate-800">Completing sign in...</h2>
      <p className="text-slate-500 mt-2">You will be redirected shortly.</p>
    </div>
  );
}
