'use client';

import { GlassCard } from '@/components/shared/GlassCard';
import { cn } from '@/lib/utils';
import {
  AlertTriangle, CheckCircle, XCircle, AlertCircle,
  TrendingUp, Target, Plus
} from 'lucide-react';

interface BreakdownItem {
  reason: string;
  points: number;
  severity: string;
}

interface ScoreBreakdownData {
  deductions: BreakdownItem[];
  bonuses: BreakdownItem[];
  deduction_total: number;
  bonus_total: number;
  summary: string;
}

interface ScoreBreakdownProps {
  score: number;
  category: string;
  breakdown: ScoreBreakdownData;
}

const severityConfig: Record<string, { icon: typeof AlertCircle; color: string; bg: string; border: string; label: string }> = {
  critical: { icon: XCircle, color: 'text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/20', label: 'Critical' },
  major: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20', label: 'Major' },
  medium: { icon: AlertCircle, color: 'text-yellow-400', bg: 'bg-yellow-500/10', border: 'border-yellow-500/20', label: 'Medium' },
  minor: { icon: AlertCircle, color: 'text-ice/60', bg: 'bg-ice/10', border: 'border-ice/20', label: 'Minor' },
  bonus: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20', label: 'Bonus' },
};

export function ScoreBreakdown({ score, category, breakdown }: ScoreBreakdownProps) {
  if (!breakdown || !breakdown.deductions) return null;

  const scoreColor = score >= 70 ? 'text-emerald-400' : score >= 40 ? 'text-amber-400' : 'text-rose-400';
  const categoryLabel = category === 'hot' ? 'Hot Lead — Needs Help' : category === 'warm' ? 'Warm Lead — Some Potential' : 'Skip';

  return (
    <GlassCard className="p-6" delay={0.1}>
      <div className="flex items-center gap-2 mb-5 animate-fade-in-down">
        <Target className="w-5 h-5 text-steel" />
        <h3 className="text-lg font-bold text-offwhite">Website Score Breakdown</h3>
      </div>

      {/* Score Display */}
      <div className="flex items-center justify-between p-4 rounded-xl bg-gradient-to-r from-ocean/30 to-navy border border-ocean/30 mb-5">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-ice/60">Health Score</p>
          <p className={cn('text-3xl font-extrabold mt-1', scoreColor)}>{score}/100</p>
          <p className="text-xs font-medium text-ice/60 mt-0.5">{categoryLabel}</p>
        </div>
        <div className="text-right">
          <p className="text-xs text-ice/50">Issues Found</p>
          <p className="text-2xl font-bold text-offwhite mt-1">
            {breakdown.deductions.length}
            <span className="text-xs text-ice/50 font-normal ml-1">problems</span>
          </p>
        </div>
      </div>

      {/* Deductions */}
      {breakdown.deductions.length > 0 && (
        <div className="mb-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-rose-400/80 mb-3 flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5" />
            Problems ({breakdown.deductions.length})
          </p>
          <div className="space-y-1.5">
            {breakdown.deductions.map((item, i) => {
              const cfg = severityConfig[item.severity] || severityConfig.minor;
              const Icon = cfg.icon;
              return (
                <div
                  key={i}
                  className={cn(
                    'flex items-start gap-2.5 p-2.5 rounded-lg border',
                    cfg.bg,
                    cfg.border,
                  )}
                >
                  <Icon className={cn('w-4 h-4 shrink-0 mt-0.5', cfg.color)} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-ice/80 leading-tight">{item.reason}</p>
                    <p className={cn('text-xs font-semibold mt-0.5', cfg.color)}>
                      {cfg.label} — {item.points} points
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Bonuses */}
      {breakdown.bonuses.length > 0 && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-emerald-400/80 mb-3 flex items-center gap-1.5">
            <CheckCircle className="w-3.5 h-3.5" />
            What&apos;s Already Fixed ({breakdown.bonuses.length})
          </p>
          <div className="space-y-1.5">
            {breakdown.bonuses.map((item, i) => (
              <div
                key={i}
                className="flex items-start gap-2.5 p-2.5 rounded-lg border bg-emerald-500/10 border-emerald-500/20 animate-fade-in-up"
              >
                <Plus className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-ice/80 leading-tight">{item.reason}</p>
                  <p className="text-xs font-semibold text-emerald-400 mt-0.5">
                    +{item.points} points
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </GlassCard>
  );
}
