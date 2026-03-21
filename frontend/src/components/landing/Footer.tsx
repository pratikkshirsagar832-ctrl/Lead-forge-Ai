import Link from 'next/link';
import { Target } from 'lucide-react';

export function Footer() {
  return (
    <footer className="bg-slate-900 py-16 text-slate-400">
      <div className="container mx-auto px-6 lg:px-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-12 mb-12 border-b border-slate-800 pb-12">
          <div className="md:col-span-2">
            <Link href="/" className="flex items-center gap-2 mb-6 text-white w-fit">
              <div className="bg-indigo-500 rounded-lg p-1">
                <Target className="w-5 h-5 text-white" />
              </div>
              <span className="font-bold text-xl tracking-tight">LeadForge AI</span>
            </Link>
            <p className="max-w-xs leading-relaxed text-sm">
              The automated lead generation engine built for agency owners, freelancers, and B2B founders.
            </p>
          </div>
          
          <div>
            <h4 className="text-white font-semibold mb-4">Product</h4>
            <ul className="space-y-3 text-sm">
              <li><Link href="#features" className="hover:text-white transition-colors">Features</Link></li>
              <li><Link href="#how-it-works" className="hover:text-white transition-colors">How it Works</Link></li>
              <li><Link href="/login" className="hover:text-white transition-colors">Login</Link></li>
            </ul>
          </div>
          
          <div>
            <h4 className="text-white font-semibold mb-4">Legal</h4>
            <ul className="space-y-3 text-sm">
              <li><Link href="#" className="hover:text-white transition-colors">Privacy Policy</Link></li>
              <li><Link href="#" className="hover:text-white transition-colors">Terms of Service</Link></li>
            </ul>
          </div>
        </div>
        
        <div className="flex flex-col md:flex-row items-center justify-between text-sm">
          <p>© {new Date().getFullYear()} LeadForge AI. All rights reserved.</p>
          <div className="flex gap-4 mt-4 md:mt-0">
            {/* Social links placeholder */}
          </div>
        </div>
      </div>
    </footer>
  );
}
