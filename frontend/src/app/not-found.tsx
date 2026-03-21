import Link from 'next/link';
import { Ghost } from 'lucide-react';

export default function NotFound() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50 relative overflow-hidden">
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-slate-200/50 rounded-full blur-[100px] -z-10" />
      
      <div className="text-center">
        <div className="bg-slate-100 w-24 h-24 rounded-full flex items-center justify-center mx-auto mb-6">
          <Ghost className="w-12 h-12 text-slate-400" />
        </div>
        <h1 className="text-4xl font-bold text-slate-900 mb-2">404 - Not Found</h1>
        <p className="text-slate-500 mb-8 max-w-sm mx-auto">
          The page you are looking for doesn't exist or has been moved.
        </p>
        <Link 
          href="/" 
          className="inline-flex items-center justify-center px-6 py-3 border border-transparent text-base font-medium rounded-xl text-white bg-indigo-600 hover:bg-indigo-700 transition-colors"
        >
          Go back home
        </Link>
      </div>
    </div>
  );
}
