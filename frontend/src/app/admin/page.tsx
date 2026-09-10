import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { sessionToken, safeEqual, ADMIN_PASSWORD, SESSION_COOKIE, HOST_SESSION_COOKIE } from '../../../lib/admin-auth';
import AdminPanel from './admin-panel';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Admin — Hyperclients Blog',
  robots: { index: false, follow: false },
};

export default async function AdminPage() {
  const store = await cookies();
  // Accept both cookie names: HTTPS deployments use the __Host- variant,
  // plain-HTTP deployments the unprefixed one.
  const value = store.get(HOST_SESSION_COOKIE)?.value ?? store.get(SESSION_COOKIE)?.value;
  const ok = !!ADMIN_PASSWORD && !!value && safeEqual(value, sessionToken());
  if (!ok) {
    redirect('/admin/login');
  }
  return <AdminPanel />;
}