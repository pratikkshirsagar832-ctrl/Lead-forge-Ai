'use client';

export const dynamic = 'force-dynamic';

import { useEffect, useState } from 'react';
import { GlassCard } from '@/components/shared/GlassCard';
import api from '@/lib/api';
import { User, Mail, Loader2 } from 'lucide-react';

export default function SettingsPage() {
  const [user, setUser] = useState<{ email?: string } | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const resp = await api.get('/api/auth/me');
        if (resp.data) setUser({ email: resp.data.email });
      } catch (e) {
        console.error('Failed to fetch user:', e);
      }
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
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold text-offwhite tracking-tight">Settings</h1>
        <p className="text-ice/60 mt-2">Manage your account preferences and profile details.</p>
      </div>

      <div className="max-w-3xl">
        <div className="space-y-6">
          <GlassCard className="p-8 bg-gradient-to-br from-ocean/30 to-navy border-ocean/40">
            <h2 className="text-xl font-bold text-offwhite mb-6 flex items-center gap-2">
              <User className="w-5 h-5 text-steel" />
              Profile Information
            </h2>

            <div className="space-y-6">
              <div>
                <label className="block text-sm font-medium text-ice/70 mb-2">Email Address</label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Mail className="h-5 w-5 text-steel" />
                  </div>
                  <input
                    type="email"
                    disabled
                    value={user?.email || ''}
                    className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-ocean/50 bg-navy/80 text-ice/60 cursor-not-allowed"
                  />
                </div>
              </div>
            </div>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
