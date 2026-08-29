'use client';

import { useState } from 'react';
import { GlassCard } from '@/components/shared/GlassCard';
import { cn } from '@/lib/utils';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Home, FileSearch, Paintbrush, Link2, PhoneCall, Zap,
  CheckCircle, XCircle, AlertTriangle, AlertCircle, ChevronDown, ChevronUp
} from 'lucide-react';

interface DeepAnalysisReportProps {
  score: number;
  category: string;
  raw: Record<string, any>;
}

interface SectionDef {
  id: string;
  label: string;
  icon: typeof Home;
  checks: { label: string; pass: boolean; detail?: string }[];
}

function organizeSections(raw: Record<string, any>): SectionDef[] {
  const sections: SectionDef[] = [];

  sections.push({
    id: 'homepage',
    label: 'Homepage',
    icon: Home,
    checks: [
      { label: 'Page Title', pass: !!(raw.title && String(raw.title).length >= 10), detail: raw.title || 'Missing' },
      { label: 'Meta Description', pass: !!(raw.meta_description && String(raw.meta_description).length >= 50), detail: raw.meta_description || 'Missing' },
      { label: 'H1 Heading', pass: (raw.headings?.h1 || 0) === 1, detail: `${raw.headings?.h1 || 0} H1 tag(s)` },
      { label: 'Clear CTA', pass: !!raw.cta_text_found },
      { label: 'Value Proposition', pass: !!raw.has_value_proposition },
      { label: 'Navigation Menu', pass: !!raw.has_navigation, detail: raw.nav_item_count ? `${raw.nav_item_count} items` : '' },
    ],
  });

  sections.push({
    id: 'seo',
    label: 'Website & Meta',
    icon: FileSearch,
    checks: [
      { label: 'HTTPS Enabled', pass: !!raw.is_https },
      { label: 'Canonical Tag', pass: !!raw.canonical_url },
      { label: 'HTML Lang Attribute', pass: !!raw.language, detail: raw.language || 'Missing' },
      { label: 'Structured Data (Schema)', pass: !!raw.has_structured_data, detail: raw.schema_types?.join(', ') || 'None' },
      { label: 'Open Graph Tags', pass: (raw.og_tags_count || 0) >= 3, detail: `${raw.og_tags_count || 0} tags` },
      { label: 'Twitter Cards', pass: (raw.twitter_card_count || 0) > 0, detail: `${raw.twitter_card_count || 0} tags` },
      { label: 'XML Sitemap', pass: !!raw.sitemap_found },
      { label: 'Robots.txt', pass: !!raw.robots_txt_found },
      { label: 'Favicon', pass: !!raw.has_favicon },
      { label: 'AI Crawlers Blocked', pass: !(raw.robots_ai_bots_blocked?.length > 0), detail: raw.robots_ai_bots_blocked?.join(', ') || 'None' },
    ],
  });

  sections.push({
    id: 'ux',
    label: 'UI / UX',
    icon: Paintbrush,
    checks: [
      { label: 'Mobile Viewport', pass: !!raw.has_viewport },
      { label: 'Footer Section', pass: !!raw.has_footer },
      { label: 'Skip Navigation (Accessibility)', pass: !!raw.has_skip_navigation },
      { label: 'ARIA Attributes', pass: !!raw.has_aria_attributes },
      { label: 'Live Chat Widget', pass: !!raw.has_live_chat },
      { label: 'Cookie Consent Banner', pass: !!raw.has_cookie_consent },
      { label: 'Testimonials / Reviews', pass: !!raw.has_testimonials },
      { label: 'Pricing Page', pass: !!raw.has_pricing_page },
      { label: 'No Auto-Playing Media', pass: !raw.has_autoplay_media },
      { label: 'No Aggressive Popups', pass: !raw.has_aggressive_popup },
    ],
  });

  sections.push({
    id: 'links',
    label: 'Links & Pages',
    icon: Link2,
    checks: [
      { label: 'Internal Links Present', pass: (raw.internal_links || 0) > 0, detail: `${raw.internal_links || 0} internal` },
      { label: 'No Broken Links', pass: !(raw.broken_links > 0), detail: raw.broken_links ? `${raw.broken_links} broken` : 'Clean' },
      { label: 'Custom 404 Page', pass: raw.has_custom_404 !== false },
      { label: 'Footer Section', pass: !!raw.has_footer },
    ],
  });

  sections.push({
    id: 'contact',
    label: 'Contact & Social',
    icon: PhoneCall,
    checks: [
      { label: 'Contact Info Found', pass: (raw.emails_count || 0) > 0 || (raw.phones_count || 0) > 0 },
      { label: 'Email Found', pass: (raw.emails_count || 0) > 0 },
      { label: 'Phone Found', pass: (raw.phones_count || 0) > 0 },
      { label: 'Clickable Phone (tel:)', pass: !!(raw.has_tel_link || raw.phones_found?.some((p: string) => p.startsWith('tel:'))) },
      { label: 'Clickable Email (mailto:)', pass: !!(raw.has_mailto || raw.emails_found?.some((e: string) => e.startsWith('mailto:'))) },
      { label: 'Social Media Presence', pass: (raw.social_count || 0) > 0, detail: raw.social_platforms?.join(', ') || 'None' },
    ],
  });

  sections.push({
    id: 'performance',
    label: 'Performance & Tech',
    icon: Zap,
    checks: [
      { label: 'Reasonable Page Size', pass: !(raw.page_size_kb < 5 || raw.page_size_kb > 3000), detail: `${raw.page_size_kb || '?'} KB` },
      { label: 'Modern Framework', pass: raw.framework && raw.framework !== 'none', detail: raw.framework || 'None detected' },
      { label: 'Analytics (GA4/GTM)', pass: !!raw.has_analytics },
      { label: 'Good Heading Structure', pass: (raw.headings?.h2 || 0) >= 3, detail: `${raw.headings?.h2 || 0} H2 tags` },
      { label: 'Images Have Alt Text', pass: !((raw.images_without_alt || 0) > (raw.total_images || 0) * 0.5), detail: raw.images_without_alt ? `${raw.images_without_alt} missing alt` : 'All good' },
      { label: 'WebP/AVIF Images', pass: !((raw.total_images || 0) > 0 && (raw.webp || 0) < (raw.total_images || 0) * 0.3) },
    ],
  });

  return sections;
}

