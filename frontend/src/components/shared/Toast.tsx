'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { CheckCircle, XCircle, AlertCircle, Info, X, Sparkles } from 'lucide-react';
import { useToast, Toast as ToastType } from '@/hooks/useToast';
import { cn } from '@/lib/utils';

export function ToastContainer() {
  const { toasts, removeToast } = useToast();

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 w-full max-w-sm pointer-events-none">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onRemove={() => removeToast(toast.id)} />
        ))}
      </AnimatePresence>
    </div>
  );
}

function ToastItem({ toast, onRemove }: { toast: ToastType; onRemove: () => void }) {
  const icons = {
    success: <CheckCircle className="w-5 h-5 text-emerald-400" />,
    error: <XCircle className="w-5 h-5 text-red-400" />,
    warning: <AlertCircle className="w-5 h-5 text-amber-400" />,
    info: <Info className="w-5 h-5 text-steel" />,
  };

  const bgStyles = {
    success: 'bg-navy/90 border-emerald-500/30 backdrop-blur-xl shadow-lg shadow-emerald-500/10',
    error: 'bg-navy/90 border-red-500/30 backdrop-blur-xl shadow-lg shadow-red-500/10',
    warning: 'bg-navy/90 border-amber-500/30 backdrop-blur-xl shadow-lg shadow-amber-500/10',
    info: 'bg-navy/90 border-steel/30 backdrop-blur-xl shadow-lg shadow-steel/10',
  };

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 50, scale: 0.9 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9, x: 50, transition: { duration: 0.2 } }}
      className={cn(
        'flex items-start gap-3 p-4 rounded-xl border pointer-events-auto relative overflow-hidden',
        bgStyles[toast.type]
      )}
      role="alert"
    >
      {/* Premium top accent */}
      <div className="absolute top-0 left-4 right-4 h-px bg-gradient-to-r from-transparent via-white/10 to-transparent pointer-events-none" />

      <div className="shrink-0 mt-0.5">{icons[toast.type]}</div>
      <div className="flex-1 text-sm font-medium text-ice pt-0.5">
        {toast.message}
      </div>
      <button
        onClick={onRemove}
        className="shrink-0 p-1 rounded-md text-ice/40 hover:text-ice hover:bg-steel/10 transition-colors"
      >
        <X className="w-4 h-4" />
      </button>
    </motion.div>
  );
}
