'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Plus, Trash2, Pencil, X, LogOut, ExternalLink, CheckCircle2, Bold, Link2, List, Quote, Image as ImageIcon, Eye, PenLine, UploadCloud, Loader2, Clock, Send, Undo2, FileText } from 'lucide-react';
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
      className="px-2.5 py-1.5 rounded-lg bg-bg-hover text-text-secondary hover:text-brand-accent-light hover:bg-steel/20 text-xs font-semibold transition-colors"
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

interface DraftPost extends BlogPost {
  status: 'draft';
  scheduledAt?: string;
  updatedAt: string;
}

type ListTab = 'all' | 'published' | 'drafts' | 'scheduled';

const AUTOSAVE_KEY = 'hyperclients:blog-form:v1';

function toLocalInput(iso?: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function formatScheduled(iso?: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

function isFutureDateTime(value: string): boolean {
  const when = new Date(value);
  return !Number.isNaN(when.getTime()) && when.getTime() > Date.now();
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
  const [drafts, setDrafts] = useState<DraftPost[]>([]);
  const [tab, setTab] = useState<ListTab>('all');
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(emptyForm);
  const [editingSlug, setEditingSlug] = useState<string | null>(null);
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null);
  const [scheduledAtInput, setScheduledAtInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [showPreview, setShowPreview] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [restoreBanner, setRestoreBanner] = useState<{ savedAt: string } | null>(null);
  const restoreRef = useRef<{ form: typeof emptyForm; editingSlug: string | null; editingDraftId: string | null; scheduledAtInput: string } | null>(null);
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
    const [blogsRes, draftsRes] = await Promise.all([
      fetch('/api/admin/blogs'),
      fetch('/api/admin/drafts'),
    ]);
    if (blogsRes.status === 401 || draftsRes.status === 401) {
      router.push('/admin/login');
      return;
    }
    const blogsData = await blogsRes.json().catch(() => ({}));
    const draftsData = await draftsRes.json().catch(() => ({}));
    setBlogs(blogsData.blogs || []);
    setDrafts(draftsData.drafts || []);
    setLoading(false);
  }, [router]);

  useEffect(() => {
    load();
  }, [load]);

  // ---- Form autosave (localStorage) ----
  // Restore prompt on mount if an unsaved form was left behind.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(AUTOSAVE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      const f = saved?.form;
      if (saved && f && (String(f.title || '').trim() || String(f.content || '').trim())) {
        restoreRef.current = {
          form: { ...emptyForm, ...f },
          editingSlug: saved.editingSlug ?? null,
          editingDraftId: saved.editingDraftId ?? null,
          scheduledAtInput: saved.scheduledAtInput ?? '',
        };
        setRestoreBanner({ savedAt: saved.savedAt || '' });
      }
    } catch {
      /* corrupted autosave — ignore */
    }
  }, []);

  // Persist on every change (debounced). Never stores a pristine empty form.
  useEffect(() => {
    const pristine =
      !form.title.trim() && !form.content.trim() && !editingSlug && !editingDraftId;
    if (pristine) return;
    const t = setTimeout(() => {
      try {
        localStorage.setItem(
          AUTOSAVE_KEY,
          JSON.stringify({
            form,
            editingSlug,
            editingDraftId,
            scheduledAtInput,
            savedAt: new Date().toISOString(),
          })
        );
      } catch {
        /* quota/private mode — autosave is best-effort */
      }
    }, 1000);
    return () => clearTimeout(t);
  }, [form, editingSlug, editingDraftId, scheduledAtInput]);

  function clearAutosave() {
    restoreRef.current = null;
    setRestoreBanner(null);
    try {
      localStorage.removeItem(AUTOSAVE_KEY);
    } catch {
      /* ignore */
    }
  }

  function applyRestore() {
    const s = restoreRef.current;
    if (!s) return;
    setForm(s.form);
    setEditingSlug(s.editingSlug);
    setEditingDraftId(s.editingDraftId);
    setScheduledAtInput(s.scheduledAtInput);
    setRestoreBanner(null);
  }

  function discardRestore() {
    clearAutosave();
  }

  function resetFormState() {
    setForm(emptyForm);
    setEditingSlug(null);
    setEditingDraftId(null);
    setScheduledAtInput('');
    setShowPreview(false);
    clearAutosave();
  }

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

  // ---- Save actions ----
  // "Save as Draft": always lands in drafts.json, clears any schedule.
  async function handleSaveDraft() {
    setBusy(true);
    try {
      const payload = { ...parseForm(), scheduledAt: '' };
      const res = await fetch(editingDraftId ? `/api/admin/drafts/${editingDraftId}` : '/api/admin/drafts', {
        method: editingDraftId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        flash(data?.error || 'Draft save failed');
        return;
      }
      flash('Draft saved');
      resetFormState();
      await load();
    } catch {
      flash('Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  // "Publish": new form -> published directly; editing a draft -> move it to
  // published; editing a published post -> update it in place.
  async function handlePublishForm() {
    setBusy(true);
    try {
      if (editingDraftId) {
        const res = await fetch(`/api/admin/drafts/${editingDraftId}/publish`, { method: 'POST' });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          flash(data?.error || 'Publish failed');
          return;
        }
        flash('Blog published');
        resetFormState();
        await load();
        return;
      }
      const payload = parseForm();
      const res = await fetch(editingSlug ? `/api/admin/blogs/${editingSlug}` : '/api/admin/blogs', {
        method: editingSlug ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        flash(data?.error || 'Save failed');
        return;
      }
      flash(editingSlug ? 'Blog updated' : 'Blog published');
      resetFormState();
      await load();
    } catch {
      flash('Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  // "Schedule": saves the current form as a draft with a future publish time.
  async function handleSchedule() {
    if (!scheduledAtInput) {
      flash('Pick a date & time first');
      return;
    }
    const when = new Date(scheduledAtInput);
    if (Number.isNaN(when.getTime())) {
      flash('Invalid date & time');
      return;
    }
    if (!isFutureDateTime(scheduledAtInput)) {
      flash('Schedule time must be in the future');
      return;
    }
    setBusy(true);
    try {
      const payload = { ...parseForm(), scheduledAt: when.toISOString() };
      const res = await fetch(editingDraftId ? `/api/admin/drafts/${editingDraftId}` : '/api/admin/drafts', {
        method: editingDraftId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        flash(data?.error || 'Schedule failed');
        return;
      }
      flash(`Scheduled for ${when.toLocaleString('en-IN')}`);
      resetFormState();
      await load();
    } catch {
      flash('Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  async function handlePublishNow(draftId: string) {
    setBusy(true);
    try {
      const res = await fetch(`/api/admin/drafts/${draftId}/publish`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        flash(data?.error || 'Publish failed');
        return;
      }
      flash('Blog published');
      if (editingDraftId === draftId) resetFormState();
      await load();
    } catch {
      flash('Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  async function handleUnpublish(blog: BlogPost) {
    setBusy(true);
    try {
      const res = await fetch(`/api/admin/blogs/${blog.slug}/unpublish`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        flash(data?.error || 'Unpublish failed');
        return;
      }
      flash('Moved back to drafts');
      // If we were editing this post, keep editing it as a draft.
      if (editingSlug === blog.slug && data.draft) {
        const d = data.draft as DraftPost;
        loadDraftIntoForm(d);
      }
      await load();
    } catch {
      flash('Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteDraft(draft: DraftPost) {
    if (!confirm(`Delete draft "${draft.title || 'Untitled draft'}"?\nThis cannot be undone.`)) return;
    setBusy(true);
    try {
      const res = await fetch(`/api/admin/drafts/${draft.id}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        flash(data?.error || 'Delete failed');
        return;
      }
      flash('Draft deleted');
      if (editingDraftId === draft.id) resetFormState();
      await load();
    } catch {
      flash('Something went wrong');
    } finally {
      setBusy(false);
    }
  }

  function loadDraftIntoForm(draft: DraftPost) {
    setEditingSlug(null);
    setEditingDraftId(draft.id);
    setForm({
      title: draft.title,
      slug: draft.slug,
      excerpt: draft.excerpt,
      date: draft.date,
      content: draft.content,
      coverImage: draft.coverImage || '',
      faqs: (draft.faqs || []).map((f) => `${f.q} | ${f.a}`).join('\n'),
      metaTitle: draft.metaTitle || '',
      metaDescription: draft.metaDescription || '',
      keywords: (draft.keywords || []).join(', '),
      author: draft.author,
      authorBio: draft.authorBio || '',
      category: draft.category,
    });
    setScheduledAtInput(toLocalInput(draft.scheduledAt));
    setShowPreview(false);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function previewDraft(draft: DraftPost) {
    loadDraftIntoForm(draft);
    setShowPreview(true);
  }

  function startEdit(blog: BlogPost) {
    setEditingDraftId(null);
    setScheduledAtInput('');
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
        resetFormState();
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
    'w-full rounded-xl bg-bg-elevated border border-primary/20 px-4 py-2.5 text-sm text-offwhite placeholder:text-text-muted/60 outline-none focus:border-brand-accent/50 focus:ring-2 focus:ring-brand-accent/20 transition-all';
  const labelCls = 'block text-xs font-semibold uppercase tracking-wider text-brand-accent-light/80 mb-1.5';

  return (
    <div className="relative min-h-screen bg-navy text-ice font-sans overflow-hidden">
      <div className="pointer-events-none absolute -top-32 -right-32 w-96 h-96 bg-primary/10 rounded-full blur-[120px]" />
      <div className="pointer-events-none absolute bottom-0 -left-32 w-96 h-96 bg-brand-accent/[0.06] rounded-full blur-[120px]" />
      <div className="relative z-10 container mx-auto px-6 pt-24 pb-16 max-w-5xl">
        <header className="flex items-center justify-between flex-wrap gap-4 mb-8">
          <div>
            <h1 className="text-3xl md:text-4xl font-bold text-offwhite font-heading">
              Blog <span className="gradient-text-premium">Admin</span>
            </h1>
            <p className="text-text-secondary text-sm mt-1">
              Add, edit, and delete blog posts. Changes go live instantly at{' '}
              <Link className="text-brand-accent-light hover:underline" href="/blogs">
                /blogs
              </Link>
              .
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/admin/keys" className="btn-glass rounded-xl px-4 py-2 text-sm inline-flex items-center gap-2">
              API keys
            </Link>
            <button
              onClick={handleLogout}
              className="btn-glass rounded-xl px-4 py-2 text-sm inline-flex items-center gap-2"
            >
              <LogOut className="w-4 h-4" /> Logout
            </button>
          </div>
        </header>

        {notice && (
          <div className="mb-6 flex items-center gap-2 text-sm font-semibold text-emerald bg-emerald/10 border border-emerald/25 rounded-xl px-4 py-3">
            <CheckCircle2 className="w-4 h-4" /> {notice}
          </div>
        )}

        {restoreBanner && (
          <div className="mb-6 flex flex-wrap items-center gap-3 text-sm text-ice/85 bg-amber-400/10 border border-amber-400/25 rounded-xl px-4 py-3">
            <FileText className="w-4 h-4 text-amber-300" />
            <span className="flex-1 min-w-52">
              Unsaved form found
              {restoreBanner.savedAt
                ? ` (last typed ${new Date(restoreBanner.savedAt).toLocaleString('en-IN')})`
                : ''}
              . Restore it?
            </span>
            <button
              type="button"
              onClick={applyRestore}
              className="px-3 py-1.5 rounded-lg bg-amber-400/20 text-amber-200 text-xs font-bold hover:bg-amber-400/30 transition-colors"
            >
              Restore
            </button>
            <button
              type="button"
              onClick={discardRestore}
              className="px-3 py-1.5 rounded-lg bg-white/5 text-ice/70 text-xs font-semibold hover:bg-white/10 transition-colors"
            >
              Discard
            </button>
          </div>
        )}

        <section className="glass-card-premium rounded-2xl p-6 md:p-8 mb-10">
          <h2 className="text-xl font-bold text-offwhite font-heading mb-6 flex items-center gap-2">
            {editingSlug || editingDraftId ? <Pencil className="w-5 h-5 text-brand-accent-light" /> : <Plus className="w-5 h-5 text-brand-accent-light" />}
            {editingSlug ? `Edit: ${editingSlug}` : editingDraftId ? 'Edit draft' : 'New Blog Post'}
          </h2>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              handlePublishForm();
            }}
            className="space-y-5"
          >
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
                    <span className="mt-1.5 text-[11px] text-brand-accent-light inline-flex items-center gap-1">
                      <UploadCloud className="w-3.5 h-3.5" />
                      {uploading ? 'Uploading...' : 'Click image to upload a new one'}
                    </span>
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => coverImgRef.current?.click()}
                    className="mt-3 w-full min-h-36 rounded-xl border-2 border-dashed border-steel/30 hover:border-brand-accent/50 bg-bg-hover/40 flex flex-col items-center justify-center gap-2 text-text-muted hover:text-brand-accent transition-colors"
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

            <div className="flex flex-wrap gap-3 items-end">
              <button
                type="submit"
                disabled={busy}
                className="btn-gradient-cyan rounded-xl px-6 py-3 text-sm disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
              >
                <Send className="w-4 h-4" />
                {busy ? 'Saving...' : editingSlug ? 'Save Changes' : 'Publish Blog'}
              </button>
              {!editingSlug && (
                <button
                  type="button"
                  onClick={handleSaveDraft}
                  disabled={busy}
                  className="btn-glass rounded-xl px-5 py-3 text-sm inline-flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <FileText className="w-4 h-4" /> Save as Draft
                </button>
              )}
              {!editingSlug && (
                <div className="flex items-end gap-2">
                  <div>
                    <label className={labelCls}>Schedule for</label>
                    <input
                      type="datetime-local"
                      className={inputCls}
                      value={scheduledAtInput}
                      onChange={(e) => setScheduledAtInput(e.target.value)}
                    />
                  </div>
                  <button
                    type="button"
                    onClick={handleSchedule}
                    disabled={busy || !scheduledAtInput}
                    className="btn-glass rounded-xl px-5 py-3 text-sm inline-flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Clock className="w-4 h-4" /> Schedule
                  </button>
                </div>
              )}
              {editingSlug && (
                <button
                  type="button"
                  onClick={() => {
                    const b = blogs.find((x) => x.slug === editingSlug);
                    if (b) handleUnpublish(b);
                  }}
                  disabled={busy}
                  className="btn-glass rounded-xl px-5 py-3 text-sm inline-flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Undo2 className="w-4 h-4" /> Unpublish to Draft
                </button>
              )}
              {(editingSlug || editingDraftId) && (
                <button
                  type="button"
                  onClick={resetFormState}
                  className="btn-glass rounded-xl px-5 py-3 text-sm inline-flex items-center gap-2"
                >
                  <X className="w-4 h-4" /> Cancel Edit
                </button>
              )}
            </div>
            {editingDraftId && scheduledAtInput && (
              <p className="text-xs text-amber-300/90 inline-flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5" /> This draft is scheduled — it will publish automatically at the set time.
              </p>
            )}
          </form>
        </section>

        <section>
          {(() => {
            const scheduled = drafts.filter((d) => d.scheduledAt);
            const unscheduled = drafts.filter((d) => !d.scheduledAt);
            const tabs: { key: typeof tab; label: string; count: number }[] = [
              { key: 'all', label: 'All', count: blogs.length + drafts.length },
              { key: 'published', label: 'Published', count: blogs.length },
              { key: 'drafts', label: 'Drafts', count: unscheduled.length },
              { key: 'scheduled', label: 'Scheduled', count: scheduled.length },
            ];
            const showPublished = tab === 'all' || tab === 'published';
            const showDrafts = tab === 'all' || tab === 'drafts';
            const showScheduled = tab === 'all' || tab === 'scheduled';
            return (
              <>
                <div className="flex flex-wrap gap-2 mb-5">
                  {tabs.map((t) => (
                    <button
                      key={t.key}
                      type="button"
                      onClick={() => setTab(t.key)}
                      className={`px-4 py-2 rounded-xl text-sm font-semibold border transition-all ${
                        tab === t.key
                          ? 'bg-brand-accent/15 border-brand-accent/40 text-brand-accent-light'
                          : 'bg-navy/40 border-steel/20 text-ice/60 hover:text-offwhite hover:border-steel/40'
                      }`}
                    >
                      {t.label}
                      <span className="ml-1.5 text-xs opacity-70">({t.count})</span>
                    </button>
                  ))}
                </div>

                {loading ? (
                  <div className="glass-card rounded-2xl p-8 text-center text-text-muted">Loading...</div>
                ) : (
                  <>
                    {showPublished && (
                      <div className="mb-8">
                        <h2 className="text-xl font-bold text-offwhite font-heading mb-4">
                          Published Posts <span className="text-text-muted text-sm font-normal">({blogs.length})</span>
                        </h2>
                        {blogs.length === 0 ? (
                          <div className="glass-card rounded-2xl p-8 text-center text-text-muted">
                            No published posts yet.
                          </div>
                        ) : (
                          <div className="space-y-3">
                            {blogs.map((blog) => (
                              <div
                                key={blog.id}
                                className="glass-card-premium rounded-xl p-4 md:p-5 flex flex-wrap items-center gap-4 transition-colors hover:border-brand-accent/20"
                              >
                                <div className="flex-1 min-w-52">
                                  <h3 className="font-heading font-bold text-offwhite">{blog.title}</h3>
                                  <p className="text-xs text-text-muted mt-1 flex items-center gap-2 flex-wrap">
                                    <span className="px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300 font-semibold">
                                      Published
                                    </span>
                                    <span className="text-brand-accent-light">/{blog.slug}</span>
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
                                    className="p-2.5 rounded-lg bg-bg-hover text-text-secondary hover:text-brand-accent-light transition-colors"
                                  >
                                    <ExternalLink className="w-4 h-4" />
                                  </a>
                                  <button
                                    onClick={() => startEdit(blog)}
                                    title="Edit post"
                                    className="p-2.5 rounded-lg bg-bg-hover text-text-secondary hover:text-brand-accent-light transition-colors"
                                  >
                                    <Pencil className="w-4 h-4" />
                                  </button>
                                  <button
                                    onClick={() => handleUnpublish(blog)}
                                    title="Unpublish — move back to drafts"
                                    disabled={busy}
                                    className="p-2.5 rounded-lg bg-bg-hover text-text-secondary hover:text-amber-300 transition-colors disabled:opacity-50"
                                  >
                                    <Undo2 className="w-4 h-4" />
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
                      </div>
                    )}

                    {(showDrafts || showScheduled) && (
                      <div>
                        <h2 className="text-xl font-bold text-offwhite font-heading mb-4">
                          {tab === 'scheduled' ? 'Scheduled' : tab === 'drafts' ? 'Drafts' : 'Drafts & Scheduled'}{' '}
                          <span className="text-text-muted text-sm font-normal">
                            ({tab === 'scheduled' ? scheduled.length : tab === 'drafts' ? unscheduled.length : drafts.length})
                          </span>
                        </h2>
                        {(() => {
                          const list = tab === 'scheduled' ? scheduled : tab === 'drafts' ? unscheduled : drafts;
                          if (list.length === 0) {
                            return (
                              <div className="glass-card rounded-2xl p-8 text-center text-text-muted">
                                No drafts here. Write above and hit “Save as Draft”.
                              </div>
                            );
                          }
                          return (
                            <div className="space-y-3">
                              {list.map((d) => (
                                <div
                                  key={d.id}
                                  className="glass-card-premium rounded-xl p-4 md:p-5 flex flex-wrap items-center gap-4 transition-colors hover:border-brand-accent/20"
                                >
                                  <div className="flex-1 min-w-52">
                                    <h3 className="font-heading font-bold text-offwhite">
                                      {d.title.trim() || <span className="italic text-text-muted">Untitled draft</span>}
                                    </h3>
                                    <p className="text-xs text-text-muted mt-1 flex items-center gap-2 flex-wrap">
                                      {d.scheduledAt ? (
                                        <span className="px-1.5 py-0.5 rounded bg-amber-400/15 text-amber-300 font-semibold inline-flex items-center gap-1">
                                          <Clock className="w-3 h-3" /> Scheduled · {formatScheduled(d.scheduledAt)}
                                        </span>
                                      ) : (
                                        <span className="px-1.5 py-0.5 rounded bg-white/5 text-ice/60 font-semibold border border-white/10">
                                          Draft
                                        </span>
                                      )}
                                      {d.slug ? (
                                        <span className="text-brand-accent-light">/{d.slug}</span>
                                      ) : (
                                        <span className="italic">(no slug yet)</span>
                                      )}
                                      <span>{d.category}</span>
                                    </p>
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <button
                                      onClick={() => previewDraft(d)}
                                      title="Preview draft"
                                      className="p-2.5 rounded-lg bg-bg-hover text-text-secondary hover:text-brand-accent-light transition-colors"
                                    >
                                      <Eye className="w-4 h-4" />
                                    </button>
                                    <button
                                      onClick={() => {
                                        loadDraftIntoForm(d);
                                      }}
                                      title="Edit draft"
                                      className="p-2.5 rounded-lg bg-bg-hover text-text-secondary hover:text-brand-accent-light transition-colors"
                                    >
                                      <Pencil className="w-4 h-4" />
                                    </button>
                                    <button
                                      onClick={() => handlePublishNow(d.id)}
                                      title="Publish now"
                                      disabled={busy}
                                      className="p-2.5 rounded-lg bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition-colors disabled:opacity-50"
                                    >
                                      <Send className="w-4 h-4" />
                                    </button>
                                    <button
                                      onClick={() => handleDeleteDraft(d)}
                                      title="Delete draft"
                                      disabled={busy}
                                      className="p-2.5 rounded-lg bg-bg-hover text-rose hover:bg-rose/20 transition-colors disabled:opacity-50"
                                    >
                                      <Trash2 className="w-4 h-4" />
                                    </button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          );
                        })()}
                      </div>
                    )}
                  </>
                )}
              </>
            );
          })()}
        </section>
      </div>
    </div>
  );
}