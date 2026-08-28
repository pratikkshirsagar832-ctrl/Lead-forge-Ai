/** @type {import('next').NextConfig} */

// FastAPI backend base URL. Set NEXT_PUBLIC_API_URL in Vercel to your
// deployed backend (e.g. https://api.yourdomain.com). Local fallback only.
const apiUrl = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

const nextConfig = {
  reactStrictMode: false,
  output: 'standalone',
  images: {
    dangerouslyAllowSVG: true,
    contentDispositionType: 'attachment',
    contentSecurityPolicy: "default-src 'self'; script-src 'none'; sandbox;",
  },
  async rewrites() {
    // Proxy FastAPI endpoints (/api/searches, /api/leads, /api/auth, ...) to the
    // Python backend. Local Next.js API routes under /api/tools and the admin
    // blog API (/api/admin/...) are kept. HyperAgent now routes to backend.
    return [
      {
        source: '/api/:path((?!admin/|tools/).*)',
        destination: `${apiUrl}/api/:path`,
      },
    ];
  },
};

export default nextConfig;
