'use client';

import { useAuth } from '@/hooks/useAuth';
import { GlassCard } from '@/components/shared/GlassCard';
import { User, Mail, Shield, Key } from 'lucide-react';

export default function SettingsPage() {
  const { user } = useAuth();

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div>
        <h1 className="text-3xl font-bold text-slate-900 tracking-tight">Settings</h1>
        <p className="text-slate-500 mt-2">Manage your account preferences and profile details.</p>
      </div>

      <div className="max-w-3xl">
        <div className="space-y-6">
          <GlassCard className="p-8">
            <h2 className="text-xl font-bold text-slate-900 mb-6 flex items-center gap-2">
              <User className="w-5 h-5 text-indigo-600" />
              Profile Information
            </h2>
            
            <div className="space-y-6">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">First Name</label>
                  <input
                    type="text"
                    disabled
                    value={user?.first_name || ''}
                    className="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-slate-500 cursor-not-allowed"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Last Name</label>
                  <input
                    type="text"
                    disabled
                    value={user?.last_name || ''}
                    className="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-slate-500 cursor-not-allowed"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Email Address</label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                    <Mail className="h-5 w-5 text-slate-400" />
                  </div>
                  <input
                    type="email"
                    disabled
                    value={user?.email || ''}
                    className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50 text-slate-500 cursor-not-allowed"
                  />
                </div>
              </div>
            </div>
          </GlassCard>

          <GlassCard className="p-8">
            <h2 className="text-xl font-bold text-slate-900 mb-6 flex items-center gap-2">
              <Shield className="w-5 h-5 text-emerald-600" />
              Security
            </h2>
            
            <div className="flex items-center justify-between p-4 bg-slate-50 rounded-xl border border-slate-100">
              <div className="flex items-center gap-4">
                <div className="p-2 bg-white rounded-lg shadow-sm border border-slate-200">
                  <Key className="w-5 h-5 text-slate-600" />
                </div>
                <div>
                  <p className="font-medium text-slate-900">Password</p>
                  <p className="text-sm text-slate-500">Manage your password via Supabase Auth</p>
                </div>
              </div>
              <button disabled className="px-4 py-2 text-sm font-medium text-slate-500 bg-white border border-slate-200 rounded-lg opacity-50 cursor-not-allowed">
                Update
              </button>
            </div>
          </GlassCard>
        </div>
      </div>
    </div>
  );
}
