'use client';

import { Sparkles, ArrowRight, Zap } from 'lucide-react';
import Link from 'next/link';
import { Modal } from './Modal';

interface UpgradeModalProps {
  isOpen: boolean;
  onClose: () => void;
  type?: 'limit' | 'expired';
  /** Overrides for a specific reason (e.g. a lead count above the plan). */
  title?: string;
  description?: string;
}

export function UpgradeModal({ isOpen, onClose, type = 'limit', title: titleOverride, description: descriptionOverride }: UpgradeModalProps) {
  const title = titleOverride || (type === 'limit' ? 'Search Limit Reached' : 'Trial Expired');
  const description = descriptionOverride || (type === 'limit'
    ? 'You have used all your searches for this month (resets on the 1st). Upgrade your plan to continue finding leads without interruption.'
    : 'Your free trial has ended. Upgrade to a paid plan to keep using Hyperclients and unlock more leads.');

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title}>
      <div className="space-y-5">
        <div className="w-14 h-14 rounded-full bg-gradient-to-br from-amber-500/20 to-rose-500/20 flex items-center justify-center mx-auto ring-1 ring-amber-500/20">
          <Zap className="w-7 h-7 text-amber-400" />
        </div>

        <p className="text-sm text-ice/60 text-center leading-relaxed">
          {description}
        </p>

        <Link
          href="/dashboard/billing"
          onClick={onClose}
          className="w-full h-11 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 btn-3d-gold"
        >
          <Sparkles className="w-4 h-4" />
          View Plans
          <ArrowRight className="w-4 h-4" />
        </Link>

        <button
          onClick={onClose}
          className="w-full text-xs text-ice/40 hover:text-ice/60 transition-colors py-1"
        >
          Maybe later
        </button>
      </div>
    </Modal>
  );
}
