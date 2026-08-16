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

function dataFile(): string {
  if (process.env.BLOGS_DATA_DIR) {
    return path.join(process.env.BLOGS_DATA_DIR, 'blogs.json');
  }
  return SEED_FILE;
}

let cached: BlogPost[] | null = null;

function readAll(): BlogPost[] {
  if (cached) return cached;
  try {
    const file = dataFile();
    if (fs.existsSync(file)) {
      const raw = fs.readFileSync(file, 'utf-8').replace(/^\uFEFF/, '');
      const posts: BlogPost[] = JSON.parse(raw);
      cached = posts;
      return posts;
    }
  } catch (err) {
    console.error('[blog-store] read failed', err);
  }
  return [];
}

function writeAll(posts: BlogPost[]): void {
  cached = posts;
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

export function createBlog(input: Partial<BlogPost>): { post?: BlogPost; error?: string } {
  if (!input.title || !input.title.trim()) return { error: 'Title is required' };
  if (!input.content || !input.content.trim()) return { error: 'Content is required' };
  const posts = readAll();
  let slug = slugify(input.slug || (input.title as string));
  const existing = posts.some((p) => p.slug === slug);
  if (existing) return { error: `Slug "${slug}" already exists` };
  const post: BlogPost = {
    id: crypto.randomUUID(),
    slug,
    title: input.title.trim(),
    excerpt: (input.excerpt || input.content.trim().slice(0, 160)).trim(),
    category: input.category || 'General',
    date: input.date || new Date().toISOString().slice(0, 10),
    content: input.content,
    coverImage: input.coverImage?.trim() || undefined,
    faqs: input.faqs || [],
    metaTitle: input.metaTitle,
    metaDescription: input.metaDescription,
    keywords: input.keywords || [],
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