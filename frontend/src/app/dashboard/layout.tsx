'use client';

import { useState } from 'react';
import { Sidebar } from '@/components/dashboard/Sidebar';
import { AmbientBackdrop } from '@/components/dashboard/AmbientBackdrop';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { Menu } from 'lucide-react';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <AuthGuard>
      <AmbientBackdrop />
      <div className="grain flex min-h-[100dvh] font-sans text-ice relative z-10">
        <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <main className="flex-1 lg:ml-64 px-4 pt-4 pb-10 md:px-10 md:pt-10 md:pb-14 overflow-y-auto text-ice">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden mb-4 p-2.5 rounded-xl key-3d text-ice/70 hover:text-offwhite"
            aria-label="Open sidebar"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div className="max-w-7xl mx-auto space-y-8">
            {children}
          </div>
        </main>
      </div>
    </AuthGuard>
  );
}
