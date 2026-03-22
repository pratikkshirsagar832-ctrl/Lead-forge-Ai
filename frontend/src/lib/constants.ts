export const API_ROUTES = {
  health: '/api/health',
  auth: {
    me: '/api/auth/me',
    profile: '/api/auth/profile',
  },
  searches: {
    create: '/api/searches',
    list: '/api/searches',
    detail: (id: string) => `/api/searches/${id}`,
    status: (id: string) => `/api/searches/${id}/status`,
    cancel: (id: string) => `/api/searches/${id}/cancel`,
  },
  leads: {
    list: '/api/leads',
    export: '/api/leads/export',
    detail: (id: string) => `/api/leads/${id}`,
    status: (id: string) => `/api/leads/${id}/status`,
    notes: (id: string) => `/api/leads/${id}/notes`,
    favorite: (id: string) => `/api/leads/${id}/favorite`,
  },
  dashboard: {
    stats: '/api/dashboard/stats',
  },
  ai: {
    pitch: (leadId: string) => `/api/ai/pitch/${leadId}`,
  },
} as const;

export const LEAD_CATEGORIES = {
  hot: { label: 'Hot', color: '#EF4444', bg: '#FEE2E2' },
  warm: { label: 'Warm', color: '#F59E0B', bg: '#FEF3C7' },
  skip: { label: 'Skip', color: '#64748B', bg: '#F1F5F9' },
} as const;

export const USER_STATUSES = {
  new: { label: 'New', color: '#6366F1' },
  contacted: { label: 'Contacted', color: '#3B82F6' },
  replied: { label: 'Replied', color: '#10B981' },
  converted: { label: 'Converted', color: '#059669' },
  lost: { label: 'Lost', color: '#DC2626' },
} as const;

export const SEARCH_STATUSES = {
  queued: { label: 'Queued', color: '#6366F1' },
  scraping: { label: 'Scraping', color: '#F59E0B' },
  analyzing: { label: 'Analyzing', color: '#3B82F6' },
  completed: { label: 'Completed', color: '#10B981' },
  failed: { label: 'Failed', color: '#DC2626' },
  cancelled: { label: 'Cancelled', color: '#64748B' },
} as const;

export const POLLING_INTERVAL = 2000;
