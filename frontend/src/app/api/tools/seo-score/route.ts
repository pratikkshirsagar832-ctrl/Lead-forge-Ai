import { NextRequest, NextResponse } from 'next/server';
import dns from 'node:dns/promises';

export const runtime = 'nodejs';
export const maxDuration = 60;

interface SeoCheck {
  id: string;
  label: string;
  passed: boolean;
  points: number;
  max: number;
  detail: string;
}

interface SeoResult {
  score: number;
  grade: string;
  url: string;
  title: string;
  metaDescription: string;
  wordCount: number;
  checks: SeoCheck[];
  error?: string;
}

const GRADE = (s: number) => (s >= 90 ? 'A' : s >= 80 ? 'B' : s >= 70 ? 'C' : s >= 60 ? 'D' : 'F');

function isPrivateIp(ip: string): boolean {
  if (ip.startsWith('::ffff:')) ip = ip.slice(7);
  if (ip === '::1' || ip === '0.0.0.0') return true;
  if (ip.includes(':')) {
    const lower = ip.toLowerCase();
    // IPv6 loopback / link-local / unique-local / unspecified
    return (
      lower === '::' ||
      lower.startsWith('fc') ||
      lower.startsWith('fd') ||
      lower.startsWith('fe8') ||
      lower.startsWith('fe9') ||
      lower.startsWith('fea') ||
      lower.startsWith('feb') ||
      lower === '::1'
    );
  }
  const parts = ip.split('.').map(Number);
  if (parts.length !== 4) return true;
  const [a, b] = parts;
  return (
    a === 10 ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    a === 127 ||
    a === 169 || // 169.254 link-local
    a === 0 ||
    (a === 100 && b >= 64 && b <= 127) // CGNAT
  );
}

/** Resolve ALL A/AAAA records and reject when ANY resolves to a private/
 * loopback/link-local address. Checking one record is not enough: dual-stack
 * hosts can pin a public address first then answer internal via the other. */
async function assertPublicHost(hostname: string): Promise<void> {
  let addresses: string[] = [];
  try {
    const lookup = await dns.lookup(hostname, { all: true, verbatim: true });
    addresses = (Array.isArray(lookup) ? lookup : [lookup]).map((x) => x.address);
  } catch {
    // Fall back to the resolver's single result so behavior stays consistent.
    const { address } = await dns.lookup(hostname, { verbatim: true });
    addresses = [address];
  }
  if (addresses.length === 0) {
    throw new Error(`Blocked: could not resolve ${hostname}`);
  }
  for (const address of addresses) {
    if (isPrivateIp(address)) {
      throw new Error(`Blocked: ${hostname} resolves to a private address (${address})`);
    }
  }
}

/** Validate a URL string is public http(s) and its hostname is not private.
 * Throws on anything else. */
async function assertPublicUrl(rawUrl: string): Promise<URL> {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new Error('Invalid URL format');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new Error('Only http/https URLs are supported');
  }
  const hostname = url.hostname.toLowerCase();
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '0.0.0.0' || hostname === '::1') {
    throw new Error(`Blocked: ${hostname} is not a public host`);
  }
  await assertPublicHost(hostname);
  return url;
}

function decodeEntities(s: string): string {
  return s
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;/g, "'")
    .replace(/&nbsp;/g, ' ');
}

function extractMeta(html: string, name: string): string | null {
  const re = new RegExp(
    `<meta[^>]+(?:name|property)=["']${name}["'][^>]+content=["']([^"']*)["']`,
    'i'
  );
  const re2 = new RegExp(
    `<meta[^>]+content=["']([^"']*)["'][^>]+(?:name|property)=["']${name}["']`,
    'i'
  );
  const m = html.match(re) || html.match(re2);
  return m ? decodeEntities(m[1]).trim().slice(0, 500) : null;
}

function countOccurrences(html: string, tag: string): number {
  const re = new RegExp(`<${tag}[\\s>]`, 'gi');
  return (html.match(re) || []).length;
}

