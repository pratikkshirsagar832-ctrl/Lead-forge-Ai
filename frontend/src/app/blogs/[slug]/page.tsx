import type { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { CalendarDays, Clock, ArrowRight } from 'lucide-react';
import { getBlog } from '../../../../lib/blog-store';
import { renderMarkdown } from '../../../components/blog-markdown';
import { BlogBackground } from '../../../components/blog-background';
import { BlogImage } from '../../../components/blog-image';
import { Footer } from '../../../components/landing/Footer';
import Header from '../../../components/landing/Header';

export const dynamic = 'force-dynamic';

interface PageProps {
  params: { slug: string };
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const post = getBlog(params.slug);
  if (!post) return {};
  const url = `https://hyperclients.online/blogs/${post.slug}`;
  return {
    title: post.metaTitle || post.title,
    description: post.metaDescription || post.excerpt,
    keywords: post.keywords,
    alternates: { canonical: url },
    openGraph: {
      title: post.metaTitle || post.title,
      description: post.metaDescription || post.excerpt,
      url,
      type: 'article',
      publishedTime: `${post.date}T10:00:00.000Z`,
      authors: [post.author],
      siteName: 'Hyperclients',
      ...(post.coverImage ? { images: [{ url: post.coverImage, alt: post.title }] } : {}),
    },
    robots: { index: true, follow: true },
  };
}

export default function BlogPostPage({ params }: PageProps) {
  const post = getBlog(params.slug);
  if (!post) notFound();

  const jsonLd = {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'BlogPosting',
        headline: post.title,
        description: post.metaDescription || post.excerpt,
        datePublished: `${post.date}T10:00:00.000Z`,
        dateModified: `${post.date}T10:00:00.000Z`,
        author: { '@type': 'Person', name: post.author },
        publisher: { '@type': 'Organization', name: 'Hyperclients', url: 'https://hyperclients.online' },
        mainEntityOfPage: `https://hyperclients.online/blogs/${post.slug}`,
        keywords: post.keywords?.join(', ') || post.category,
      },
      ...(post.faqs?.length
        ? [
            {
              '@type': 'FAQPage',
              mainEntity: post.faqs.map((f) => ({
                '@type': 'Question',
                name: f.q,
                acceptedAnswer: { '@type': 'Answer', text: f.a },
              })),
            },
          ]
        : []),
    ],
  };

  const displayDate = new Date(post.date).toLocaleDateString('en-IN', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
  const readMinutes = Math.max(1, Math.round(post.content.split(' ').length / 200));

  return (
    <div className="relative min-h-screen bg-navy text-ice font-sans overflow-hidden">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <BlogBackground />
      <Header />

      <div className="container relative z-10 mx-auto px-6 pt-28 pb-20 max-w-3xl">
        <nav className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-muted mb-6">
          <Link href="/" className="hover:text-cyan-300 transition-colors">Home</Link>
          <span>/</span>
          <Link href="/blogs" className="hover:text-cyan-300 transition-colors">Blog</Link>
          <span>/</span>
          <span className="text-cyan-300 truncate max-w-[40ch]">{post.title}</span>
        </nav>

        <Link
          href="/"
          className="inline-flex items-center gap-2.5 rounded-full border border-steel/20 bg-white/[0.04] backdrop-blur-sm px-3.5 py-1.5 mb-5 hover:border-cyan-300/30 transition-colors"
        >
          <img
            src="/publisher.png"
            alt="Hyperclients"
            width={24}
            height={24}
            className="w-6 h-6 rounded-full object-cover"
          />
          <span className="text-xs font-semibold text-ice/80">
            Published by <span className="text-cyan-200 font-bold">Bhaskar</span>
          </span>
        </Link>

        <div className="flex flex-wrap items-center gap-3 text-xs font-semibold uppercase tracking-wide text-text-muted mb-4">
          <span className="px-2.5 py-1 rounded-full bg-primary/15 text-primary-light border border-primary/20">
            {post.category}
          </span>
          <span className="flex items-center gap-1.5">
            <CalendarDays className="w-3.5 h-3.5" />
            {displayDate}
          </span>
          <span className="flex items-center gap-1.5">
            <Clock className="w-3.5 h-3.5" />
            {readMinutes} min read
          </span>
        </div>

        <h1 className="text-3xl md:text-5xl font-bold text-offwhite font-heading leading-tight mb-8">
          {post.title.split(/\s*\(\s*/)[0]}
          {post.title.includes('(') && (
            <>
              {' '}
              <span className="gradient-text-premium">({post.title.split('(').slice(1).join('(')}</span>
            </>
          )}
        </h1>

        {post.coverImage && (
          <BlogImage
            src={post.coverImage}
            alt={post.title}
            wrapperClassName="relative rounded-2xl overflow-hidden mb-8 border border-steel/20"
            imgClassName="w-full aspect-[21/9] object-cover"
            overlayClassName="absolute inset-0 bg-gradient-to-t from-[#0C1024]/60 via-transparent to-transparent"
          />
        )}

        <article className="text-[17px]">{renderMarkdown(post.content)}</article>

        <div className="glass-card gradient-border rounded-2xl p-6 md:p-8 mt-10">
          <h2 className="text-2xl font-bold text-offwhite font-heading mb-3">
            Ready to Build a Predictable Pipeline?
          </h2>
          <p className="text-ice/85 leading-relaxed mb-6">
            Hyperclients turns these signals into a ranked list of ready-to-buy leads - traffic drops,
            competitor gaps, ad dependence, expansion triggers, and intent searches, all in one dashboard.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link
              href="/login"
              className="btn-gradient-cyan rounded-xl px-6 py-3 text-sm inline-flex items-center gap-2"
            >
              Try It Free <ArrowRight className="w-4 h-4" />
            </Link>
            <Link href="/pricing" className="btn-glass rounded-xl px-6 py-3 text-sm">
              See Pricing
            </Link>
          </div>
        </div>

        {post.faqs && post.faqs.length > 0 && (
          <section className="mt-12">
            <h2 className="text-2xl md:text-3xl font-bold text-offwhite font-heading mb-4">
              Frequently Asked Questions
            </h2>
            <div className="space-y-3">
              {post.faqs.map((faq, i) => (
                <details
                  key={i}
                  className="group glass-card rounded-xl overflow-hidden open:border-cyan-300/30"
                >
                  <summary className="list-none flex items-center justify-between gap-4 cursor-pointer px-5 py-4 font-semibold text-offwhite hover:text-cyan-200 transition-colors select-none">
                    {faq.q}
                    <span className="text-cyan-300 text-xl leading-none transition-transform duration-300 group-open:rotate-45">
                      +
                    </span>
                  </summary>
                  <p className="px-5 pb-5 text-ice/85 leading-relaxed text-sm">{faq.a}</p>
                </details>
              ))}
            </div>
          </section>
        )}

        <aside className="mt-12 glass-card rounded-2xl p-6 md:p-8 border-t-2 border-t-cyan-300/40">
          <p className="text-xs font-bold uppercase tracking-widest text-cyan-300 mb-3">About the Author</p>
          <div className="flex items-start gap-4">
            <img
              src="/publisher.png"
              alt={post.author}
              width={48}
              height={48}
              className="w-12 h-12 shrink-0 rounded-full object-cover border border-steel/20"
            />
            <div>
              <h3 className="font-heading font-bold text-offwhite">{post.author}</h3>
              {post.authorBio && (
                <p className="text-ice/80 leading-relaxed text-sm mt-1">{post.authorBio}</p>
              )}
            </div>
          </div>
        </aside>
      </div>
      <Footer />
    </div>
  );
}