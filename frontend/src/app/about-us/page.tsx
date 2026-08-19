import type { Metadata } from 'next';
import Link from 'next/link';
import { Target, Search, Users, Rocket, ArrowRight } from 'lucide-react';
import Header from '@/components/landing/Header';
import { Footer } from '@/components/landing/Footer';

export const metadata: Metadata = {
  title: 'About Us — Hyperclients',
  description:
    'HyperClients is a local business intelligence platform that surfaces high-intent leads by reading the signals hidden inside Google My Business profiles.',
};

const founders = [
  {
    name: 'Bhaskar Gupta',
    role: 'Founder, Radian Marketing',
    bio: 'A Delhi-based digital marketer with years of hands-on experience helping D2C, SaaS, and B2B brands grow. He brings the market experience.',
  },
  {
    name: 'Pratik Kshirsagar',
    role: 'Co-founder & AI/ML Engineer',
    bio: 'A Class 12 student and AI/ML enthusiast already building things most professionals have not attempted yet. He brings the machine intelligence.',
  },
];

export default function AboutPage() {
  return (
    <div className="relative min-h-screen bg-navy text-ice font-sans overflow-hidden">
      <div className="pointer-events-none absolute -top-32 right-0 w-[500px] h-[500px] bg-primary/10 rounded-full blur-[120px]" />
      <div className="pointer-events-none absolute bottom-0 -left-32 w-96 h-96 bg-brand-accent/[0.05] rounded-full blur-[120px]" />
      <Header />

      <main className="relative z-10 container mx-auto px-6 pt-28 pb-16 max-w-4xl">
        <p className="text-xs font-semibold uppercase tracking-widest text-brand-accent-light mb-2">Company</p>
        <h1 className="text-4xl md:text-5xl font-bold text-offwhite font-heading mb-4 leading-tight">
          About <span className="gradient-text-premium">Hyperclients</span>
        </h1>
        <p className="text-lg text-ice/80 leading-relaxed max-w-2xl mb-10">
          We built the tool we always wished existed. Every agency owner knows the grind — hours lost chasing cold
          leads, manually sifting through directories, and pitching businesses that were never a good fit to begin
          with. HyperClients was born out of that frustration.
        </p>

        <div className="grid md:grid-cols-2 gap-5 mb-10">
          <section className="glass-card-premium rounded-2xl p-6 md:p-8">
            <div className="flex items-center gap-3 mb-4">
              <span className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-primary/20 border border-primary/30">
                <Target className="w-5 h-5 text-brand-accent-light" />
              </span>
              <h2 className="text-xl font-bold text-offwhite font-heading">What We Do</h2>
            </div>
            <p className="text-ice/80 leading-relaxed text-[15px]">
              HyperClients is a local business intelligence platform that surfaces high-intent leads by reading the
              signals hidden inside Google My Business profiles — contact gaps, growth patterns, review velocity,
              expansion activity. We turn all of it into a scored, prioritised pipeline your team can actually act on.
              Apart from finding leads, we hand you context and a website score based on SEO parameters.
            </p>
          </section>

          <section className="glass-card-premium rounded-2xl p-6 md:p-8">
            <div className="flex items-center gap-3 mb-4">
              <span className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-primary/20 border border-primary/30">
                <Search className="w-5 h-5 text-brand-accent-light" />
              </span>
              <h2 className="text-xl font-bold text-offwhite font-heading">Why It Matters</h2>
            </div>
            <p className="text-ice/80 leading-relaxed text-[15px]">
              Most lead generation tools are built for enterprise markets. They miss the millions of local and
              regional businesses growing quietly with real hiring needs, real digital gaps, and real budgets.
              HyperClients is built specifically for that gap. Whether you are a recruitment agency or a marketing
              services provider, HyperClients gets you in front of the right door at the right time.
            </p>
          </section>
        </div>

        <section className="mb-10">
          <div className="flex items-center gap-3 mb-5">
            <span className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-brand-accent/15 border border-brand-accent/25">
              <Users className="w-5 h-5 text-brand-accent-light" />
            </span>
            <h2 className="text-2xl font-bold text-offwhite font-heading">Who Built This</h2>
          </div>
          <div className="grid md:grid-cols-2 gap-5">
            {founders.map((f) => (
              <div key={f.name} className="glass-card-premium rounded-2xl p-6 md:p-8">
                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-primary to-brand-accent flex items-center justify-center font-heading font-bold text-offwhite mb-4">
                  {f.name.split(' ').map((n) => n[0]).join('')}
                </div>
                <h3 className="text-lg font-bold text-offwhite font-heading">{f.name}</h3>
                <p className="text-xs font-semibold uppercase tracking-wider text-brand-accent-light mb-3">{f.role}</p>
                <p className="text-ice/80 leading-relaxed text-sm">{f.bio}</p>
              </div>
            ))}
          </div>
          <p className="text-ice/80 leading-relaxed mt-5 text-[15px]">
            One brings the market experience. The other brings the machine intelligence. Together, they are building
            the prospecting layer that modern agencies deserve.
          </p>
        </section>

        <section className="glass-card gradient-border rounded-2xl p-6 md:p-8 mb-10">
          <div className="flex items-center gap-3 mb-4">
            <span className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-brand-accent/15 border border-brand-accent/25">
              <Rocket className="w-5 h-5 text-brand-accent-light" />
            </span>
            <h2 className="text-xl font-bold text-offwhite font-heading">What Drives Us</h2>
          </div>
          <p className="text-ice/80 leading-relaxed text-[15px]">
            We believe the best leads are not found. They are identified through signals. And we believe small teams
            with the right intelligence can outpunch agencies ten times their size. That is the edge HyperClients
            gives you.
          </p>
        </section>

        <div className="flex flex-wrap gap-3">
          <Link
            href="/login"
            className="btn-gradient-cyan rounded-xl px-6 py-3 text-sm inline-flex items-center gap-2"
          >
            Try It Free <ArrowRight className="w-4 h-4" />
          </Link>
          <Link href="/pricing" className="btn-glass rounded-xl px-6 py-3 text-sm">
            See Pricing
          </Link>
        </div>
      </main>
      <Footer />
    </div>
  );
}