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
}

export interface SearchStatus {
  id: string;
  status: string;
  progress_percent: number;
  message: string;
  total_results: number;
  hot_leads: number;
  warm_leads: number;
  skipped: number;
  processed_count: number;
  elapsed_seconds: number;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
}

export interface SearchHistoryItem {
  id: string;
  niche: string;
  location: string;
  status: string;
  total_results: number;
  hot_leads: number;
  warm_leads: number;
  skipped: number;
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
  website_url: string | null;
  rating: number | null;
  total_reviews: number;
  lead_category: string;
  website_health_score: number | null;
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
