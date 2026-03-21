'use client';

import * as React from 'react';
import { Moon, Sun } from 'lucide-react';
import { useTheme } from 'next-themes';

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return <div className="w-10 h-10" />; // Placeholder to avoid hydration mismatch
  }

  return (
    <button
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
      className="p-2.5 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors shadow-sm relative overflow-hidden flex items-center justify-center w-10 h-10"
      aria-label="Toggle theme"
    >
      <Sun className={`h-5 w-5 absolute transition-all duration-300 ${theme === 'dark' ? '-translate-y-10 opacity-0' : 'translate-y-0 opacity-100'}`} />
      <Moon className={`h-5 w-5 absolute transition-all duration-300 ${theme === 'dark' ? 'translate-y-0 opacity-100' : 'translate-y-10 opacity-0'}`} />
    </button>
  );
}
