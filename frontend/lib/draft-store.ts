import fs from 'fs';
import path from 'path';
import crypto from 'crypto';
import { createBlog, deleteBlog, getBlog, slugify } from './blog-store';

export interface DraftFaq {
  q: string;
  a: string;
}

export interface DraftPost {
  id: string;
  slug: string;
  title: string;
  excerpt: string;
  category: string;
  date: string;
  content: string;
  coverImage?: string;
  faqs?: DraftFaq[];
  metaTitle?: string;
  metaDescription?: string;
  keywords?: string[];
  author: string;
  authorBio: string;
  status: 'draft';
  /** ISO datetime at/after which the draft auto-publishes. Absent = manual only. */
  scheduledAt?: string;
  /** Last publish failure (scheduled retries back off instead of hammering). */
  lastPublishError?: string;
  lastPublishAttemptAt?: string;
  createdAt: string;
  updatedAt: string;
}

/** How long a failed scheduled publish waits before it is retried. */
const PUBLISH_RETRY_BACKOFF_MS = 10 * 60 * 1000;

const SEED_FILE = path.join(process.cwd(), 'data', 'drafts.json');

function dataFile(): string {
  if (process.env.BLOGS_DATA_DIR) {
    return path.join(process.env.BLOGS_DATA_DIR, 'drafts.json');
  }
  return SEED_FILE;
}

// NOTE: deliberately NO in-memory cache here — see blog-store.ts. Next.js
// bundles lib/ separately per route, so a module-level cache would diverge
// between route bundles. Drafts are tiny; always read from disk.

function readAll(): DraftPost[] {
  // Always read from disk: see NOTE above (no in-memory cache).
  try {
    const file = dataFile();
    if (fs.existsSync(file)) {
      const raw = fs.readFileSync(file, 'utf-8').replace(/^\uFEFF/, '');
      const parsed: unknown = JSON.parse(raw);
      return Array.isArray(parsed) ? (parsed as DraftPost[]) : [];
    }
  } catch (err) {
    console.error('[draft-store] read failed', err);
  }
  return [];
}

function writeAll(drafts: DraftPost[]): void {
  const file = dataFile();
  const dir = path.dirname(file);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(drafts, null, 2), 'utf-8');
  fs.renameSync(tmp, file);
}

function normalizeKeywords(input: unknown): string[] {
  if (Array.isArray(input)) {
    return input.map((k) => String(k).trim()).filter(Boolean);
  }
  if (typeof input === 'string') {
    return input
      .split(',')
      .map((k) => k.trim())
      .filter(Boolean);
  }
  return [];
}

function normalizeFaqs(input: unknown): DraftFaq[] {
  if (Array.isArray(input)) {
    return input
      .filter((f) => f && typeof f === 'object' && (f as { q?: string }).q)
      .map((f) => ({
        q: String((f as { q: string }).q).trim(),
        a: String((f as { a?: string }).a || '').trim(),
      }))
      .filter((f) => f.q && f.a);
  }
  if (typeof input === 'string') {
    return input
      .split('\n')
      .map((line) => {
        const sep = line.indexOf('|');
        return sep > -1
          ? { q: line.slice(0, sep).trim(), a: line.slice(sep + 1).trim() }
          : { q: line.trim(), a: '' };
      })
      .filter((f) => f.q && f.a);
  }
  return [];
}

