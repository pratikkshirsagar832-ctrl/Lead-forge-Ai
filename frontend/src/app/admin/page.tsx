import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { sessionToken } from '../../../lib/admin-auth';
import AdminPanel from './admin-panel';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Admin — Hyperclients Blog',
  robots: { index: false, follow: false },
};

export default async function AdminPage() {
  const store = await cookies();
  if (store.get('hc_admin_session')?.value !== sessionToken()) {
    redirect('/admin/login');
  }
  return <AdminPanel />;
}