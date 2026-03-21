'use client';

import { motion } from 'framer-motion';

const steps = [
  {
    number: '01',
    title: 'Enter Niche & Location',
    description: 'Tell us exactly who you are looking for. E.g., "Plumbers in Dallas, TX" or "Dentists in London".',
  },
  {
    number: '02',
    title: 'Auto-Scrape Engine',
    description: 'Our backend connects directly to Google Maps, fetching up to 50 targeted businesses and extracting their core info and websites.',
  },
  {
    number: '03',
    title: 'Smart AI Analysis',
    description: 'We visit every website found to check for load speed, content quality, and basic SEO issues, categorizing them instantly.',
  },
  {
    number: '04',
    title: 'Personalized Pitch',
    description: 'Use our AI to write a highly customized email draft referencing specific issues on their website to dramatically increase reply rates.',
  },
];

export function HowItWorks() {
  return (
    <section id="how-it-works" className="py-24 bg-slate-50 relative overflow-hidden">
      <div className="container mx-auto px-6 lg:px-8 relative z-10">
        <div className="mb-16">
          <h2 className="text-3xl md:text-5xl font-bold text-slate-900 mb-6 tracking-tight">How it works</h2>
          <p className="text-lg text-slate-600 max-w-2xl">
            A linear pipeline built for speed and quality. Go from a simple search query to a qualified list of prospects in minutes.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
          {steps.map((step, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, x: -20 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.5, delay: idx * 0.1 }}
              className="relative"
            >
              <div className="text-7xl font-black text-slate-200/60 mb-6">{step.number}</div>
              <h4 className="text-xl font-bold text-slate-900 mb-3">{step.title}</h4>
              <p className="text-slate-600 leading-relaxed">
                {step.description}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
