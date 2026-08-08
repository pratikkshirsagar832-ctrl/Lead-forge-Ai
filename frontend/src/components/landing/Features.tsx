'use client';

import { motion } from 'framer-motion';
import { Map, Bot, Zap, Filter, LayoutDashboard, Target, Sparkles, Shield, BarChart3, MessageSquare } from 'lucide-react';
import { ScrollReveal } from '@/lib/animations';

const features = [
  {
    icon: <Map className="w-6 h-6" />,
    title: 'Google Maps Searching',
    description: 'Instantly find hundreds of local businesses in any niche and location directly from Google Maps.',
    gradient: 'from-violet-400/20 to-steel/20',
    color: 'text-violet-400',
    accent: 'via-violet-500',
  },
  {
    icon: <Sparkles className="w-6 h-6" />,
    title: 'Automated Website Analysis',
    description: 'We visit every website, analyze load speed, content quality, SEO, and identify the best opportunities.',
    gradient: 'from-amber-400/20 to-steel/20',
    color: 'text-amber-400',
    accent: 'via-amber-500',
  },
  {
    icon: <MessageSquare className="w-6 h-6" />,
    title: 'AI Pitch Generation',
    description: 'Generate hyper-personalized outreach pitches based on website context, missing features, and pain points.',
    gradient: 'from-cta-light/20 to-steel/20',
    color: 'text-cta-light',
    accent: 'via-cta',
  },
  {
    icon: <Filter className="w-6 h-6" />,
    title: 'Smart Filtering',
    description: 'Quickly sort and filter your leads by category, rating, review count, and website quality score.',
    gradient: 'from-emerald-400/20 to-steel/20',
    color: 'text-emerald-400',
    accent: 'via-emerald-500',
  },
  {
    icon: <LayoutDashboard className="w-6 h-6" />,
    title: 'Built-in CRM',
    description: 'Track contact status, leave notes, favorite leads, and monitor your entire pipeline in one clean dashboard.',
    gradient: 'from-steel/20 to-ocean/20',
    color: 'text-steel',
    accent: 'via-steel',
  },
  {
    icon: <BarChart3 className="w-6 h-6" />,
    title: 'Deep Analytics',
    description: 'Score breakdown, website deep analysis, and performance reports for every single lead in your pipeline.',
    gradient: 'from-violet-400/20 to-teal/20',
    color: 'text-teal-400',
    accent: 'via-teal-500',
  },
  {
    icon: <Shield className="w-6 h-6" />,
    title: 'Quality Scoring',
    description: 'Every lead gets a quality score based on website health, SEO, UX, and contact availability.',
    gradient: 'from-rose-400/20 to-steel/20',
    color: 'text-rose-400',
    accent: 'via-rose-500',
  },
  {
    icon: <Target className="w-6 h-6" />,
    title: 'Instant CSV Export',
    description: 'Export your qualified list to CSV with one click, ready to import into any cold email tool.',
    gradient: 'from-teal/20 to-emerald/20',
    color: 'text-teal',
    accent: 'via-teal',
  },
];

export function Features() {
  return (
    <section id="features" className="py-24 bg-navy relative overflow-hidden">
      {/* Premium ambient glow */}
      <div className="absolute inset-0 bg-gradient-to-b from-violet/5 via-transparent to-teal/5 pointer-events-none" />
      <div className="absolute top-0 left-1/4 w-96 h-96 bg-violet/5 rounded-full blur-[100px] pointer-events-none" />
      <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-teal/5 rounded-full blur-[100px] pointer-events-none" />

      <div className="container mx-auto px-6 lg:px-8 relative z-10">
        <div className="text-center max-w-3xl mx-auto mb-16">
          <ScrollReveal>
            <span className="inline-flex items-center gap-2 text-violet-400 font-semibold tracking-wide uppercase text-sm mb-3">
              <span className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
              Powerful Features
            </span>
          </ScrollReveal>
          <ScrollReveal delay={0.1}>
            <h2
              className="text-3xl md:text-5xl font-bold text-offwhite mb-6 tracking-tight"
              style={{ fontFamily: 'var(--font-heading)' }}
            >
              Everything you need to{' '}
              <span className="gradient-text-premium">scale output</span>
            </h2>
          </ScrollReveal>
          <ScrollReveal delay={0.2}>
            <p className="text-lg text-ice/60 max-w-2xl mx-auto">
              Stop switching between different tools. Hyperclients combines map search, website analysis,
              AI personalization, and CRM tracking into one seamless workflow.
            </p>
          </ScrollReveal>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5 max-w-7xl mx-auto">
          {features.map((feature, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, y: 24 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: '-50px' }}
              transition={{ duration: 0.45, delay: idx * 0.06, ease: [0.25, 0.1, 0.25, 1] }}
              className="group relative p-6 rounded-2xl border border-steel/20 hover:border-steel/40 transition-all duration-300 bg-gradient-to-br from-sapphire/30 to-navy/95 hover:shadow-xl hover:shadow-steel/5 hover:-translate-y-1"
            >
              {/* Premium hover gradient overlay */}
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-violet/5 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />

              {/* Top accent line on hover */}
              <div className="absolute left-4 right-4 top-0 h-px bg-gradient-to-r from-transparent via-steel/40 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />

              <div className="relative z-10">
                <div
                  className={`w-11 h-11 rounded-xl bg-gradient-to-br ${feature.gradient} flex items-center justify-center mb-5 group-hover:scale-110 group-hover:shadow-lg transition-all duration-300 ${feature.color}`}
                >
                  {feature.icon}
                </div>
                <h4
                  className="text-lg font-bold text-offwhite mb-2.5 group-hover:text-offwhite transition-colors"
                  style={{ fontFamily: 'var(--font-heading)' }}
                >
                  {feature.title}
                </h4>
                <p className="text-sm text-ice/60 leading-relaxed group-hover:text-ice/70 transition-colors">
                  {feature.description}
                </p>
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
