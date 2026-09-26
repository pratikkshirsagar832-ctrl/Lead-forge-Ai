import type { Metadata } from 'next';
import Link from 'next/link';
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  ChevronDown,
  FileCode2,
  Gauge,
  Heading,
  ImageIcon,
  Network,
  Tags,
} from 'lucide-react';
import { BlogBackground } from '@/components/blog-background';
import { Footer } from '@/components/landing/Footer';
import Header from '@/components/landing/Header';
import { SeoChecker } from './_components/SeoChecker';

const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || 'https://hyperclients.online').replace(/\/+$/, '');
const PAGE_URL = `${SITE_URL}/tools/seo-score-checker`;

const TITLE = 'Free SEO Score Checker | Online Website SEO Audit Tool';
const DESCRIPTION =
  "Use our free SEO Score Checker to analyze your website's SEO. Check meta tags, headings, alt text, sitemap, robots.txt, and more.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  keywords: ['seo score checker', 'online seo score checker', 'seo score checker free', 'website seo audit tool'],
  alternates: { canonical: PAGE_URL },
  openGraph: { title: TITLE, description: DESCRIPTION, url: PAGE_URL, siteName: 'Hyperclients', type: 'website' },
  twitter: { card: 'summary_large_image', title: TITLE, description: DESCRIPTION },
};

const BENEFITS = [
  'Identify on-page SEO issues',
  'Find missing or incomplete meta tags',
  'Review your heading structure',
  'Identify missing image alt text',
  'Check important technical SEO elements',
  'Review robots.txt availability',
  'Check for an XML sitemap',
  'Find areas that need optimization',
  'Track improvements after making SEO changes',
];

const ANALYZES = [
  {
    icon: Tags,
    title: 'Meta Tags',
    body: 'Meta titles and meta descriptions help search engines and users understand the topic of a webpage. Optimized metadata can also help create a clear and relevant search result. The checker helps you identify potential issues with these important SEO elements.',
  },
  {
    icon: Heading,
    title: 'Headings',
    body: 'A well-organized heading structure makes your content easier to scan and understand. Proper use of H1, H2, and other headings can help establish a logical content hierarchy.',
  },
  {
    icon: ImageIcon,
    title: 'Image Alt Text',
    body: 'Alternative text helps describe images to users who rely on assistive technologies and can provide search engines with additional context. The checker can help identify images that may be missing useful alt attributes.',
  },
  {
    icon: Bot,
    title: 'Robots.txt',
    body: 'The robots.txt file provides instructions to search engine crawlers about which areas of a website they can access. Reviewing robots.txt is an important part of a basic technical SEO audit.',
  },
  {
    icon: Network,
    title: 'XML Sitemap',
    body: 'An XML sitemap helps search engines discover important URLs on your website. Checking sitemap availability is useful when reviewing the technical SEO setup of a website.',
  },
];

const STEPS = [
  'Enter your website URL into the SEO Score Checker.',
  'Click the check button to start the analysis.',
  'Review the SEO audit results and identify elements that need improvement.',
  'Make the necessary changes to your website.',
  'Run another check after implementing your improvements to measure progress.',
];

const AUDIENCE = [
  'SEO professionals',
  'Digital marketers',
  'Website owners',
  'Freelancers',
  'Agencies',
  'Bloggers',
  'Business owners',
];

const FAQS = [
  {
    q: 'What is an SEO Score Checker?',
    a: 'An SEO Score Checker is a tool that analyzes important SEO factors on a webpage, including meta tags, headings, image alt text, sitemap, and robots.txt. It helps identify areas that may need optimization.',
  },
  {
    q: 'How can I check my website SEO score?',
    a: 'Enter your website URL into the Hyperclients SEO Score Checker and start the analysis. The tool reviews key SEO elements and provides insights into areas that may need improvement.',
  },
  {
    q: 'Is the Hyperclients SEO Score Checker free?',
    a: 'Yes, you can use the Hyperclients SEO Score Checker to perform a basic SEO analysis of your website without paying for the tool.',
  },
  {
    q: 'What factors does an SEO Score Checker analyze?',
    a: 'The tool can check important elements such as meta titles, meta descriptions, heading structure, image alt text, robots.txt, XML sitemap, and other on-page SEO factors.',
  },
  {
    q: 'Does an SEO score guarantee higher Google rankings?',
    a: 'No. An SEO score is an indicator of website optimization and does not guarantee higher rankings. Google rankings also depend on content quality, search intent, backlinks, competition, technical SEO, user experience, and other factors.',
  },
  {
    q: 'How often should I check my website SEO score?',
    a: 'You can check your SEO score regularly, especially after publishing new pages, updating content, making technical SEO changes, or redesigning your website. Regular audits can help you identify and fix SEO issues over time.',
  },
];

