import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

export interface BlogFaq {
  q: string;
  a: string;
}

export interface BlogPost {
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
  createdAt: string;
}

const SEED_FILE = path.join(process.cwd(), 'data', 'blogs.json');

/**
 * Where posts are READ and WRITTEN. In production BLOGS_DATA_DIR points at a
 * Docker volume outside the git checkout: the repo file (SEED_FILE) is only
 * the initial content. Writing into the git-tracked data/ folder meant every
 * deploy that reset or re-cloned the checkout silently wiped all posts
 * published from the admin panel.
 */
function dataFile(): string {
  const dir = process.env.BLOGS_DATA_DIR;
  if (!dir) return SEED_FILE;
  const file = path.join(dir, 'blogs.json');
  // First run on an empty volume: start from the seed (which, on the server,
  // is the bind-mounted copy holding the posts published so far).
  if (!fs.existsSync(file) && fs.existsSync(SEED_FILE)) {
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.copyFileSync(SEED_FILE, file);
    } catch (err) {
      console.error('[blog-store] seeding persistent store failed', err);
    }
  }
  return file;
}

// NOTE: deliberately NO in-memory cache here. Next.js bundles lib/ separately
// per route, so a module-level cache would diverge between the admin API
// routes (writers) and the public pages (readers) — a newly published post
// would 404 until server restart. Blogs are tiny; always read from disk.

function readAll(): BlogPost[] {
  // Always read from disk: see NOTE above (no in-memory cache).
  try {
    const file = dataFile();
    if (fs.existsSync(file)) {
      const raw = fs.readFileSync(file, 'utf-8').replace(/^\uFEFF/, '');
      const posts: BlogPost[] = JSON.parse(raw);
      return posts;
    }
  } catch (err) {
    console.error('[blog-store] read failed', err);
  }
  return [];
}

function writeAll(posts: BlogPost[]): void {
  const file = dataFile();
  const dir = path.dirname(file);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(posts, null, 2), 'utf-8');
  fs.renameSync(tmp, file);
}

export function getBlogs(): BlogPost[] {
  return readAll().slice().sort((a, b) => (a.date < b.date ? 1 : -1));
}

export function getBlog(slug: string): BlogPost | undefined {
  return readAll().find((p) => p.slug === slug);
}

export function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
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

function normalizeFaqs(input: unknown): { q: string; a: string }[] {
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

export function createBlog(input: Partial<BlogPost>): { post?: BlogPost; error?: string } {
  if (!input.title || !input.title.trim()) return { error: 'Title is required' };
  if (!input.content || !input.content.trim()) return { error: 'Content is required' };
  const posts = readAll();
  const slug = slugify(input.slug || (input.title as string));
  const existing = posts.some((p) => p.slug === slug);
  if (existing) return { error: `Slug "${slug}" already exists` };
  const post: BlogPost = {
    id: crypto.randomUUID(),
    slug,
    title: input.title.trim(),
    excerpt: (input.excerpt || cleanExcerpt(input.content)).trim(),
    category: input.category || 'General',
    date: input.date || new Date().toISOString().slice(0, 10),
    content: input.content,
    coverImage: input.coverImage?.trim() || undefined,
    faqs: normalizeFaqs(input.faqs),
    metaTitle: input.metaTitle,
    metaDescription: input.metaDescription,
    keywords: normalizeKeywords(input.keywords),
    author: input.author || 'Hyperclients Team',
    authorBio: input.authorBio || '',
    createdAt: new Date().toISOString(),
  };
  posts.push(post);
  writeAll(posts);
  return { post };
}

export function updateBlog(slug: string, input: Partial<BlogPost>): { post?: BlogPost; error?: string } {
  const posts = readAll();
  const idx = posts.findIndex((p) => p.slug === slug);
  if (idx === -1) return { error: 'Post not found' };
  const updated: BlogPost = {
    ...posts[idx],
    ...input,
    slug,
    id: posts[idx].id,
    createdAt: posts[idx].createdAt,
    excerpt: (input.excerpt || posts[idx].excerpt).trim(),
    faqs: normalizeFaqs(input.faqs ?? posts[idx].faqs),
    keywords: normalizeKeywords(input.keywords ?? posts[idx].keywords),
  };
  posts[idx] = updated;
  writeAll(posts);
  return { post: updated };
}

export function deleteBlog(slug: string): { ok: boolean; error?: string } {
  const posts = readAll();
  const next = posts.filter((p) => p.slug !== slug);
  if (next.length === posts.length) return { ok: false, error: 'Post not found' };
  writeAll(next);
  return { ok: true };
}