function cleanExcerpt(text: string): string {
  const clean = text
    .replace(/^[#>\-*\s]+/gm, '')
    .replace(/#/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  return clean.length > 160 ? `${clean.slice(0, 160).trimEnd()}...` : clean;
}

function parseScheduledAt(input: unknown): string | undefined {
  if (typeof input !== 'string' || !input.trim()) return undefined;
  const d = new Date(input.trim());
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString();
}

export function getDrafts(): DraftPost[] {
  return readAll()
    .slice()
    .sort((a, b) => ((a.updatedAt || '') < (b.updatedAt || '') ? 1 : -1));
}

export function getDraft(id: string): DraftPost | undefined {
  return readAll().find((d) => d.id === id);
}

export interface DraftInput {
  id?: string;
  title?: string;
  slug?: string;
  excerpt?: string;
  category?: string;
  date?: string;
  content?: string;
  coverImage?: string;
  faqs?: unknown;
  metaTitle?: string;
  metaDescription?: string;
  keywords?: unknown;
  author?: string;
  authorBio?: string;
  scheduledAt?: string;
}

function buildDraftFields(input: DraftInput) {
  return {
    title: (input.title || '').trim(),
    slug: (input.slug || '').trim(),
    excerpt: (input.excerpt || '').trim(),
    category: (input.category || '').trim() || 'General',
    date: input.date || new Date().toISOString().slice(0, 10),
    content: input.content || '',
    coverImage: (input.coverImage || '').trim() || undefined,
    faqs: normalizeFaqs(input.faqs),
    metaTitle: (input.metaTitle || '').trim(),
    metaDescription: (input.metaDescription || '').trim(),
    keywords: normalizeKeywords(input.keywords),
    author: (input.author || '').trim() || 'Hyperclients Team',
    authorBio: (input.authorBio || '').trim(),
    scheduledAt: parseScheduledAt(input.scheduledAt),
  };
}

export function saveDraft(input: DraftInput): { draft?: DraftPost; error?: string } {
  const drafts = readAll();
  const now = new Date().toISOString();
  if (input.id) {
    const idx = drafts.findIndex((d) => d.id === input.id);
    if (idx === -1) return { error: 'Draft not found' };
    const prev = drafts[idx];
    const slug = input.slug !== undefined ? input.slug.trim() : prev.slug;
    if (slug && drafts.some((d) => d.id !== input.id && d.slug === slug)) {
      return { error: `Another draft already uses slug "${slug}"` };
    }
    // Partial update: only keys present in `input` overwrite the saved draft.
    // (A missing key must never wipe a stored value — e.g. updating just the
    // schedule must keep the slug.)
    const f = buildDraftFields(input);
    const has = (k: keyof DraftInput): boolean => input[k] !== undefined;
    const updated: DraftPost = {
      ...prev,
      title: has('title') ? f.title : prev.title,
      slug,
      excerpt: has('excerpt') ? f.excerpt : prev.excerpt,
      category: has('category') ? f.category || prev.category : prev.category,
      date: has('date') && input.date ? input.date : prev.date,
      content: has('content') ? f.content : prev.content,
      coverImage: has('coverImage') ? f.coverImage : prev.coverImage,
      faqs: has('faqs') ? f.faqs : prev.faqs,
      metaTitle: has('metaTitle') ? f.metaTitle : prev.metaTitle,
      metaDescription: has('metaDescription') ? f.metaDescription : prev.metaDescription,
      keywords: has('keywords') ? f.keywords : prev.keywords,
      author: has('author') ? f.author || prev.author : prev.author,
      authorBio: has('authorBio') ? f.authorBio : prev.authorBio,
      scheduledAt: has('scheduledAt') ? f.scheduledAt : prev.scheduledAt,
      id: prev.id,
      status: 'draft',
      createdAt: prev.createdAt,
      updatedAt: now,
    };
    // Auto-excerpt only when the draft has neither an explicit excerpt nor one
    // saved before (never clobber an intentional excerpt).
    if (!updated.excerpt && updated.content.trim()) {
      updated.excerpt = cleanExcerpt(updated.content);
    }
    drafts[idx] = updated;
    writeAll(drafts);
    return { draft: updated };
  }
  const slug = (input.slug || '').trim();
  if (slug && drafts.some((d) => d.slug === slug)) {
    return { error: `Another draft already uses slug "${slug}"` };
  }
  const fields = buildDraftFields(input);
  const draft: DraftPost = {
    id: crypto.randomUUID(),
    ...fields,
    slug,
    status: 'draft',
    excerpt: fields.excerpt || (fields.content.trim() ? cleanExcerpt(fields.content) : ''),
    createdAt: now,
    updatedAt: now,
  };
  drafts.push(draft);
  writeAll(drafts);
  return { draft };
}

export function deleteDraft(id: string): { ok: boolean; error?: string } {
  const drafts = readAll();
  const next = drafts.filter((d) => d.id !== id);
  if (next.length === drafts.length) return { ok: false, error: 'Draft not found' };
  writeAll(next);
  return { ok: true };
}

function uniqueSlug(base: string): string {
  const clean = slugify(base || 'untitled');
  let candidate = clean || 'untitled';
  let n = 2;
  while (getBlog(candidate)) {
    candidate = `${clean || 'untitled'}-${n}`;
    n += 1;
    if (n > 1000) break;
  }
  return candidate;
}

/** Record a failed publish so scheduled retries can back off. Best-effort. */
function notePublishFailure(id: string, error: string): void {
  try {
    const drafts = readAll();
    const idx = drafts.findIndex((d) => d.id === id);
    if (idx === -1) return;
    drafts[idx] = {
      ...drafts[idx],
      lastPublishError: error,
      lastPublishAttemptAt: new Date().toISOString(),
    };
    writeAll(drafts);
  } catch (err) {
    console.error('[draft-store] could not record publish failure', err);
  }
}

/**
 * Move a draft into the published store. The draft row is removed.
 *
 * Publishing touches TWO files (blogs.json, drafts.json), so a failure between
 * the writes used to leave the post published AND the draft intact — the next
 * cron tick then published it again under a different slug. The post is now
 * rolled back when the draft write fails, so the operation is all-or-nothing.
 */
export function publishDraft(id: string): { post?: unknown; error?: string } {
  const drafts = readAll();
  const idx = drafts.findIndex((d) => d.id === id);
  if (idx === -1) return { error: 'Draft not found' };
  const draft = drafts[idx];
  if (!draft.title.trim()) {
    notePublishFailure(id, 'Title is required to publish');
    return { error: 'Title is required to publish' };
  }
  if (!draft.content.trim()) {
    notePublishFailure(id, 'Content is required to publish');
    return { error: 'Content is required to publish' };
  }
  const slug = draft.slug || uniqueSlug(draft.title);
  const finalSlug = getBlog(slug) ? uniqueSlug(`${slug}-post`) : slug;
  let result: { post?: { slug?: string }; error?: string };
  try {
    result = createBlog({
      title: draft.title,
      slug: finalSlug,
      excerpt: draft.excerpt,
      category: draft.category,
      date: draft.date,
      content: draft.content,
      coverImage: draft.coverImage,
      faqs: draft.faqs,
      metaTitle: draft.metaTitle,
      metaDescription: draft.metaDescription,
      keywords: draft.keywords,
      author: draft.author,
      authorBio: draft.authorBio,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Publish failed';
    notePublishFailure(id, message);
    return { error: message };
  }
  if (result.error || !result.post) {
    const message = result.error || 'Publish failed';
    notePublishFailure(id, message);
    return { error: message };
  }

  const nextDrafts = drafts.filter((d) => d.id !== id);
  try {
    writeAll(nextDrafts);
  } catch (err) {
    // Roll the published post back so the draft is never half-published.
    console.error('[draft-store] draft write failed after publish; rolling back', err);
    try {
      deleteBlog(finalSlug);
    } catch (rollbackErr) {
      console.error('[draft-store] publish rollback failed', rollbackErr);
    }
    const message = 'Publish failed (storage write failed)';
    notePublishFailure(id, message);
    return { error: message };
  }
  return { post: result.post };
}

/** Move a published post back to drafts (unpublish). The published row is removed. */
export function unpublishPost(slug: string): { draft?: DraftPost; error?: string } {
  const post = getBlog(slug);
  if (!post) return { error: 'Post not found' };
  const now = new Date().toISOString();
  const drafts = readAll();
  const draft: DraftPost = {
    id: crypto.randomUUID(),
    slug: post.slug,
    title: post.title,
    excerpt: post.excerpt,
    category: post.category,
    date: post.date,
    content: post.content,
    coverImage: post.coverImage,
    faqs: (post.faqs || []).map((f) => ({ q: f.q, a: f.a })),
    metaTitle: post.metaTitle || '',
    metaDescription: post.metaDescription || '',
    keywords: post.keywords ? [...post.keywords] : [],
    author: post.author,
    authorBio: post.authorBio || '',
    status: 'draft',
    scheduledAt: undefined,
    createdAt: post.createdAt,
    updatedAt: now,
  };
  // Write the draft copy FIRST so a failed write never destroys the
  // published post. Only after the draft is durable do we remove the
  // published row. If the delete fails we compensate by removing the
  // just-created draft, keeping the operation all-or-nothing.
  drafts.push(draft);
  try {
    writeAll(drafts);
  } catch (err) {
    console.error('[draft-store] unpublish save failed', err);
    return { error: 'Unpublish failed (storage write failed)' };
  }
  try {
    const removed = deleteBlog(slug);
    if (!removed.ok) {
      deleteDraft(draft.id); // compensate: keep the published post as-is
      return { error: removed.error || 'Unpublish failed' };
    }
  } catch (err) {
    console.error('[draft-store] unpublish delete failed', err);
    deleteDraft(draft.id);
    return { error: 'Unpublish failed (storage write failed)' };
  }
  return { draft };
}

/** Publish every draft whose scheduledAt has passed. Returns what moved. */
export function publishDueDrafts(nowMs: number = Date.now()): { published: string[]; failed: { id: string; error: string }[] } {
  const published: string[] = [];
  const failed: { id: string; error: string }[] = [];
  const due = readAll().filter((d) => d.scheduledAt && !Number.isNaN(Date.parse(d.scheduledAt)) && Date.parse(d.scheduledAt) <= nowMs);
  for (const d of due) {
    // A draft that keeps failing (e.g. empty content) is retried on EVERY admin
    // API hit; back off so it cannot spin on each request.
    const lastAttempt = d.lastPublishAttemptAt ? Date.parse(d.lastPublishAttemptAt) : NaN;
    if (
      d.lastPublishError &&
      !Number.isNaN(lastAttempt) &&
      nowMs - lastAttempt < PUBLISH_RETRY_BACKOFF_MS
    ) {
      failed.push({ id: d.id, error: d.lastPublishError });
      continue;
    }
    const res = publishDraft(d.id);
    if (res.post) {
      published.push(d.id);
    } else {
      failed.push({ id: d.id, error: res.error || 'Publish failed' });
    }
  }
  return { published, failed };
}
