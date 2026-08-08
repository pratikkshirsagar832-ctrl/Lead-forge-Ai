'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Plus, Trash2, Pencil, X, LogOut, ExternalLink, CheckCircle2 } from 'lucide-react';

interface BlogFaq {
  q: string;
  a: string;
}

interface BlogPost {
  id: string;
  slug: string;
  title: string;
  excerpt: string;
  category: string;
  date: string;
  content: string;
  faqs?: BlogFaq[];
  metaTitle?: string;
  metaDescription?: string;
  keywords?: string[];
  author: string;
  authorBio: string;
}

const emptyForm = {
  title: '',
  slug: '',
  category: 'Lead Scoring',
  excerpt: '',
  date: new Date().toISOString().slice(0, 10),
  content: '',
  faqs: '',
  metaTitle: '',
  metaDescription: '',
  keywords: '',
  author: 'Hyperclients Team',
  authorBio: '',
};

export default function AdminPanel() {
  const router = useRouter();
  const [blogs, setBlogs] = useState<BlogPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(emptyForm);
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const flash = (msg: string) => {
    setNotice(msg);
    setTimeout(() => setNotice(''), 3000);
  };

  const load = useCallback(async () => {
    const res = await fetch('/api/admin/blogs');
    if (res.status === 401) {
      router.push('/admin/login');
      return;
    }
    const data = await res.json();
    setBlogs(data.blogs || []);
    setLoading(false);
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  function setField(field: keyof typeof emptyForm, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  function parseForm() {
    return {
      title: form.title.trim(),
      slug: form.slug.trim() || undefined,
      excerpt: form.excerpt.trim(),
      category: form.category.trim() || 'General',
      date: form.date,
      content: form.content,
      faqs: form.faqs
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const sep = line.indexOf('|');
          return sep > -1
            ? { q: line.slice(0, sep).trim(), a: line.slice(sep + 1).trim() }
            : { q: line, a: '' };
        })
        .filter((f) => f.q && f.a),
      metaTitle: form.metaTitle.trim(),
      metaDescription: form.metaDescription.trim(),
      keywords: form.keywords
        .split(',')
        .map((k) => k.trim())
        .filter(Boolean),
      author: form.author.trim() || 'Hyperclients Team',
      authorBio: form.authorBio.trim(),
    };
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const payload = parseForm();
    try {
      const res = await fetch(editingSlug ? `/api/admin/blogs/${editingSlug}` : '/api/admin/blogs', {
        method: editingSlug ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        flash(data?.error || 'Save failed');
        return;
      }
      flash(editingSlug ? 'Blog updated' : 'Blog published');
      setForm(emptyForm);
      setEditingSlug(null);
      await load();
    } catch {
      flash('Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  function startEdit(blog: BlogPost) {
    setEditingSlug(blog.slug);
    setForm({
      title: blog.title,
      slug: blog.slug,
      excerpt: blog.excerpt,
      date: blog.date,
      content: blog.content,
      faqs: (blog.faqs || []).map((f) => `${f.q} | ${f.a}`).join('\n'),
      metaTitle: blog.metaTitle || '',
      metaDescription: blog.metaDescription || '',
      keywords: (blog.keywords || []).join(', '),
      author: blog.author,
      authorBio: blog.authorBio || '',
      category: blog.category,
    });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function handleDelete(blog: BlogPost) {
    if (!confirm(`Delete "${blog.title}"?\nThis cannot be undone.`)) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/admin/blogs/${blog.slug}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        flash(data?.error || 'Delete failed');
        return;
      }
      flash('Blog deleted');
      if (editingSlug === blog.slug) {
        setEditingSlug(null);
        setForm(emptyForm);
      }
      await load();
    } catch {
      flash('Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  async function handleLogout() {
    await fetch('/api/admin/logout', { method: 'POST' });
    router.push('/admin/login');
    router.refresh();
  }

  const inputCls =
    'w-full rounded-xl bg-bg-elevated border border-primary/20 px-4 py-2.5 text-sm text-offwhite placeholder:text-text-muted/60 outline-none focus:border-cyan-300/50 focus:ring-2 focus:ring-cyan-300/20 transition-all';
  const labelCls = 'block text-xs font-semibold uppercase tracking-wider text-cyan-300/80 mb-1.5';

  return (
    <div className="min-h-screen bg-navy text-ice font-sans">
      <div className="container mx-auto px-6 pt-24 pb-16 max-w-5xl">
        <header className="flex items-center justify-between flex-wrap gap-4 mb-8">
          <div>
            <h1 className="text-3xl md:text-4xl font-bold text-offwhite font-heading">
              Blog <span className="gradient-text-premium">Admin</span>
            </h1>
            <p className="text-text-secondary text-sm mt-1">
              Add, edit, and delete blog posts. Changes go live instantly at{' '}
              <a className="text-cyan-300 hover:underline" href="/blogs">
                /blogs
              </a>
              .
            </p>
          </div>
          <button
            onClick={handleLogout}
            className="btn-glass rounded-xl px-4 py-2 text-sm inline-flex items-center gap-2"
          >
            <LogOut className="w-4 h-4" /> Logout
          </button>
        </header>

        {notice && (
          <div className="mb-6 flex items-center gap-2 text-sm font-semibold text-emerald bg-emerald/10 border border-emerald/25 rounded-xl px-4 py-3">
            <CheckCircle2 className="w-4 h-4" /> {notice}
          </div>
        )}

        <section className="glass-card-premium rounded-2xl p-6 md:p-8 mb-10">
          <h2 className="text-xl font-bold text-offwhite font-heading mb-6 flex items-center gap-2">
            {editingSlug ? <Pencil className="w-5 h-5 text-cyan-300" /> : <Plus className="w-5 h-5 text-cyan-300" />}
            {editingSlug ? `Edit: ${editingSlug}` : 'New Blog Post'}
          </h2>

          <form onSubmit={handleSave} className="space-y-5">
            <div className="grid md:grid-cols-2 gap-4">
              <div className="md:col-span-2">
                <label className={labelCls}>Title *</label>
                <input
                  className={inputCls}
                  value={form.title}
                  onChange={(e) => setField('title', e.target.value)}
                  placeholder="e.g. 5 Signs a Local Business Is Ready to Buy SEO"
                  required
                />
              </div>
              <div>
                <label className={labelCls}>Slug (auto if empty)</label>
                <input
                  className={inputCls}
                  value={form.slug}
                  onChange={(e) => setField('slug', e.target.value)}
                  placeholder="my-blog-post"
                />
              </div>
              <div>
                <label className={labelCls}>Category</label>
                <input
                  className={inputCls}
                  value={form.category}
                  onChange={(e) => setField('category', e.target.value)}
                  placeholder="Lead Scoring"
                />
              </div>
              <div>
                <label className={labelCls}>Publish Date</label>
                <input
                  type="date"
                  className={inputCls}
                  value={form.date}
                  onChange={(e) => setField('date', e.target.value)}
                />
              </div>
              <div>
                <label className={labelCls}>Author</label>
                <input
                  className={inputCls}
                  value={form.author}
                  onChange={(e) => setField('author', e.target.value)}
                  placeholder="Bhaskar Gupta"
                />
              </div>
              <div className="md:col-span-2">
                <label className={labelCls}>Excerpt (shown on /blogs)</label>
                <textarea
                  className={`${inputCls} min-h-20 resize-y`}
                  value={form.excerpt}
                  onChange={(e) => setField('excerpt', e.target.value)}
                  placeholder="Short summary shown on the blog index..."
                />
              </div>
              <div className="md:col-span-2">
                <label className={labelCls}>Content (markdown-lite) *</label>
                <textarea
                  className={`${inputCls} min-h-64 font-mono text-xs leading-relaxed resize-y`}
                  value={form.content}
                  onChange={(e) => setField('content', e.target.value)}
                  placeholder={'## Heading\n\nParagraph text. Use **bold** for emphasis.\n\n- list item\n\n> callout / quote'}
                  required
                />
                <p className="text-[11px] text-text-muted mt-1.5">
                  Supports <code>## headings</code>, <code>**bold**</code>, <code>- lists</code>, and{' '}
                  <code>&gt; quotes</code>.
                </p>
              </div>
              <div className="md:col-span-2">
                <label className={labelCls}>FAQ (one per line: question | answer)</label>
                <textarea
                  className={`${inputCls} min-h-24 font-mono text-xs resize-y`}
                  value={form.faqs}
                  onChange={(e) => setField('faqs', e.target.value)}
                  placeholder={'How much do you charge? | Most local businesses pay 15k-50k INR/month.\nDo you offer a trial? | Yes - 3 free searches to test.'}
                />
              </div>
              <div>
                <label className={labelCls}>Meta Title (SEO)</label>
                <input
                  className={inputCls}
                  value={form.metaTitle}
                  onChange={(e) => setField('metaTitle', e.target.value)}
                  placeholder="Under 60 characters"
                />
              </div>
              <div>
                <label className={labelCls}>Meta Description (SEO)</label>
                <input
                  className={inputCls}
                  value={form.metaDescription}
                  onChange={(e) => setField('metaDescription', e.target.value)}
                  placeholder="Under 160 characters"
                />
              </div>
              <div className="md:col-span-2">
                <label className={labelCls}>Focus Keywords (comma separated)</label>
                <input
                  className={inputCls}
                  value={form.keywords}
                  onChange={(e) => setField('keywords', e.target.value)}
                  placeholder="local SEO leads, buy SEO services"
                />
              </div>
              <div className="md:col-span-2">
                <label className={labelCls}>Author Bio</label>
                <textarea
                  className={`${inputCls} min-h-16 resize-y`}
                  value={form.authorBio}
                  onChange={(e) => setField('authorBio', e.target.value)}
                  placeholder="Short bio for the About the Author box..."
                />
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="submit"
                disabled={busy}
                className="btn-gradient-cyan rounded-xl px-6 py-3 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {busy ? 'Saving...' : editingSlug ? 'Save Changes' : 'Publish Blog'}
              </button>
              {editingSlug && (
                <button
                  type="button"
                  onClick={() => {
                    setEditingSlug(null);
                    setForm(emptyForm);
                  }}
                  className="btn-glass rounded-xl px-5 py-3 text-sm inline-flex items-center gap-2"
                >
                  <X className="w-4 h-4" /> Cancel Edit
                </button>
              )}
            </div>
          </form>
        </section>

        <section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold text-offwhite font-heading">
              Published Posts <span className="text-text-muted text-sm font-normal">({blogs.length})</span>
            </h2>
          </div>

          {loading ? (
            <div className="glass-card rounded-2xl p-8 text-center text-text-muted">Loading...</div>
          ) : blogs.length === 0 ? (
            <div className="glass-card rounded-2xl p-8 text-center text-text-muted">
              No blogs yet. Write your first post above.
            </div>
          ) : (
            <div className="space-y-3">
              {blogs.map((blog) => (
                <div
                  key={blog.id}
                  className="glass-card-premium rounded-xl p-4 md:p-5 flex flex-wrap items-center gap-4"
                >
                  <div className="flex-1 min-w-52">
                    <h3 className="font-heading font-bold text-offwhite">{blog.title}</h3>
                    <p className="text-xs text-text-muted mt-1 flex items-center gap-2 flex-wrap">
                      <span className="text-cyan-300">/{blog.slug}</span>
                      <span>{blog.category}</span>
                      <span>{blog.date}</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <a
                      href={`/blogs/${blog.slug}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      title="View post"
                      className="p-2.5 rounded-lg bg-bg-hover text-text-secondary hover:text-cyan-300 transition-colors"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </a>
                    <button
                      onClick={() => startEdit(blog)}
                      title="Edit post"
                      className="p-2.5 rounded-lg bg-bg-hover text-text-secondary hover:text-cyan-300 transition-colors"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(blog)}
                      title="Delete post"
                      disabled={busy}
                      className="p-2.5 rounded-lg bg-bg-hover text-rose hover:bg-rose/20 transition-colors disabled:opacity-50"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}