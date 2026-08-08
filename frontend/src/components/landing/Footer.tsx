import Link from 'next/link';
import Image from 'next/image';
import { Target, Zap, Shield } from 'lucide-react';

export function Footer() {
  return (
    <footer className="bg-navy py-16 text-ice/50 border-t border-steel/15 relative overflow-hidden">
      {/* Subtle top glow */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-96 h-px bg-gradient-to-r from-transparent via-steel/30 to-transparent pointer-events-none" />

      <div className="container mx-auto px-6 lg:px-8 relative z-10">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-12 mb-12 border-b border-steel/15 pb-12">
          <div className="md:col-span-2">
            <Link href="/" className="flex items-center gap-2 mb-6 text-offwhite w-fit group">
              <div className="bg-gradient-to-br from-violet to-steel rounded-lg p-1 group-hover:scale-105 transition-transform duration-300 shadow-lg shadow-violet/20">
                <Image src="/hyperclients-icon.svg" alt="Hyperclients" width={40} height={40} className="object-contain" />
              </div>
              <span className="font-bold text-xl tracking-tight" style={{ fontFamily: 'var(--font-heading)' }}>Hyperclients</span>
            </Link>
            <p className="max-w-xs leading-relaxed text-sm text-ice/50">
              The automated lead generation engine built for agency owners, freelancers, and B2B founders who want to scale faster.
            </p>
            <div className="flex items-center gap-4 mt-6">
              <span className="flex items-center gap-1.5 text-xs text-ice/40">
                <Zap className="w-3 h-3 text-emerald-400/60" />
                AI Powered
              </span>
              <span className="flex items-center gap-1.5 text-xs text-ice/40">
                <Shield className="w-3 h-3 text-steel/60" />
                Secure
              </span>
            </div>
          </div>

          <div>
            <h4 className="text-offwhite font-semibold mb-4 text-sm uppercase tracking-wider">Product</h4>
            <ul className="space-y-3 text-sm">
              <li><Link href="#features" className="hover:text-steel transition-colors duration-200">Features</Link></li>
              <li><Link href="#how-it-works" className="hover:text-steel transition-colors duration-200">How it Works</Link></li>
              <li><Link href="/pricing" className="hover:text-steel transition-colors duration-200">Pricing</Link></li>
              <li><Link href="/dashboard" className="hover:text-steel transition-colors duration-200">Dashboard</Link></li>
            </ul>
          </div>

          <div>
            <h4 className="text-offwhite font-semibold mb-4 text-sm uppercase tracking-wider">Legal</h4>
            <ul className="space-y-3 text-sm">
              <li><Link href="#" className="hover:text-steel transition-colors duration-200">Privacy Policy</Link></li>
              <li><Link href="#" className="hover:text-steel transition-colors duration-200">Terms of Service</Link></li>
              <li><Link href="#" className="hover:text-steel transition-colors duration-200">Cookie Policy</Link></li>
            </ul>
          </div>
        </div>

        <div className="flex flex-col md:flex-row items-center justify-between text-sm text-ice/40">
          <p>&copy; {new Date().getFullYear()} Hyperclients. All rights reserved.</p>
          <p className="mt-2 md:mt-0">
            Built with <span className="text-rose-400/60">&hearts;</span> for lead generation
          </p>
        </div>
      </div>
    </footer>
  );
}
