import type { Metadata } from 'next';
import Link from 'next/link';
import { CalendarDays, ArrowRight } from 'lucide-react';
import { getBlogs } from '../../../lib/blog-store';
import { BlogBackground } from '../../components/blog-background';
import { BlogImage } from '../../components/blog-image';
import { Footer } from '../../components/landing/Footer';
import Header from '../../components/landing/Header';

export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: 'Blog — Hyperclients',
  description:
    'Lead generation insights for SEO agencies and freelancers: how to find businesses that are ready to buy, not just ready to talk.',
};

export default function BlogsIndexPage() {
  const posts = getBlogs();

  return (
    <div className="relative min-h-screen bg-navy text-ice font-sans overflow-hidden">
      <BlogBackground />
      <Header />
      <div className="container relative z-10 mx-auto px-6 pt-28 pb-16 max-w-4xl">
        <p className="text-xs font-semibold uppercase tracking-widest text-brand-accent-light mb-2">Blog</p>
        <h1 className="text-4xl md:text-5xl font-bold text-offwhite font-heading mb-3">
          Lead Generation <span className="gradient-text-premium">Guides and Blogs</span>
        </h1>

        {posts.length === 0 ? (
          <div className="glass-card rounded-2xl p-10 text-center">
            <p className="text-ice/80">New articles are on the way. Check back soon.</p>
          </div>
        ) : (
          <div className="space-y-6">
            {posts.map((post) => (
              <Link
                key={post.slug}
                href={`/blogs/${post.slug}`}
                className="block group glass-card-premium rounded-2xl overflow-hidden transition-colors duration-300 hover:border-secondary/40"
              >
                {post.coverImage && (
                  <BlogImage
                    src={post.coverImage}
                    alt={post.title}
                    wrapperClassName="relative aspect-[16/7] overflow-hidden"
                    imgClassName="w-full h-full object-cover"
                    overlayClassName="absolute inset-0 bg-gradient-to-t from-[#06231F] via-transparent to-transparent"
                  />
                )}
                <div className="p-6 md:p-8">
                  <div className="flex items-center gap-3 text-xs font-semibold text-text-muted uppercase tracking-wide mb-3">
                    <span className="px-2.5 py-1 rounded-full bg-primary/15 text-primary-light border border-primary/20">
                      {post.category}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <CalendarDays className="w-3.5 h-3.5" />
                      {new Date(post.date).toLocaleDateString('en-IN', {
                        day: 'numeric',
                        month: 'long',
                        year: 'numeric',
                      })}
                    </span>
                  </div>
                  <h2 className="text-xl md:text-2xl font-bold text-offwhite font-heading mb-2 group-hover:text-secondary transition-colors">
                    {post.title}
                  </h2>
                  <p className="text-ice/85 leading-relaxed">{post.excerpt}</p>
                  <div className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-brand-accent group-hover:gap-3 transition-all">
                    Read article <ArrowRight className="w-4 h-4" />
                  </div>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
      <Footer />
    </div>
  );
}