/**
 * Fetch with SSRF-safe redirect handling. Every hop (including the initial
 * URL and each redirect target) is re-validated against private-IP ranges, so
 * a redirect to 127.0.0.1, cloud metadata, or an internal host is refused.
 * fetch()'s `redirect: 'follow'` trusts the server's Location header, which is
 * exactly the attack: attacker URL 302 -> http://169.254.169.254/...
 */
async function fetchText(url: string, timeoutMs: number, maxRedirects = 4): Promise<{ text: string; finalUrl: string }> {
  let current = await assertPublicUrl(url); // validates scheme + host + DNS
  let text = '';
  for (let hop = 0; hop <= maxRedirects; hop++) {
    const res = await fetch(current.toString(), {
      redirect: 'manual',
      signal: AbortSignal.timeout(timeoutMs),
      headers: { 'User-Agent': 'Mozilla/5.0 (compatible; HyperclientsSeoBot/1.0)' },
    });
    if (res.status >= 300 && res.status < 400) {
      const location = res.headers.get('location');
      if (!location) {
        // No Location header: treat as final (some servers do this).
        text = await res.text();
        return { text: text.slice(0, 600000), finalUrl: res.url || current.toString() };
      }
      // Validate the redirect target BEFORE following it.
      const next = new URL(location, current);
      current = await assertPublicUrl(next.toString());
      continue;
    }
    text = await res.text();
    return { text: text.slice(0, 600000), finalUrl: res.url || current.toString() };
  }
  throw new Error('Too many redirects');
}

// Simple in-memory rate limit (per-process): this route is public and runs
// arbitrary fetches, so it must not become a free port-scanner / DoS vector.
const RATE_WINDOW_MS = 60_000;
const RATE_MAX_PER_WINDOW = 20;
const hitTimes: number[] = [];
function rateLimited(): boolean {
  const now = Date.now();
  while (hitTimes.length && hitTimes[0] < now - RATE_WINDOW_MS) hitTimes.shift();
  if (hitTimes.length >= RATE_MAX_PER_WINDOW) return true;
  hitTimes.push(now);
  return false;
}

