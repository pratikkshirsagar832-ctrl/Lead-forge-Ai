'use client';
import Image from 'next/image';
import Link from 'next/link';
import { Sparkles, Menu, X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useState } from 'react';

const NAV_LINKS = [
  { label: 'Features', href: '/#features' },
  { label: 'How it Works', href: '/#how-it-works' },
  { label: 'About', href: '/about-us' },
  { label: 'SEO Checker', href: '/tools/seo-score-checker' },
  { label: 'Pricing', href: '/pricing' },
  { label: 'Blog', href: '/blogs' },
];

export default function Header() {
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <motion.header
      initial={{ y: -20, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.6, ease: [0.25, 0.1, 0.25, 1] }}
      className="fixed top-0 inset-x-0 z-50 bg-navy/85 backdrop-blur-xl border-b border-steel/10"
    >
      <div className="container mx-auto px-6 h-16 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 group">
          <Image
            src="/logo-lockup.png"
            alt="Hyperclients"
            width={160}
            height={40}
            className="h-9 w-auto object-contain"
          />
        </Link>

        <nav className="hidden md:flex items-center gap-8 text-sm font-medium text-ice/60">
          {NAV_LINKS.map((item, i) => (
            <motion.div
              key={item.label}
              initial={{ opacity: 0, y: -8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 + i * 0.05, duration: 0.4 }}
            >
              <Link href={item.href} className="hover:text-offwhite transition-all duration-200 relative group">
                {item.label}
                <span className="absolute -bottom-1 left-0 right-0 h-px bg-steel/60 scale-x-0 group-hover:scale-x-100 transition-transform duration-300" />
              </Link>
            </motion.div>
          ))}
        </nav>

        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.2, duration: 0.4 }}
          className="flex items-center gap-4"
        >
          <Link
            href="/login"
            className="group relative text-sm font-medium bg-cta text-white px-5 py-2.5 rounded-lg transition-colors duration-200 hover:bg-cta-light"
          >
            <span className="relative flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5" />
              Try It Free
            </span>
          </Link>

          <button
            onClick={() => setMenuOpen((v) => !v)}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={menuOpen}
            className="md:hidden text-ice/80 hover:text-offwhite p-2 -mr-2 rounded-lg hover:bg-white/5 transition-colors"
          >
            {menuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </motion.div>
      </div>

      <AnimatePresence>
        {menuOpen && (
          <motion.nav
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25, ease: 'easeInOut' }}
            className="md:hidden overflow-hidden border-t border-steel/10 bg-navy/95 backdrop-blur-xl"
          >
            <div className="container mx-auto px-6 py-4 flex flex-col gap-1">
              {NAV_LINKS.map((item) => (
                <Link
                  key={item.label}
                  href={item.href}
                  onClick={() => setMenuOpen(false)}
                  className="px-3 py-3 rounded-lg text-sm font-medium text-ice/80 hover:text-offwhite hover:bg-white/5 transition-colors"
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </motion.nav>
        )}
      </AnimatePresence>
    </motion.header>
  );
}
