'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Lock } from 'lucide-react';
import Header from '@/components/landing/Header';

export default function AdminLogin() {
  const router = useRouter();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const res = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.error || 'Login failed');
        return;
      }
      router.push('/admin');
      router.refresh();
    } catch {
      setError('Something went wrong. Try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative min-h-screen bg-navy text-ice font-sans flex items-center justify-center px-6 overflow-hidden">
      <div className="pointer-events-none absolute -top-32 -right-32 w-96 h-96 bg-primary/10 rounded-full blur-[120px]" />
      <div className="pointer-events-none absolute bottom-0 -left-32 w-96 h-96 bg-brand-accent/[0.06] rounded-full blur-[120px]" />
      <Header />
      <div className="relative z-10 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-gradient-to-br from-primary to-brand-accent mb-4">
            <Lock className="w-6 h-6 text-offwhite" />
          </div>
          <h1 className="text-3xl font-bold text-offwhite font-heading">Blog Admin</h1>
          <p className="text-text-secondary text-sm mt-2">Enter the admin password to continue</p>
        </div>

        <form onSubmit={handleSubmit} className="glass-card-premium rounded-2xl p-8 space-y-4">
          <div>
            <label htmlFor="password" className="block text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Admin password"
              autoFocus
              className="w-full rounded-xl bg-bg-elevated border border-primary/20 px-4 py-3 text-offwhite placeholder:text-text-muted/60 outline-none focus:border-brand-accent/50 focus:ring-2 focus:ring-brand-accent/20 transition-all"
            />
          </div>
          {error && (
            <p className="text-rose text-sm font-medium bg-rose/10 border border-rose/20 rounded-lg px-3 py-2">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={loading || !password}
            className="w-full btn-gradient-cyan rounded-xl px-6 py-3 text-sm disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            {loading ? 'Checking...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
}