export async function POST(req: NextRequest) {
  if (rateLimited()) {
    return NextResponse.json({ error: 'Too many requests. Try again shortly.' }, { status: 429 });
  }
  const body = await req.json().catch(() => null);
  let rawUrl = (body?.url as string | undefined)?.trim();
  if (!rawUrl) {
    return NextResponse.json({ error: 'URL is required' }, { status: 400 });
  }
  if (!/^https?:\/\//i.test(rawUrl)) rawUrl = `https://${rawUrl}`;

  try {
    const validated = await assertPublicUrl(rawUrl);

    const { text: html, finalUrl } = await fetchText(validated.toString(), 15000);
    const final = new URL(finalUrl);
    const origin = `${final.protocol}//${final.host}`;
    const lower = html.toLowerCase();

    const rawTitle = extractMeta(html, 'og:title') || (html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1] || '').trim();
    const title = decodeEntities(rawTitle).replace(/\s+/g, ' ').trim().slice(0, 300);
    const metaDescription = extractMeta(html, 'description') || '';

    const h1Count = countOccurrences(html, 'h1');
    const h2Count = countOccurrences(html, 'h2');
    const h3Count = countOccurrences(html, 'h3');

    const imgTags = html.match(/<img[\s>]/gi) || [];
    const altCount = imgTags.filter((tag) => /alt=["']([^"']+)["']/i.test(tag) && !/alt=["']\s*["']/.test(tag)).length;

    const hasViewport = /<meta[^>]+name=["']viewport["']/i.test(html);
    const canonical = html.match(/<link[^>]+rel=["']canonical["'][^>]*>/i);
    const ogTitle = extractMeta(html, 'og:title');
    const ogDescription = extractMeta(html, 'og:description');
    const ogImage = extractMeta(html, 'og:image');
    const hasHreflang = /rel=["']alternate["'][^>]+hreflang=/i.test(html);

    const strippedText = html
      .replace(/<script[\s\S]*?<\/script>/gi, ' ')
      .replace(/<style[\s\S]*?<\/style>/gi, ' ')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&[a-z#0-9]+;/gi, ' ')
      .replace(/\s+/g, ' ')
      .trim();
    const wordCount = strippedText ? strippedText.split(' ').length : 0;

    const [robotsRes, sitemapRes] = await Promise.allSettled([
      fetchText(`${origin}/robots.txt`, 8000),
      fetchText(`${origin}/sitemap.xml`, 8000),
    ]);

    let robotsText = '';
    if (robotsRes.status === 'fulfilled') robotsText = robotsRes.value.text.slice(0, 20000);
    const robotsBlocked = /^disallow:\s*\/\s*$/im.test(robotsText);
    const robotsHasSitemap = /^sitemap:/im.test(robotsText);

    let sitemapOk = false;
    if (sitemapRes.status === 'fulfilled') {
      const sitemapText = sitemapRes.value.text;
      sitemapOk = /<urlset[\s>]/i.test(sitemapText) || /<url>[\s\S]*?<loc>/i.test(sitemapText) || sitemapText.length > 0;
    }

    const titleLen = title.length;
    const metaLen = metaDescription.length;
    const noImages = imgTags.length === 0;

    const checks: SeoCheck[] = [];

    // 1. Title (15)
    {
      let pts = 0;
      let detail: string;
      if (!title) {
        detail = 'No <title> tag found';
      } else {
        if (titleLen >= 10 && titleLen <= 60) pts += 7;
        else if (titleLen > 60) pts += 4;
        else pts += 3;
        const generic = /^(home|home page|index|about|website|untitled)$/i.test(title) || titleLen < 4;
        if (!generic) pts += 5;
        if (!generic && titleLen >= 10 && titleLen <= 60) pts += 3;
        detail = `"${title.slice(0, 60)}${titleLen > 60 ? '…' : ''}" (${titleLen} chars)`;
        if (generic) detail += ' — looks like a generic default title';
      }
      checks.push({ id: 'title', label: 'Page title', passed: pts >= 12, points: pts, max: 15, detail });
    }

    // 2. Meta description (10)
    {
      let pts = 0;
      const detail = metaLen ? `"${metaDescription.slice(0, 80)}${metaLen > 80 ? '…' : ''}" (${metaLen} chars)` : 'No meta description found';
      if (metaLen > 0) {
        pts += 5;
        if (metaLen >= 70 && metaLen <= 160) pts += 5;
        else if (metaLen < 70) pts += 3;
        else pts += 2;
      }
      checks.push({ id: 'description', label: 'Meta description', passed: pts >= 8, points: pts, max: 10, detail });
    }

    // 3. H1 (10)
    {
      let pts = 0;
      let detail = `${h1Count} H1 tag${h1Count === 1 ? '' : 's'} found`;
      if (h1Count === 1) pts = 10;
      else if (h1Count === 2 || h1Count === 3) pts = 5;
      else if (h1Count === 0) detail = 'No H1 tag found';
      else detail = `${h1Count} H1 tags — multiple H1s dilute keyword focus`;
      checks.push({ id: 'h1', label: 'H1 heading', passed: h1Count === 1, points: pts, max: 10, detail });
    }

    // 4. Heading hierarchy (5)
    {
      const hasSub = h2Count > 0 || h3Count > 0;
      checks.push({
        id: 'headings',
        label: 'Heading hierarchy',
        passed: hasSub,
        points: hasSub ? 5 : 0,
        max: 5,
        detail: hasSub ? `Found ${h2Count} H2 and ${h3Count} H3 tags` : 'No H2/H3 subheadings — content structure is flat',
      });
    }

    // 5. Image alt text (10)
    {
      let pts: number;
      let detail: string;
      if (noImages) {
        pts = 2;
        detail = 'No images found on the page';
      } else {
        const ratio = altCount / imgTags.length;
        pts = Math.round(ratio * 10);
        detail = `${altCount}/${imgTags.length} images have alt text`;
      }
      checks.push({ id: 'alt', label: 'Image alt text', passed: !noImages && altCount === imgTags.length, points: pts, max: 10, detail });
    }

    // 6. HTTPS (10)
    checks.push({
      id: 'https',
      label: 'HTTPS (secure connection)',
      passed: final.protocol === 'https:',
      points: final.protocol === 'https:' ? 10 : 0,
      max: 10,
      detail: final.protocol === 'https:' ? 'Serving over HTTPS' : `Redirected/loaded over ${final.protocol.replace(':', '')} — not secure`,
    });

    // 7. Mobile viewport (5)
    checks.push({
      id: 'viewport',
      label: 'Mobile viewport',
      passed: hasViewport,
      points: hasViewport ? 5 : 0,
      max: 5,
      detail: hasViewport ? 'Responsive viewport meta tag present' : 'No viewport meta tag — page is not mobile-friendly',
    });

    // 8. Canonical (5)
    checks.push({
      id: 'canonical',
      label: 'Canonical tag',
      passed: !!canonical,
      points: canonical ? 5 : 0,
      max: 5,
      detail: canonical ? 'Canonical URL declared' : 'No canonical tag — duplicate content risk',
    });

    // 9. Open Graph (10)
    {
      let pts = 0;
      if (ogTitle) pts += 4;
      if (ogDescription) pts += 3;
      if (ogImage) pts += 3;
      checks.push({
        id: 'og',
        label: 'Open Graph (social sharing)',
        passed: pts >= 7,
        points: pts,
        max: 10,
        detail: [ogTitle && 'title', ogDescription && 'description', ogImage && 'image'].filter(Boolean).join(', ') || 'No Open Graph tags found',
      });
    }

    // 10. robots.txt (10)
    {
      let pts = 0;
      let detail = 'No robots.txt found';
      if (robotsText) {
        pts += 6;
        detail = '/robots.txt found';
        if (!robotsBlocked) {
          pts += 4;
        } else {
          detail += ' — but it blocks crawlers entirely (Disallow: /)';
        }
      }
      checks.push({ id: 'robots', label: 'robots.txt', passed: !!robotsText && !robotsBlocked, points: pts, max: 10, detail });
    }

    // 11. Sitemap (5)
    {
      let pts = 0;
      let detail = 'No sitemap.xml found';
      if (sitemapOk) {
        pts = 5;
        detail = '/sitemap.xml found';
      } else if (robotsHasSitemap) {
        pts = 2;
        detail = 'No sitemap.xml, but robots.txt declares a Sitemap URL';
      }
      checks.push({ id: 'sitemap', label: 'XML sitemap', passed: sitemapOk, points: pts, max: 5, detail });
    }

    // 12. Content depth (5)
    {
      let pts = 0;
      let detail = `${wordCount} words of visible content`;
      if (wordCount >= 300) pts = 5;
      else if (wordCount >= 100) pts = 3;
      else if (wordCount > 0) pts = 1;
      else detail = 'No readable text content found';
      checks.push({ id: 'content', label: 'Content depth', passed: pts >= 3, points: pts, max: 5, detail });
    }

    const score = Math.min(100, Math.round(checks.reduce((sum, c) => sum + c.points, 0)));

    const result: SeoResult = {
      score,
      grade: GRADE(score),
      url: finalUrl,
      title,
      metaDescription,
      wordCount,
      checks,
    };
    return NextResponse.json(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    const friendly = /fetch failed|network|undici|ECONN|timed out/i.test(message)
      ? 'Could not reach the website. Check the URL or try again.'
      : message;
    return NextResponse.json(
      { error: friendly, checks: [], score: 0, grade: 'F' },
      { status: 422 }
    );
  }
}

export const dynamic = 'force-dynamic';