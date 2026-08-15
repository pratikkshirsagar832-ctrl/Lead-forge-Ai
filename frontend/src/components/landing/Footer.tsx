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
              <li><Link href="/tools/seo-score-checker" className="hover:text-steel transition-colors duration-200">SEO Score Checker</Link></li>
              <li><Link href="/pricing" className="hover:text-steel transition-colors duration-200">Pricing</Link></li>
              <li><Link href="/blogs" className="hover:text-steel transition-colors duration-200">Blog</Link></li>
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

        <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-ice/40">
          <p>&copy; {new Date().getFullYear()} Hyperclients. All rights reserved.</p>
          <a
            href="https://www.producthunt.com/products/hyperclients?launch=hyperclients"
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-2.5 rounded-full border border-orange-500/25 bg-orange-500/5 px-4 py-2 transition-all duration-300 hover:border-orange-400/50 hover:bg-orange-500/10 hover:shadow-lg hover:shadow-orange-500/10"
          >
            <svg viewBox="0 0 24 24" className="w-4 h-4 fill-[#DA552F]" aria-hidden="true">
              <path d="M13.604 8.4h-3.405V12h3.405c.995 0 1.801-.806 1.801-1.8 0-.993-.806-1.8-1.801-1.8zM12 0C5.372 0 0 5.372 0 12s5.372 12 12 12 12-5.372 12-12S18.628 0 12 0zm1.604 14.4h-3.405V18H7.801V6h5.803c2.319 0 4.2 1.88 4.2 4.2 0 2.32-1.881 4.2-4.2 4.2z" />
            </svg>
            <span className="text-xs font-semibold text-ice/60 group-hover:text-offwhite transition-colors">
              Find us on Product Hunt
            </span>
            <svg viewBox="0 0 20 20" className="w-3 h-3 text-ice/30 group-hover:text-[#DA552F] transition-colors" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M7 7h10v10" />
              <path d="M7 17 17 7" />
            </svg>
          </a>
          <p>
            Built with <span className="text-rose-400/60">&hearts;</span> for lead generation
          </p>
        </div>
      </div>
    </footer>
  );
}
