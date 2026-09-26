import type { Metadata } from 'next';

// Sign-in pages have no search value: keep them out of the index (links are
// still followed) so they never compete with the landing page.
export const metadata: Metadata = {
  title: 'Log in — Hyperclients',
  description: 'Log in or create your Hyperclients account.',
  alternates: { canonical: '/login' },
  robots: { index: false, follow: true },
};

export default function LoginLayout({ children }: { children: React.ReactNode }) {
  return children;
}
