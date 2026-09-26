import type { Metadata } from 'next';
import LandingPage from './_components/LandingPage';

export const metadata: Metadata = {
  title: 'Hyperclients — Find High-intent Clients on Auto-pilot',
  description:
    'Find people asking for your service on LinkedIn right now and pull local businesses from Google Maps. AI-qualified leads, newest first, for freelancers and agencies.',
  alternates: { canonical: '/' },
};

export default function Page() {
  return <LandingPage />;
}
