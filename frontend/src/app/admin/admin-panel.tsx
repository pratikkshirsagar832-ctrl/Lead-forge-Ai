'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Plus, Trash2, Pencil, X, LogOut, ExternalLink, CheckCircle2, Bold, Link2, List, Quote, Image as ImageIcon, Eye, PenLine, UploadCloud, Loader2 } from 'lucide-react';
import { renderMarkdown } from '../../components/blog-markdown';

function ToolbarBtn({
  onClick,
  title,
  children,
}: {
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="px-2.5 py-1.5 rounded-lg bg-bg-hover text-text-secondary hover:text-cyan-300 hover:bg-steel/20 text-xs font-semibold transition-colors"
    >
      {children}
    </button>
  );
}

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
  coverImage?: string;
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
  coverImage: '',
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
  const [showPreview, setShowPreview] = useState(false);
  const [uploading, setUploading] = useState(false);
  const contentRef = useRef<HTMLTextAreaElement>(null);
  const coverImgRef = useRef<HTMLInputElement>(null);
  const contentImgRef = useRef<HTMLInputElement>(null);

  async function uploadFile(file: File): Promise<string> {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch('/api/admin/upload', { method: 'POST', body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Upload failed (${res.status})`);
    return data.url as string;
  }

  async function handleCoverFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setUploading(true);
    try {
      const url = await uploadFile(file);
      setField('coverImage', url);
      flash('Cover uploaded');
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function handleContentImageFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) {
      const url = window.prompt('Image URL (https://... or /local-image.png):');
      if (!url) return;
      const alt = window.prompt('Alt text (optional):') || '';
      insertAtCursor(`![${alt}](${url})`, '', '');
      return;
    }
    setUploading(true);
    try {
      const url = await uploadFile(file);
      const alt = window.prompt('Alt text (optional):') || 'Image';
      insertAtCursor(`![${alt}](${url})`, '', '');
      flash('Image added to content');
    } catch (err) {
      alert((err as Error).message);
    } finally {
      setUploading(false);
    }
  }

  function insertAtCursor(before: string, after: string, placeholder: string) {
    const ta = contentRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = form.content.slice(start, end) || placeholder;
    const next = form.content.slice(0, start) + before + selected + after + form.content.slice(end);
    setField('content', next);
    requestAnimationFrame(() => {
      ta.focus();
      const pos = start + before.length + selected.length;
      ta.setSelectionRange(pos, pos);
    });
  }

  function insertAtLineStart(prefix: string) {
    const ta = contentRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const lineStart = form.content.lastIndexOf('\n', start - 1) + 1;
    const rest = form.content.slice(lineStart).replace(/^\s*/, '');
    const next = form.content.slice(0, lineStart) + prefix + rest;
    setField('content', next);
    requestAnimationFrame(() => {
      ta.focus();
      const pos = lineStart + prefix.length;
      ta.setSelectionRange(pos, pos);
    });
  }

  function insertInterlink(slug: string, title: string) {
    const ta = contentRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const label = form.content.slice(start, end) || title;
    const link = `[${label}](/blogs/${slug})`;
    const next = form.content.slice(0, start) + link + form.content.slice(end);
    setField('content', next);
    requestAnimationFrame(() => {
      ta.focus();
      const pos = start + link.length;
      ta.setSelectionRange(pos, pos);
    });
  }

  function insertImage() {
    contentImgRef.current?.click();
  }

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
      coverImage: form.coverImage.trim() || undefined,
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
      coverImage: blog.coverImage || '',
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
    <div className="relative min-h-screen bg-navy text-ice font-sans overflow-hidden">
      <div className="pointer-events-none absolute -top-32 -right-32 w-96 h-96 bg-primary/10 rounded-full blur-[120px]" />
      <div className="pointer-events-none absolute bottom-0 -left-32 w-96 h-96 bg-cyan-300/[0.06] rounded-full blur-[120px]" />
      <div className="relative z-10 container mx-auto px-6 pt-24 pb-16 max-w-5xl">
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
                <label className={labelCls}>Cover Image</label>
                <input
                  className={inputCls}
                  value={form.coverImage}
                  onChange={(e) => setField('coverImage', e.target.value)}
                  placeholder="https://example.com/cover.jpg (or click the image below to upload)"
                />
                {form.coverImage ? (
                  <button
                    type="button"
                    onClick={() => coverImgRef.current?.click()}
                    title="Click to replace cover"
                    className="mt-3 w-full text-left block"
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={form.coverImage}
                      alt="Cover preview — click to replace"
                      className="w-full max-h-52 object-cover rounded-xl border border-primary/20"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                    <span className="mt-1.5 text-[11px] text-cyan-300 inline-flex items-center gap-1">
                      <UploadCloud className="w-3.5 h-3.5" />
                      {uploading ? 'Uploading...' : 'Click image to upload a new one'}
                    </span>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => coverImgRef.current?.click()}
                    className="mt-3 w-full min-h-36 rounded-xl border-2 border-dashed border-steel/30 hover:border-cyan-300/50 bg-bg-hover/40 flex flex-col items-center justify-center gap-2 text-text-muted hover:text-cyan-200 transition-colors"
                  >
                    <UploadCloud className="w-6 h-6" />
                    <span className="text-xs font-semibold">
                      {uploading ? 'Uploading...' : 'Click to upload cover image'}
                    </span>
                    <span className="text-[10px]">PNG, JPG, WEBP, GIF or SVG · max 5MB</span>
                  </button>
                )}
                <input
                  ref={coverImgRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
                  className="hidden"
                  onChange={handleCoverFile}
                />
              </div>
              <div className="md:col-span-2">
                <label className={labelCls}>Content (markdown-lite) *</label>
                <div className="flex flex-wrap items-center gap-1.5 mb-2">
                  <ToolbarBtn onClick={() => insertAtLineStart('# ')} title="Heading 1 — biggest">
                    <span className="text-base font-extrabold leading-none">H1</span>
                  </ToolbarBtn>
                  <ToolbarBtn onClick={() => insertAtLineStart('## ')} title="Heading 2 — medium">
                    <span className="text-sm font-bold leading-none">H2</span>
                  </ToolbarBtn>
                  <ToolbarBtn onClick={() => insertAtLineStart('### ')} title="Heading 3 — small">
                    <span className="text-xs font-semibold leading-none">H3</span>
                  </ToolbarBtn>
                  <span className="w-px h-5 bg-steel/20 mx-1" />
                  <ToolbarBtn onClick={() => insertAtCursor('**', '**', 'bold text')} title="Bold">
                    <Bold className="w-3.5 h-3.5" />
                  </ToolbarBtn>
                  <ToolbarBtn
                    onClick={() => insertAtCursor('[', '](https://example.com)', 'link text')}
                    title="External link"
                  >
                    <Link2 className="w-3.5 h-3.5" />
                  </ToolbarBtn>
                  <ToolbarBtn onClick={() => insertAtLineStart('- ')} title="List item">
                    <List className="w-3.5 h-3.5" />
                  </ToolbarBtn>
                  <ToolbarBtn onClick={() => insertAtLineStart('> ')} title="Quote / callout">
                    <Quote className="w-3.5 h-3.5" />
                  </ToolbarBtn>
                  <ToolbarBtn onClick={insertImage} title="Insert image (upload or paste URL)">
                    {uploading ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <ImageIcon className="w-3.5 h-3.5" />
                    )}
                  </ToolbarBtn>
                  <input
                    ref={contentImgRef}
                    type="file"
                    accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
                    className="hidden"
                    onChange={handleContentImageFile}
                  />
                  <span className="w-px h-5 bg-steel/20 mx-1" />
                  <select
                    defaultValue=""
                    onChange={(e) => {
                      const slug = e.target.value;
                      e.target.value = '';
                      if (!slug) return;
                      const post = blogs.find((b) => b.slug === slug);
                      if (post) insertInterlink(post.slug, post.title);
                    }}
                    className="bg-bg-hover border border-steel/20 rounded-lg px-2 py-1.5 text-xs text-offwhite"
                    title="Interlink another blog post"
                  >
                    <option value="">Interlink blog...</option>
                    {blogs.map((b) => (
                      <option key={b.slug} value={b.slug}>
                        {b.title}
                      </option>
                    ))}
                  </select>
                  <span className="flex-1" />
                  <ToolbarBtn
                    onClick={() => setShowPreview((v) => !v)}
                    title={showPreview ? 'Back to editor' : 'Live preview'}
                  >
                    {showPreview ? (
                      <span className="inline-flex items-center gap-1">
                        <PenLine className="w-3.5 h-3.5" /> Edit
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1">
                        <Eye className="w-3.5 h-3.5" /> Preview
                      </span>
                    )}
                  </ToolbarBtn>
                </div>
                <textarea
                  ref={contentRef}
                  className={`${inputCls} min-h-64 font-mono text-xs leading-relaxed resize-y`}
                  value={form.content}
                  onChange={(e) => setField('content', e.target.value)}
                  placeholder={'# Heading 1\n\nParagraph with **bold** text and [internal links](/blogs/slug).\n\n![alt text](https://example.com/image.jpg)\n\n- list item\n\n> callout / quote'}
                  required
                />
                {showPreview && (
                  <div className="mt-3 rounded-xl border border-steel/20 bg-bg-hover/50 p-5 max-h-96 overflow-y-auto">
                    {renderMarkdown(form.content)}
                  </div>
                )}
                <p className="text-[11px] text-text-muted mt-1.5">
                  Supports <code># ## ### #### headings</code> — H1 is the biggest, each extra{' '}
                  <code>#</code> makes it smaller: <code># H1</code>, <code>## H2</code>,{' '}
                  <code>### H3</code>. Also <code>**bold**</code>, <code>[links](/blogs/slug)</code>,{' '}
                  <code>![images](url)</code>, <code>- lists</code>, and <code>&gt; quotes</code>. Use the{' '}
                  <b>Interlink blog...</b> dropdown to link other posts.
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
                  className="glass-card-premium rounded-xl p-4 md:p-5 flex flex-wrap items-center gap-4 transition-colors hover:border-cyan-300/20"
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