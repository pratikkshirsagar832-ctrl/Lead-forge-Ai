'use client';

import { useState } from 'react';
import { Sidebar } from '@/components/dashboard/Sidebar';
import { AuthGuard } from '@/components/auth/AuthGuard';
import { ThreeBackground } from '@/components/shared/ThreeBackground';
import { Menu } from 'lucide-react';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <AuthGuard>
      <ThreeBackground />
      <div className="flex min-h-screen font-sans text-ice relative z-10">
        <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
        <main className="flex-1 lg:ml-64 p-4 md:p-8 overflow-y-auto text-ice">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden mb-4 p-2 rounded-lg hover:bg-ocean/50 text-ice/60 hover:text-offwhite transition-colors"
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
