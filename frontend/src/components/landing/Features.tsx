'use client';

import { motion } from 'framer-motion';
import { Map, Bot, Zap, Filter, LayoutDashboard, Target } from 'lucide-react';

const features = [
  {
    icon: <Map className="w-6 h-6 text-indigo-600" />,
    title: 'Google Maps Scraping',
    description: 'Instantly extract hundreds of local businesses in any niche and location directly from Google Maps.',
    color: 'bg-indigo-100',
  },
  {
    icon: <Bot className="w-6 h-6 text-blue-600" />,
    title: 'Automated Website Analysis',
    description: 'We visit their website, analyze it for quality, and categorize the lead as Hot, Warm, or Skip based on your criteria.',
    color: 'bg-blue-100',
  },
  {
    icon: <Zap className="w-6 h-6 text-emerald-600" />,
    title: 'AI Pitch Generation',
    description: 'Generate hyper-personalized outreach pitches based on the business\'s website context and missing features.',
    color: 'bg-emerald-100',
  },
  {
    icon: <Filter className="w-6 h-6 text-amber-600" />,
    title: 'Smart Filtering',
    description: 'Quickly sort and filter your leads by category, rating, review count, and website status.',
    color: 'bg-amber-100',
  },
  {
    icon: <LayoutDashboard className="w-6 h-6 text-purple-600" />,
    title: 'Built-in CRM',
    description: 'Track contact status, leave notes, favorite leads, and monitor your entire pipeline in one clean dashboard.',
    color: 'bg-purple-100',
  },
  {
    icon: <Target className="w-6 h-6 text-rose-600" />,
    title: 'Instant CSV Export',
    description: 'Export your qualified list to CSV with one click, ready to import into Instantly, Lemlist, or any cold email tool.',
    color: 'bg-rose-100',
  },
];

export function Features() {
  return (
    <section id="features" className="py-24 bg-white">
      <div className="container mx-auto px-6 lg:px-8">
        <div className="text-center max-w-3xl mx-auto mb-16">
          <h2 className="text-indigo-600 font-semibold tracking-wide uppercase text-sm mb-3">Powerful Features</h2>
          <h3 className="text-3xl md:text-5xl font-bold text-slate-900 mb-6 tracking-tight">Everything you need to scale output</h3>
          <p className="text-lg text-slate-600">
            Stop switching between different tools. LeadForge AI combines map scraping, website analysis, AI personalization, and CRM tracking into one seamless workflow.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 max-w-7xl mx-auto">
          {features.map((feature, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-50px" }}
              transition={{ duration: 0.5, delay: idx * 0.1 }}
              className="p-8 rounded-2xl border border-slate-100 hover:border-indigo-100 hover:shadow-xl hover:shadow-indigo-500/5 transition-all bg-white group"
            >
              <div className={`w-12 h-12 rounded-xl ${feature.color} flex items-center justify-center mb-6 group-hover:scale-110 transition-transform`}>
                {feature.icon}
              </div>
              <h4 className="text-xl font-bold text-slate-900 mb-3">{feature.title}</h4>
              <p className="text-slate-600 leading-relaxed">
                {feature.description}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
