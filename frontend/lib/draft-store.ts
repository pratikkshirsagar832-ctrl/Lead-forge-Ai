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
  createdAt: string;
  updatedAt: string;
}

const SEED_FILE = path.join(process.cwd(), 'data', 'drafts.json');

function dataFile(): string {
  if (process.env.BLOGS_DATA_DIR) {
    return path.join(process.env.BLOGS_DATA_DIR, 'drafts.json');
  }
  return SEED_FILE;
}

let cached: DraftPost[] | null = null;

function readAll(): DraftPost[] {
  if (cached) return cached;
  try {
    const file = dataFile();
    if (fs.existsSync(file)) {
      const raw = fs.readFileSync(file, 'utf-8').replace(/^\uFEFF/, '');
      const parsed: unknown = JSON.parse(raw);
      cached = Array.isArray(parsed) ? (parsed as DraftPost[]) : [];
      return cached;
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
  // Same discipline as blog-store: only commit the in-memory cache after the
  // disk write succeeded, so a failed save never poisons memory.
  fs.writeFileSync(tmp, JSON.stringify(drafts, null, 2), 'utf-8');
  fs.renameSync(tmp, file);
  cached = drafts;
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
    const slug = (input.slug || '').trim();
    if (slug && drafts.some((d) => d.id !== input.id && d.slug === slug)) {
      return { error: `Another draft already uses slug "${slug}"` };
    }
    const updated: DraftPost = {
      ...drafts[idx],
      ...buildDraftFields(input),
      id: drafts[idx].id,
      slug,
      status: 'draft',
      createdAt: drafts[idx].createdAt,
      updatedAt: now,
    };
    // Auto-excerpt only when the admin left it blank AND the saved draft has
    // no excerpt of its own yet (never clobber an intentional excerpt).
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

/** Move a draft into the published store. The draft row is removed. */
export function publishDraft(id: string): { post?: unknown; error?: string } {
  const drafts = readAll();
  const idx = drafts.findIndex((d) => d.id === id);
  if (idx === -1) return { error: 'Draft not found' };
  const draft = drafts[idx];
  if (!draft.title.trim()) return { error: 'Title is required to publish' };
  if (!draft.content.trim()) return { error: 'Content is required to publish' };
  const slug = draft.slug || uniqueSlug(draft.title);
  const finalSlug = getBlog(slug) ? uniqueSlug(`${slug}-post`) : slug;
  const result = createBlog({
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
  if (result.error || !result.post) {
    return { error: result.error || 'Publish failed' };
  }
  drafts.splice(idx, 1);
  writeAll(drafts);
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
  try {
    const removed = deleteBlog(slug);
    if (!removed.ok) return { error: removed.error || 'Unpublish failed' };
  } catch (err) {
    console.error('[draft-store] unpublish delete failed', err);
    return { error: 'Unpublish failed (storage write failed)' };
  }
  drafts.push(draft);
  try {
    writeAll(drafts);
  } catch (err) {
    console.error('[draft-store] unpublish save failed', err);
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
    const res = publishDraft(d.id);
    if (res.post) {
      published.push(d.id);
    } else {
      failed.push({ id: d.id, error: res.error || 'Publish failed' });
    }
  }
  return { published, failed };
}
