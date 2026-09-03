export interface SubscriptionInfo {
  plan_id: string;
  plan_name: string;
  status: string;
  searches_per_day: number;
  leads_per_day: number;
  remaining_searches: number;
  remaining_leads: number;
  current_period_start?: string;
  current_period_end?: string;
  trial_end?: string;
  is_trial_expired?: boolean;
  is_team_seat?: boolean;
  linkedin_hq_leads_monthly: number;
  gmb_leads_monthly: number;
  linkedin_hq_leads_used: number;
  gmb_leads_used: number;
  linkedin_hq_leads_remaining: number;
  gmb_leads_remaining: number;
}

export interface Plan {
  id: string;
  name: string;
  price_monthly: number;
  searches_per_day: number;
  leads_per_day: number;
  is_active: boolean;
  sort_order: number;
  features: string[];
  linkedin_hq_leads_monthly?: number;
  gmb_leads_monthly?: number;
}

export interface SearchStatus {
  id: string;
  status: string;
  source?: string;
  progress_percent: number;
  message: string;
  total_results: number;
  hot_leads: number;
  warm_leads: number;
  skipped: number;
  emails_found?: number;
  processed_count: number;
  elapsed_seconds: number;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  requested_count?: number;
  returned_count?: number;
  lead_type?: string;
  country?: string;
  service?: string;
  lead_status?: string;
}

export interface SearchHistoryItem {
  id: string;
  niche: string;
  location: string;
  source?: string;
  status: string;
  total_results: number;
  hot_leads: number;
  warm_leads: number;
  skipped: number;
  emails_found?: number;
  created_at?: string;
  completed_at?: string;
}

export interface LeadListItem {
  id: string;
  search_id: string;
  source?: string;
  business_name: string;
  category: string | null;
  full_address: string | null;
  phone: string | null;
  email_found?: string | null;
  website_url: string | null;
  rating: number | null;
  total_reviews: number;
  lead_category: string;
  website_health_score: number | null;
  headline?: string | null;
  linkedin_url?: string | null;
  post_url?: string | null;
  post_text?: string | null;
  profile_picture_url?: string | null;
  connections_count?: number;
  posted_at?: string | null;
  post_type?: string | null;
  ai_confidence_score?: number | null;
  ai_pitch?: string | null;
  user_status: string;
  user_notes?: string;
  is_favorite: boolean;
  has_pitch: boolean;
  created_at?: string;
}

export interface LeadDetail {
  id: string;
  search_id: string;
  user_id: string;
  source?: string;
  business_name: string;
  category: string | null;
  full_address: string | null;
  phone: string | null;
  email_found?: string | null;
  website_url: string | null;
  rating: number | null;
  total_reviews: number;
  google_maps_link?: string | null;
  headline?: string | null;
  linkedin_url?: string | null;
  post_url?: string | null;
  post_text?: string | null;
  profile_picture_url?: string | null;
  connections_count?: number;
  posted_at?: string | null;
  post_type?: string | null;
  lead_category: string;
  website_health_score: number | null;
  ai_pitch?: string | null;
  ai_confidence_score?: number | null;
  user_status: string;
  user_notes?: string;
  is_favorite: boolean;
  created_at?: string;
  website_analyses?: unknown[];
}

export interface LeadPaginatedResponse {
  items: LeadListItem[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

// ── HyperAgent (LinkedIn lead agent) ────────────────────────────────────────
export interface AgentCookieStatus {
  configured: boolean;
  expired: boolean;
  expires_at?: string | null;
  note?: string;
}

export interface AgentGuide {
  title: string;
  what: string;
  steps: string[];
  why?: string;
  does?: string;
}

export interface AgentChatState {
  step: string;
  cookie_status: AgentCookieStatus;
  guide?: AgentGuide | null;
  data?: Record<string, unknown>;
}

export interface AgentChatResponse {
  message: string;
  done: boolean;
  next_step?: string;
  step?: string;
  options?: string[];
  guide?: AgentGuide | null;
  run?: { id?: string; status?: string; error?: string } | null;
}

export interface AgentRun {
  id: string;
  service?: string;
  country?: string;
  status: string;
  progress_percent: number;
  message?: string;
  total_results: number;
  hot_leads: number;
  warm_leads: number;
  emails_found: number;
  created_at?: string;
  completed_at?: string;
  lead_type?: string;
}

export interface AgentRunDetail extends AgentRun {
  skipped: number;
  error_message?: string;
  max_results?: number;
}

export interface AgentRunHistoryResponse {
  items: AgentRun[];
  total: number;
}
