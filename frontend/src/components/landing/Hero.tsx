'use client';

import { motion } from 'framer-motion';
import { ArrowRight, Search, Zap, Target } from 'lucide-react';
import Link from 'next/link';

export function Hero() {
  return (
    <div className="relative overflow-hidden bg-slate-50 pt-[120px] pb-32">
      {/* Background decoration */}
      <div className="absolute inset-0 z-0">
        <div className="absolute -top-40 -right-40 w-[600px] h-[600px] rounded-full bg-indigo-50/50 blur-[100px]" />
        <div className="absolute top-40 -left-20 w-[400px] h-[400px] rounded-full bg-blue-50/50 blur-[80px]" />
      </div>

      <div className="container relative z-10 mx-auto px-6 lg:px-8">
        <div className="mx-auto max-w-4xl text-center">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-100 text-indigo-700 text-sm font-semibold mb-6">
              <Zap className="w-4 h-4" />
              LeadForge AI v2.0 is live
            </span>
          </motion.div>
          
          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className="text-5xl md:text-7xl font-extrabold tracking-tight text-slate-900 mb-8"
          >
            Find perfect clients on <span className="text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-blue-500">Google Maps</span>
            <br className="select-none hidden md:block" />
             in minutes.
          </motion.h1>
          
          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="text-xl md:text-2xl text-slate-600 mb-10 max-w-3xl mx-auto leading-relaxed"
          >
            Stop wasting hours manually searching. LeadForge AI automatically extracts businesses, analyzes their websites, and drafts personalized pitches.
          </motion.p>
          
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="flex flex-col sm:flex-row items-center justify-center gap-4"
          >
            <Link 
              href="/signup" 
              className="w-full sm:w-auto px-8 py-4 bg-indigo-600 text-white rounded-xl font-semibold text-lg hover:bg-indigo-700 hover:shadow-lg hover:shadow-indigo-600/20 active:scale-95 transition-all flex items-center justify-center gap-2"
            >
              Start For Free <ArrowRight className="w-5 h-5" />
            </Link>
            <Link 
              href="#how-it-works" 
              className="w-full sm:w-auto px-8 py-4 bg-white text-slate-700 border border-slate-200 rounded-xl font-semibold text-lg hover:bg-slate-50 hover:border-slate-300 active:scale-95 transition-all"
            >
              How it works
            </Link>
          </motion.div>
        </div>

        {/* Dashboard Preview Image/Mockup */}
        <motion.div
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.5 }}
          className="mt-20 mx-auto max-w-6xl relative"
        >
          <div className="absolute inset-0 bg-gradient-to-t from-slate-50 10% to-transparent z-10 bottom-0 top-1/2" />
          <div className="rounded-2xl border border-slate-200/60 bg-white/50 p-2 shadow-2xl shadow-indigo-500/10 backdrop-blur-sm overflow-hidden ring-1 ring-slate-900/5">
            <div className="rounded-xl border border-slate-100 bg-white p-4 shadow-sm overflow-hidden h-[400px] md:h-[600px] relative">
              {/* Fake Dashboard Header */}
              <div className="flex items-center justify-between border-b border-slate-100 pb-4 mb-6">
                <div className="flex items-center gap-4">
                  <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center">
                    <Search className="w-4 h-4 text-indigo-600" />
                  </div>
                  <div className="h-5 w-40 bg-slate-100 rounded" />
                </div>
                <div className="flex gap-2">
                  <div className="h-8 w-24 bg-slate-100 rounded-md" />
                  <div className="h-8 w-8 bg-slate-100 rounded-md" />
                </div>
              </div>
              
              {/* Fake Table */}
              <div className="space-y-4">
                <div className="flex items-center gap-4 bg-slate-50 p-4 rounded-lg">
                  <div className="h-6 w-1/4 bg-slate-200/60 rounded" />
                  <div className="h-6 w-1/4 bg-slate-200/60 rounded" />
                  <div className="h-6 w-1/4 bg-slate-200/60 rounded" />
                  <div className="h-6 w-1/4 bg-slate-200/60 rounded" />
                </div>
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="flex items-center gap-4 p-4 border-b border-slate-50">
                    <div className="h-5 w-1/4 bg-slate-100 rounded" />
                    <div className="flex items-center gap-2 w-1/4">
                      <div className="h-5 w-5 bg-indigo-100 rounded-full" />
                      <div className="h-5 w-20 bg-slate-100 rounded" />
                    </div>
                    <div className="h-5 w-1/4 bg-slate-100 rounded" />
                    <div className="h-6 w-16 bg-emerald-50 rounded-full" />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}
