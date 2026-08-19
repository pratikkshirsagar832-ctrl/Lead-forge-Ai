import { ReactNode } from 'react';
import Header from './Header';
import { Footer } from './Footer';

export function ContentPage({
  kicker,
  title,
  children,
}: {
  kicker: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="relative min-h-screen bg-navy text-ice font-sans overflow-hidden">
      <div className="pointer-events-none absolute -top-32 right-0 w-[500px] h-[500px] bg-primary/10 rounded-full blur-[120px]" />
      <div className="pointer-events-none absolute bottom-0 -left-32 w-96 h-96 bg-brand-accent/[0.05] rounded-full blur-[120px]" />
      <Header />
      <main className="relative z-10 container mx-auto px-6 pt-28 pb-16 max-w-3xl">
        <p className="text-xs font-semibold uppercase tracking-widest text-brand-accent-light mb-2">{kicker}</p>
        <h1 className="text-3xl md:text-4xl font-bold text-offwhite font-heading mb-8 leading-tight">{title}</h1>
        <div className="space-y-6">{children}</div>
      </main>
      <Footer />
    </div>
  );
}

export function PolicySection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="glass-card-premium rounded-2xl p-6 md:p-8">
      <h2 className="text-lg md:text-xl font-bold text-offwhite font-heading mb-3">{title}</h2>
      <div className="text-ice/80 leading-relaxed space-y-3 text-[15px]">{children}</div>
    </section>
  );
}