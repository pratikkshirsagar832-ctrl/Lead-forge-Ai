import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import { verifySessionToken, SESSION_COOKIE, HOST_SESSION_COOKIE } from '../../../../lib/admin-auth';
import KeysPanel from './keys-panel';

export const dynamic = 'force-dynamic';

export const metadata = {
  title: 'Admin — API keys',
  robots: { index: false, follow: false },
};

export default async function AdminKeysPage() {
  const store = await cookies();
  const value = store.get(HOST_SESSION_COOKIE)?.value ?? store.get(SESSION_COOKIE)?.value;
  if (!verifySessionToken(value)) {
    redirect('/admin/login');
  }
  return <KeysPanel />;
}
