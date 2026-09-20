import type { NextRequest } from 'next/server';

/**
 * Best-effort client IP for rate limiting / lockouts.
 *
 * `x-forwarded-for` is APPENDED by each proxy (`$proxy_add_x_forwarded_for`),
 * so the FIRST hop is whatever the client sent — an attacker could rotate it
 * and get a fresh allowance on every request, completely defeating a
 * brute-force lockout. We therefore prefer `x-real-ip` (nginx sets it to the
 * peer address) and otherwise use the LAST hop, i.e. the address appended by
 * the closest trusted proxy.
 *
 * Deployments that expose the app without a proxy cannot be protected here at
 * all (every value is client-controlled) — terminate behind one nginx/ALB that
 * overwrites these headers.
 */
export function clientIp(req: NextRequest): string {
  const real = (req.headers.get('x-real-ip') || '').trim();
  if (isIpLike(real)) return real;

  const forwarded = req.headers.get('x-forwarded-for');
  if (forwarded) {
    const hops = forwarded
      .split(',')
      .map((h) => h.trim())
      .filter(Boolean);
    for (let i = hops.length - 1; i >= 0; i -= 1) {
      if (isIpLike(hops[i])) return hops[i];
    }
  }
  // No usable header: shard by UA hash instead of a single global 'unknown'
  // bucket, so one header-less abuser can't lock out all direct-connect users.
  const ua = (req.headers.get('user-agent') || '').slice(0, 200);
  if (ua) {
    let h = 0;
    for (let i = 0; i < ua.length; i += 1) h = (h * 31 + ua.charCodeAt(i)) >>> 0;
    return `unknown-${h.toString(16)}`;
  }
  return 'unknown';
}

/** Loose validation: enough to keep junk out of rate-limit keys. */
function isIpLike(value: string): boolean {
  if (!value || value.length > 45) return false;
  // IPv6 (optionally bracketed, with or without a port) or IPv6-mapped IPv4.
  if (value.includes(':')) {
    const bare = value.replace(/^\[|\]$/g, '').split('%')[0];
    return /^[0-9a-fA-F:.]+$/.test(bare) && bare.includes(':');
  }
  // IPv4, optionally with a port.
  const octets = value.split(':')[0].split('.');
  if (octets.length !== 4) return false;
  return octets.every((o) => /^\d{1,3}$/.test(o) && Number(o) <= 255);
}
