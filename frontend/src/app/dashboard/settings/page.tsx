'use client';

export const dynamic = 'force-dynamic';

import { useEffect, useState } from 'react';
import { GlassCard } from '@/components/shared/GlassCard';
import { supabase } from '@/lib/supabase';
import { User, Mail, Loader2 } from 'lucide-react';

export default function SettingsPage() {
  const [user, setUser] = useState<{ email?: string } | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchUser = async () => {
      const { data: { user: u } } = await supabase.auth.getUser();
      setUser(u);
      setIsLoading(false);
    };
    fetchUser();
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="w-6 h-6 text-steel animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-offwhite">Settings</h1>
      <GlassCard className="p-6">
        <h2 className="text-lg font-semibold text-offwhite mb-4">Profile</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider text-ice/60 mb-1.5">Email</label>
            <div className="relative">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ice/40" />
              <input
                type="email"
                value={user?.email || ''}
                readOnly
                className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-ocean/20 border border-ocean/40 text-ice/60 text-sm"
              />
            </div>
          </div>
        </div>
      </GlassCard>
    </div>
  );
}
