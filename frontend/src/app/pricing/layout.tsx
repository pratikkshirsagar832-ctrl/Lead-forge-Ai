import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Pricing — Hyperclients',
  description:
    'Simple, transparent pricing for Hyperclients. Start with a free trial, then pick the plan that fits how many LinkedIn and Google Maps leads you need.',
  alternates: { canonical: '/pricing' },
};

export default function PricingLayout({ children }: { children: React.ReactNode }) {
  return children;
}