const JSON_LD = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'WebApplication',
      name: 'Hyperclients SEO Score Checker',
      url: PAGE_URL,
      description: DESCRIPTION,
      applicationCategory: 'BusinessApplication',
      operatingSystem: 'Any',
      offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
    },
    {
      '@type': 'FAQPage',
      mainEntity: FAQS.map(({ q, a }) => ({
        '@type': 'Question',
        name: q,
        acceptedAnswer: { '@type': 'Answer', text: a },
      })),
    },
  ],
};

function SectionHeading({ children }: { children: React.ReactNode }) {
  return <h2 className="text-2xl md:text-3xl font-bold text-offwhite font-heading mb-4">{children}</h2>;
}

export default function SeoScoreCheckerPage() {
  return (
    <div className="relative min-h-screen bg-navy text-ice font-sans overflow-hidden">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(JSON_LD) }} />
      <BlogBackground />
      <Header />

      <main className="container relative z-10 mx-auto px-6 pt-28 pb-20 max-w-4xl">
        {/* ── Hero + tool ── */}
        <section id="checker" className="scroll-mt-28">
          <p className="text-xs font-semibold uppercase tracking-widest text-brand-accent-light mb-2 flex items-center gap-2">
            <Gauge className="w-4 h-4" /> Free Website SEO Audit Tool
          </p>
          <h1 className="text-4xl md:text-5xl font-bold text-offwhite font-heading mb-4">
            SEO <span className="gradient-text-premium">Score Checker</span>
          </h1>
          <p className="text-ice/80 text-lg leading-relaxed mb-3">
            Want to know how well your website is optimized for search engines? Use the Hyperclients SEO Score
            Checker to analyze your website and identify important SEO issues that may affect its visibility,
            crawlability, and user experience.
          </p>
          <p className="text-ice/65 leading-relaxed mb-8">
            With an online SEO score checker, you can quickly review essential SEO elements without manually
            checking every page. Simply enter your website URL, run the analysis, and discover areas that may need
            improvement.
          </p>

          <SeoChecker />

          <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5 text-xs text-ice/50">
            {['100% free', 'No login required', 'Results in seconds'].map((t) => (
              <li key={t} className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" /> {t}
              </li>
            ))}
          </ul>
        </section>

        {/* ── What is ── */}
        <section className="mt-20">
          <SectionHeading>What Is an SEO Score Checker?</SectionHeading>
          <p className="text-ice/80 leading-relaxed mb-4">
            An SEO Score Checker is a tool that evaluates a webpage based on important search engine optimization
            factors. It helps identify common on-page and technical SEO issues so you can understand what is working
            well and what needs attention.
          </p>
          <p className="text-ice/80 leading-relaxed">
            The Hyperclients SEO score checker free tool allows you to perform a quick website SEO analysis without
            complicated setup. You can use the results to identify optimization opportunities and improve your
            website&apos;s overall SEO health.
          </p>
        </section>

        {/* ── Why ── */}
        <section className="mt-16">
          <SectionHeading>Why Check Your Website SEO Score?</SectionHeading>
          <p className="text-ice/80 leading-relaxed mb-6">
            Search engines need to crawl, understand, and index your webpages before they can appear in relevant
            search results. Issues such as missing meta tags, poor heading structure, missing image alt text, or
            technical configuration problems can affect how effectively search engines understand your website.
          </p>
          <div className="glass-card rounded-2xl p-6 md:p-8">
            <h3 className="text-sm font-bold uppercase tracking-widest text-brand-accent-light mb-5">
              Regular website SEO checks can help you
            </h3>
            <ul className="grid sm:grid-cols-2 gap-x-8 gap-y-3">
              {BENEFITS.map((b) => (
                <li key={b} className="flex items-start gap-2.5 text-[15px] text-ice/85">
                  <CheckCircle2 className="w-4.5 h-4.5 text-emerald-400 shrink-0 mt-0.5" /> {b}
                </li>
              ))}
            </ul>
          </div>
          <p className="text-ice/70 leading-relaxed mt-6">
            Using an online SEO score checker can save time by bringing several basic SEO checks together in one
            place.
          </p>
        </section>

        {/* ── What it analyzes ── */}
        <section className="mt-16">
          <SectionHeading>What Does the Hyperclients SEO Checker Analyze?</SectionHeading>
          <p className="text-ice/80 leading-relaxed mb-6">
            The Hyperclients SEO Score Checker reviews several important elements of your webpage.
          </p>
          <div className="grid md:grid-cols-2 gap-5">
            {ANALYZES.map(({ icon: Icon, title, body }, i) => (
              <div
                key={title}
                className={`glass-card-premium rounded-2xl p-6 ${i === ANALYZES.length - 1 ? 'md:col-span-2' : ''}`}
              >
                <div className="flex items-center gap-3 mb-3">
                  <span className="inline-flex items-center justify-center w-10 h-10 rounded-xl bg-primary/20 border border-primary/30">
                    <Icon className="w-5 h-5 text-brand-accent-light" />
                  </span>
                  <h3 className="text-lg font-bold text-offwhite font-heading">{title}</h3>
                </div>
                <p className="text-ice/75 leading-relaxed text-[15px]">{body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ── How to use ── */}
        <section className="mt-16">
          <SectionHeading>How to Use the Hyperclients SEO Score Checker</SectionHeading>
          <p className="text-ice/80 leading-relaxed mb-6">Checking your website is simple:</p>
          <ol className="space-y-3">
            {STEPS.map((step, i) => (
              <li key={step} className="glass-card rounded-xl px-5 py-4 flex items-start gap-4">
                <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-brand-accent/15 text-brand-accent-light text-sm font-bold shrink-0 ring-1 ring-brand-accent/30">
                  {i + 1}
                </span>
                <p className="text-ice/85 leading-relaxed pt-1">
                  <span className="font-semibold text-offwhite">Step {i + 1}:</span> {step}
                </p>
              </li>
            ))}
          </ol>
          <p className="text-ice/70 leading-relaxed mt-6">
            The SEO score checker free tool can be useful when performing regular website audits, reviewing newly
            published pages, or checking the impact of SEO changes.
          </p>
        </section>

        {/* ── Who ── */}
        <section className="mt-16">
          <SectionHeading>Who Can Use This SEO Audit Tool?</SectionHeading>
          <p className="text-ice/80 leading-relaxed mb-5">
            The Hyperclients SEO Score Checker can be useful for SEO professionals, digital marketers, website
            owners, freelancers, agencies, bloggers, and business owners.
          </p>
          <ul className="flex flex-wrap gap-2 mb-5">
            {AUDIENCE.map((a) => (
              <li key={a} className="px-3 py-1.5 rounded-full text-sm bg-ocean/40 border border-steel/15 text-ice/80">
                {a}
              </li>
            ))}
          </ul>
          <p className="text-ice/80 leading-relaxed">
            Whether you manage a small business website, ecommerce store, service website, or blog, a basic SEO
            audit can help you identify optimization opportunities and technical issues.
          </p>
        </section>

        {/* ── FAQ ── */}
        <section className="mt-16">
          <SectionHeading>Frequently Asked Questions</SectionHeading>
          <div className="space-y-3">
            {FAQS.map(({ q, a }, i) => (
              <details key={q} className="group glass-card rounded-xl px-5 py-4" open={i === 0}>
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-semibold text-offwhite [&::-webkit-details-marker]:hidden">
                  <h3 className="text-base">{i + 1}. {q}</h3>
                  <ChevronDown className="w-4 h-4 text-ice/50 shrink-0 transition-transform group-open:rotate-180" />
                </summary>
                <p className="mt-3 text-ice/75 leading-relaxed text-[15px]">{a}</p>
              </details>
            ))}
          </div>
        </section>

        {/* ── CTA ── */}
        <section className="mt-16 glass-card-premium rounded-2xl p-6 md:p-10 text-center">
          <FileCode2 className="w-8 h-8 text-brand-accent-light mx-auto mb-3" />
          <h2 className="text-2xl md:text-3xl font-bold text-offwhite font-heading mb-3">
            Check your website SEO score now
          </h2>
          <p className="text-ice/75 leading-relaxed mb-6 max-w-xl mx-auto">
            Run a free SEO audit in seconds, then find clients who need exactly this kind of help with
            Hyperclients.
          </p>
          <div className="flex flex-col sm:flex-row gap-3 justify-center">
            <a href="#checker" className="btn-gradient-cyan rounded-xl px-6 py-3 text-sm inline-flex items-center justify-center gap-2">
              Check SEO Score <ArrowRight className="w-4 h-4" />
            </a>
            <Link
              href="/login?mode=signup"
              className="rounded-xl px-6 py-3 text-sm font-semibold inline-flex items-center justify-center gap-2 border border-steel/30 text-ice hover:bg-ocean/40 transition-colors"
            >
              Find Leads Free
            </Link>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
