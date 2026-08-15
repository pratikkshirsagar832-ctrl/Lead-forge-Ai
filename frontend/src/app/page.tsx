'use client';
import Image from 'next/image';
import { Hero } from '@/components/landing/Hero';
import { Features } from '@/components/landing/Features';
import { HowItWorks } from '@/components/landing/HowItWorks';
import { Footer } from '@/components/landing/Footer';
import Link from 'next/link';
import { Sparkles } from 'lucide-react';
import { motion } from 'framer-motion';

export default function LandingPage() {
  return (
    <div className="min-h-screen flex flex-col font-sans selection:bg-violet/30 selection:text-offwhite">
      {/* Premium Sticky Header — Fade in from top */}
      <motion.header
        initial={{ y: -20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.6, ease: [0.25, 0.1, 0.25, 1] }}
        className="fixed top-0 inset-x-0 z-50 bg-navy/85 backdrop-blur-xl border-b border-steel/10 before:absolute before:inset-0 before:bg-gradient-to-r before:from-transparent before:via-steel/[0.02] before:to-transparent before:animate-shimmer before:pointer-events-none"
      >
        <div className="container mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2 group">
            <motion.div
              whileHover={{ scale: 1.05 }}
              className="bg-gradient-to-br from-violet to-steel rounded-lg p-1 transition-transform duration-300 shadow-lg shadow-violet/20"
            >
              <Image src="/hyperclients-icon.svg" alt="Hyperclients" width={40} height={40} className="object-contain" />
            </motion.div>
            <span className="font-bold text-xl tracking-tight text-offwhite" style={{ fontFamily: 'var(--font-heading)' }}>
              Hyperclients
            </span>
          </Link>

          <nav className="hidden md:flex items-center gap-8 text-sm font-medium text-ice/60">
            {[
              { label: 'Features', href: '#features' },
              { label: 'How it Works', href: '#how-it-works' },
              { label: 'SEO Checker', href: '/tools/seo-score-checker' },
              { label: 'Pricing', href: '/pricing' },
              { label: 'Blog', href: '/blogs' },
            ].map((item, i) => (
              <motion.div
                key={item.label}
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 + i * 0.05, duration: 0.4 }}
              >
                <Link
                  href={item.href}
                  className="hover:text-offwhite transition-all duration-200 relative group"
                >
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
              className="group relative text-sm font-medium bg-gradient-to-r from-cta to-cta-light text-white px-5 py-2.5 rounded-lg overflow-hidden transition-all duration-200 hover:shadow-lg hover:shadow-cta/25 active:scale-[0.97]"
            >
              <span className="absolute inset-0 bg-white/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
              <span className="relative flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                Try It Free
              </span>
            </Link>
          </motion.div>
        </div>
      </motion.header>

      <main className="flex-1">
        {/* Hero — already has its own stagger animations */}
        <Hero />

        {/* Features — scroll-triggered section wrapper */}
        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.6 }}
        >
          <Features />
        </motion.div>

        {/* How It Works — scroll-triggered section wrapper */}
        <motion.div
          initial={{ opacity: 0 }}
          whileInView={{ opacity: 1 }}
          viewport={{ once: true, margin: '-100px' }}
          transition={{ duration: 0.6 }}
        >
          <HowItWorks />
        </motion.div>
      </main>

      {/* Footer — fade in on scroll */}
      <motion.div
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        transition={{ duration: 0.8 }}
      >
        <Footer />
      </motion.div>
    </div>
  );
}