export function DeepAnalysisReport({ score, category, raw }: DeepAnalysisReportProps) {
  const [expandedSection, setExpandedSection] = useState<string | null>(null);

  if (!raw || Object.keys(raw).length === 0) return null;

  const sections = organizeSections(raw);
  const scoreColor = score >= 70 ? 'text-emerald-400' : score >= 40 ? 'text-amber-400' : 'text-rose-400';
  const scoreBg = score >= 70 ? 'from-emerald-500/20 to-emerald-500/5' : score >= 40 ? 'from-amber-500/20 to-amber-500/5' : 'from-rose-500/20 to-rose-500/5';
  const scoreBar = score >= 70 ? 'bg-emerald-400' : score >= 40 ? 'bg-amber-400' : 'bg-rose-400';
  const totalChecks = sections.reduce((sum, s) => sum + s.checks.length, 0);
  const passedChecks = sections.reduce((sum, s) => sum + s.checks.filter((c) => c.pass).length, 0);

  return (
    <GlassCard className="p-6" delay={0.1}>
      <div className="flex items-center gap-2 mb-5">
        <FileSearch className="w-5 h-5 text-steel" />
        <h3 className="text-lg font-bold text-offwhite">Deep Website Analysis</h3>
      </div>

      <div className={cn('p-5 rounded-xl bg-gradient-to-br border mb-6', scoreBg, 'border-ocean/30')}>
        <div className="flex items-center justify-between mb-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-ice/60">Health Score</p>
            <p className={cn('text-4xl font-extrabold mt-1', scoreColor)}>{score}/100</p>
          </div>
          <div className="text-right">
            <p className="text-xs text-ice/50">Checks Passed</p>
            <p className="text-2xl font-bold text-offwhite">{passedChecks}/{totalChecks}</p>
          </div>
        </div>
        <div className="relative h-2 bg-navy/50 rounded-full overflow-hidden">
          <motion.div
            className={cn('absolute top-0 left-0 h-full rounded-full', scoreBar)}
            initial={{ width: 0 }}
            animate={{ width: `${score}%` }}
            transition={{ duration: 1, ease: 'easeOut' }}
          />
        </div>
        <p className="text-xs text-ice/50 mt-2">
          {score >= 70 ? 'Great shape — minor improvements' : score >= 40 ? 'Room for improvement' : 'Needs significant work'}
        </p>
      </div>

      <div className="space-y-3">
        {sections.map((section) => {
          const isOpen = expandedSection === section.id;
          const passed = section.checks.filter((c) => c.pass).length;
          const total = section.checks.length;
          const Icon = section.icon;

          return (
            <div key={section.id} className="border border-ocean/30 rounded-xl overflow-hidden bg-ocean/10">
              <button
                onClick={() => setExpandedSection(isOpen ? null : section.id)}
                className="w-full flex items-center justify-between p-4 hover:bg-steel/10 transition-colors text-left"
              >
                <div className="flex items-center gap-3">
                  <Icon className="w-5 h-5 text-steel" />
                  <span className="font-semibold text-offwhite text-sm">{section.label}</span>
                  <span className={cn(
                    'text-xs font-bold px-2 py-0.5 rounded-full',
                    passed === total ? 'text-emerald-400 bg-emerald-500/10' :
                    passed >= total / 2 ? 'text-amber-400 bg-amber-500/10' :
                    'text-rose-400 bg-rose-500/10'
                  )}>
                    {passed}/{total}
                  </span>
                </div>
                {isOpen ? <ChevronUp className="w-4 h-4 text-ice/60" /> : <ChevronDown className="w-4 h-4 text-ice/60" />}
              </button>
              <AnimatePresence>
                {isOpen && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="px-4 pb-4 space-y-1.5 border-t border-ocean/20 pt-3">
                      {section.checks.map((check, i) => (
                        <div key={i} className="flex items-start gap-2.5 py-1.5">
                          {check.pass ? (
                            <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                          ) : (
                            <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                          )}
                          <div className="flex-1 min-w-0">
                            <p className={cn('text-sm', check.pass ? 'text-ice/70' : 'text-ice/90 font-medium')}>
                              {check.label}
                            </p>
                            {check.detail && (
                              <p className="text-xs text-ice/40 mt-0.5 truncate">{check.detail}</p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </GlassCard>
  );
}