'use client';

import { motion } from 'framer-motion';
import { Search, Database, Brain, SendHorizonal } from 'lucide-react';
import { ScrollReveal } from '@/lib/animations';

const steps = [
  {
    number: '01',
    title: 'Enter Niche & Location',
    description: 'Tell us exactly who you are looking for. "Plumbers in Dallas, TX" or "Dentists in London" — we handle the rest.',
    icon: Search,
    color: 'from-violet-400/30 to-steel/20',
    iconColor: 'text-violet-400',
  },
  {
    number: '02',
    title: 'Auto-Scrape Engine',
    description: 'Our backend connects directly to Google Maps, fetching up to 50 targeted businesses with their core info and websites.',
    icon: Database,
    color: 'from-steel/30 to-ocean/20',
    iconColor: 'text-steel',
  },
  {
    number: '03',
    title: 'Smart AI Analysis',
    description: 'We visit every website to check load speed, content quality, SEO, and categorize each lead by opportunity level.',
    icon: Brain,
    color: 'from-violet-400/20 to-teal/20',
    iconColor: 'text-teal-400',
  },
  {
    number: '04',
    title: 'Personalized Pitch',
    description: 'AI writes customized email drafts referencing specific issues on their website — dramatically increasing reply rates.',
    icon: SendHorizonal,
    color: 'from-amber-400/20 to-rose/20',
    iconColor: 'text-amber-400',
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="py-24 bg-navy relative overflow-hidden">
      {/* Ambient glows */}
      <div className="absolute -top-40 -left-40 w-[600px] h-[600px] rounded-full bg-ocean/8 blur-[120px] pointer-events-none" />
      <div className="absolute -bottom-40 -right-40 w-[500px] h-[500px] rounded-full bg-violet/8 blur-[100px] pointer-events-none" />

      <div className="container mx-auto px-6 lg:px-8 relative z-10">
        <div className="mb-16 max-w-2xl">
          <ScrollReveal>
            <span className="inline-flex items-center gap-2 text-steel font-semibold tracking-wide uppercase text-sm mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-steel animate-pulse-slow" />
              Simple Pipeline
            </span>
          </ScrollReveal>
          <ScrollReveal delay={0.1}>
            <h2
              className="text-3xl md:text-5xl font-bold text-offwhite mb-6 tracking-tight"
              style={{ fontFamily: 'var(--font-heading)' }}
            >
              From search to{' '}
              <span className="gradient-text-premium">qualified leads</span>
              <br />in 4 steps
            </h2>
          </ScrollReveal>
          <ScrollReveal delay={0.2}>
            <p className="text-lg text-ice/60 max-w-xl">
              A linear pipeline built for speed and quality. Go from a simple search query to a qualified list of prospects in minutes.
            </p>
          </ScrollReveal>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8 relative">
          {/* Connecting line */}
          <div className="hidden lg:block absolute top-16 left-[12%] right-[12%] h-px bg-gradient-to-r from-violet/30 via-steel/40 to-amber/30 pointer-events-none" />

          {steps.map((step, idx) => {
            const Icon = step.icon;
            return (
              <motion.div
                key={idx}
                initial={{ opacity: 0, y: 30 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: idx * 0.15 }}
                className="relative group"
              >
                {/* Step number - large background */}
                <div className="text-7xl font-black text-steel/10 mb-4 group-hover:text-steel/20 transition-colors duration-500 select-none leading-none">
                  {step.number}
                </div>

                {/* Icon */}
                <div
                  className={`w-12 h-12 rounded-xl bg-gradient-to-br ${step.color} flex items-center justify-center mb-5 transition-colors duration-300 ${step.iconColor}`}
                >
                  <Icon className="w-5 h-5" />
                </div>

                <h4
                  className="text-xl font-bold text-offwhite mb-3 group-hover:text-steel transition-colors duration-300"
                  style={{ fontFamily: 'var(--font-heading)' }}
                >
                  {step.title}
                </h4>
                <p className="text-ice/60 leading-relaxed text-sm">
                  {step.description}
                </p>

                {/* Arrow connector for desktop */}
                {idx < steps.length - 1 && (
                  <div className="hidden lg:block absolute top-16 -right-6 text-steel/30 group-hover:text-steel/50 transition-colors duration-300">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M5 12h14m-6-6 6 6-6 6" />
                    </svg>
                  </div>
                )}
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
