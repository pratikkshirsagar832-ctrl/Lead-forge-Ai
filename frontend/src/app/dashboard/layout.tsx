'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import { Sidebar } from '@/components/dashboard/Sidebar';
import { FullPageLoader } from '@/components/shared/FullPageLoader';

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated, isLoading, fetchProfile } = useAuth();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let mounted = true;
    const init = async () => {
      try {
        await fetchProfile();
      } finally {
        if (mounted) setReady(true);
      }
    };
    init();

    const timeout = setTimeout(() => {
      if (mounted) {
        console.warn('[Dashboard] Auth initialization timed out after 5s');
        setReady(true);
      }
    }, 5000);

    return () => { 
      mounted = false; 
      clearTimeout(timeout);
    };
  }, [fetchProfile]);

  // If local readiness flag hasn't flipped and global loading is true
  if (!ready && isLoading) {
    return <FullPageLoader />;
  }

  if (!isAuthenticated) {
    router.replace('/login');
    return <FullPageLoader />;
  }

  return (
    <div className="flex min-h-screen bg-[#09090B] font-sans text-white">
      <Sidebar />
      <main className="flex-1 ml-64 p-8 overflow-y-auto bg-[#09090B] text-white">
        <div className="max-w-7xl mx-auto space-y-8">
          {children}
        </div>
      </main>
    </div>
  );
}
