# 04 — FRONTEND (Next.js)

## Architecture

```
frontend/src/
├── app/                 # Next.js App Router (23 pages)
│   ├── layout.tsx       # Root layout
│   ├── page.tsx         # Landing page
│   ├── login/           # Auth
│   ├── dashboard/       # Main app
│   ├── admin/           # Admin panel
│   ├── blogs/           # Content
│   └── tools/           # SEO tools
├── components/          # React components (39 files)
│   ├── landing/         # Marketing pages
│   ├── dashboard/       # App components
│   ├── auth/            # Auth guards
│   ├── shared/          # Reusable UI
│   └── ui/              # Radix primitives
├── hooks/               # Custom React hooks (3 files)
├── stores/              # Zustand state (2 files)
├── lib/                 # Utilities (6 files)
├── styles/              # CSS (1 file)
└── types/               # TypeScript (empty)
```

---

## Key Technologies

| Technology | Purpose |
|-----------|---------|
| **Next.js 16.3** | React framework (App Router) |
| **React 18.3** | UI library |
| **TypeScript 5** | Type safety |
| **Tailwind CSS 4** | Utility-first CSS |
| **Framer Motion** | Animations |
| **Zustand** | State management |
| **Supabase JS** | Auth client |
| **Axios** | HTTP client |
| **Radix UI** | Accessible components |

---

## Pages

### Landing Page (`/`)

Components:
- `Header.tsx` — Nav bar with logo, links, CTA
- `Hero.tsx` — Main hero section with animated text
- `Features.tsx` — Feature cards with icons
- `HowItWorks.tsx` — Step-by-step explanation
- `Footer.tsx` — Footer with links

All wrapped in `ScrollReveal` components with Framer Motion animations.

### Dashboard Layout (`/dashboard/layout.tsx`)

```
┌─────────────────────────────────────────┐
│  Sidebar (fixed left)                   │
│  - Logo                                 │
│  - Nav links (Search, Leads, History)   │
│  - User info                            │
│  - Upgrade button                       │
├─────────────────────────────────────────┤
│  Main Content Area                      │
│  - Stats cards (top)                    │
│  - Page content                         │
└─────────────────────────────────────────┘
```

### Search Page (`/dashboard/search/page.tsx`)

**The main user-facing search interface.**

State variables:
```typescript
const [niche, setNiche] = useState("")
const [location, setLocation] = useState("")
const [source, setSource] = useState<"linkedin" | "google_maps">("linkedin")
const [leadTypes, setLeadTypes] = useState<("buyer" | "hiring")[]>([])
const [maxResults, setMaxResults] = useState(10)
```

UI Flow:
```
┌─────────────────────────────────────┐
│  Search Form                        │
│  [Niche input]                      │
│  [Location input]                   │
│  [Source: LinkedIn | Google Maps]   │
│  [Lead Types: ☐ Buyer ☐ Hiring]     │
│  [Count: 1-50 slider]              │
│  [🔍 Search Button]                │
└─────────────────────────────────────┘
          ↓
┌─────────────────────────────────────┐
│  Search Progress Card               │
│  ━━━━━━━━━━━━━━━━━━ 45%            │
│  "AI qualifying 87 leads..."        │
│  [Cancel Button]                    │
└─────────────────────────────────────┘
          ↓
┌─────────────────────────────────────┐
│  Results Grid                       │
│  [LeadCard] [LeadCard] [LeadCard]   │
│  [LeadCard] [LeadCard] [LeadCard]   │
│  ... (progressive loading)          │
└─────────────────────────────────────┘
```

### Leads Page (`/dashboard/leads/page.tsx`)

**Lead management with filters.**

Filters:
```typescript
const [filters, setFilters] = useState({
    status: "",        // new, contacted, replied, converted, lost
    category: "",      // hot, warm
    isFavorite: false,
    search: "",        // full-text search
    searchId: "",      // filter by search
    source: "",        // linkedin, google_maps
    postType: "",      // buyer, hiring, job_seeker
    page: 1,
    limit: 20,
})
```

UI:
```
┌─────────────────────────────────────┐
│  Filters Bar                        │
│  [Status ▼] [Category ▼] [Source ▼] │
│  [Post Type ▼] [Search 🔍]         │
│  [❤️ Favorites] [Export CSV]        │
└─────────────────────────────────────┘
          ↓
┌─────────────────────────────────────┐
│  Lead Cards Grid                    │
│  ┌────────────┐ ┌────────────┐     │
│  │ LeadCard 1 │ │ LeadCard 2 │     │
│  │ Score: 85  │ │ Score: 72  │     │
│  │ 🔥 Hot     │ │ 🟡 Warm    │     │
│  │ [♥] [→]    │ │ [♥] [→]    │     │
│  └────────────┘ └────────────┘     │
└─────────────────────────────────────┘
          ↓
┌─────────────────────────────────────┐
│  Pagination                         │
│  [← Prev] Page 1 of 5 [Next →]    │
└─────────────────────────────────────┘
```

### Lead Detail Page (`/dashboard/leads/[id]/page.tsx`)

```
┌─────────────────────────────────────┐
│  Lead Header                        │
│  John Smith - CEO @ Acme Corp       │
│  Score: 85/100 🔥                   │
│  [♥ Favorite] [← Back]             │
├─────────────────────────────────────┤
│  Contact Info                       │
│  📧 john@acme.com                   │
│  📱 +1-555-0123                     │
│  🔗 linkedin.com/in/johnsmith      │
│  🌐 acme.com                        │
├─────────────────────────────────────┤
│  Post Content                       │
│  "Looking for a website developer   │
│   to redesign our corporate site..."│
│  [View Original Post →]             │
├─────────────────────────────────────┤
│  Score Breakdown                    │
│  Intent: 85/100 ████████░░         │
│  Fit: 90/100 █████████░░           │
│  Urgency: 70/100 ███████░░░        │
│  ...                                │
├─────────────────────────────────────┤
│  AI Pitch                           │
│  "Hi John, I noticed Acme Corp is   │
│   looking for a website developer..."│
│  [Generate New Pitch]               │
├─────────────────────────────────────┤
│  User Notes                         │
│  [textarea for notes]               │
│  [Save Notes]                       │
├─────────────────────────────────────┤
│  Pipeline Status                    │
│  [New] → [Contacted] → [Replied]   │
│  → [Converted] → [Lost]            │
└─────────────────────────────────────┘
```

---

## Components

### Dashboard Components

| Component | File | Purpose |
|-----------|------|---------|
| `Sidebar.tsx` | Dashboard sidebar | Navigation, user info, upgrade CTA |
| `StatsCards.tsx` | Dashboard overview | Key metrics cards |
| `LeadCard.tsx` | Lead list item | Compact lead display |
| `FiltersBar.tsx` | Lead filters | Filter dropdowns |
| `SearchProgressCard.tsx` | Search progress | Live progress bar |
| `PostTypeBadge.tsx` | Post type badge | Buyer/Hiring/JobSeeker badge |
| `ScoreBreakdown.tsx` | Score details | 6-dimension score visualization |
| `DeepAnalysisReport.tsx` | Website analysis | Full analysis report |
| `EmptyState.tsx` | Empty states | No results placeholder |
| `PlanGuard.tsx` | Plan gate | Upgrade prompt for locked features |

### LeadCard.tsx

```tsx
function LeadCard({ lead }: { lead: LeadListItem }) {
    return (
        <GlassCard className="p-4 hover:scale-[1.02]">
            {/* Header */}
            <div className="flex justify-between">
                <h3>{lead.full_name}</h3>
                <PostTypeBadge type={lead.post_type} />
            </div>
            
            {/* Company */}
            <p className="text-sm text-gray-400">{lead.company}</p>
            
            {/* Score */}
            <div className="flex items-center gap-2">
                <ScoreRing score={lead.ai_confidence_score} />
                <span>{lead.ai_confidence_score}/100</span>
            </div>
            
            {/* Category */}
            <Badge variant={lead.lead_category === "hot" ? "danger" : "warning"}>
                {lead.lead_category}
            </Badge>
            
            {/* Actions */}
            <div className="flex gap-2">
                <Button onClick={toggleFavorite}>
                    {lead.is_favorite ? "❤️" : "🤍"}
                </Button>
                <Button onClick={() => router.push(`/leads/${lead.id}`)}>
                    View →
                </Button>
            </div>
        </GlassCard>
    )
}
```

### PostTypeBadge.tsx

```tsx
const POST_TYPE_CONFIG = {
    buyer: { label: "Buyer", color: "bg-green-500/20 text-green-400" },
    hiring: { label: "Hiring", color: "bg-blue-500/20 text-blue-400" },
    job_seeker: { label: "Job Seeker", color: "bg-yellow-500/20 text-yellow-400" },
}

function PostTypeBadge({ type }: { type: string }) {
    const config = POST_TYPE_CONFIG[type]
    return (
        <span className={`px-2 py-1 rounded-full text-xs ${config.color}`}>
            {config.label}
        </span>
    )
}
```

---

## Hooks

### `useSearch.ts` — Search Orchestration

```typescript
function useSearch() {
    const { activeSearchId, setActiveSearch, setProgress, setResults } = useSearchStore()
    
    async function startSearch(params: SearchParams) {
        // 1. POST /api/searches
        const { search_id } = await api.post("/api/searches", params)
        setActiveSearch(search_id)
        
        // 2. Start polling
        pollStatus(search_id)
        pollResults(search_id)
    }
    
    async function pollStatus(searchId: string) {
        const interval = setInterval(async () => {
            const status = await api.get(`/api/searches/${searchId}/status`)
            setProgress(status.progress_percent, status.message)
            
            if (status.status === "completed") {
                clearInterval(interval)
                fetchFinalResults(searchId)
            }
        }, 2000)  // Poll every 2 seconds
    }
    
    async function pollResults(searchId: string) {
        // Progressive loading: 4 leads every 4 seconds
        const interval = setInterval(async () => {
            const results = await api.get(`/api/searches/${searchId}/results`, {
                params: { offset: currentOffset, limit: 4 }
            })
            appendResults(results)
            currentOffset += 4
            
            if (results.length < 4) {
                clearInterval(interval)
            }
        }, 4000)
    }
    
    return { startSearch, cancelSearch }
}
```

### `useLeads.ts` — Lead Management

```typescript
function useLeads() {
    const { leads, setLeads, filters, setFilters } = useLeadStore()
    
    async function fetchLeads() {
        const response = await api.get("/api/leads", { params: filters })
        setLeads(response.data.leads, response.data.total)
    }
    
    async function updateLeadStatus(leadId: string, status: string) {
        // Optimistic update
        const previous = leads.find(l => l.id === leadId)
        updateLeadInStore(leadId, { user_status: status })
        
        try {
            await api.patch(`/api/leads/${leadId}/status`, { user_status: status })
        } catch (error) {
            // Rollback on failure
            updateLeadInStore(leadId, { user_status: previous.user_status })
        }
    }
    
    async function exportCsv() {
        const response = await api.get("/api/leads/export", {
            params: filters,
            responseType: "blob"
        })
        // Download file
        const url = window.URL.createObjectURL(response.data)
        const a = document.createElement("a")
        a.href = url
        a.download = "leads.csv"
        a.click()
    }
    
    return { fetchLeads, updateLeadStatus, exportCsv }
}
```

---

## State Management (Zustand)

### `searchStore.ts`

```typescript
interface SearchState {
    activeSearchId: string | null
    progress: number
    message: string
    results: LeadListItem[]
    resultsTotal: number
    history: SearchHistoryItem[]
    requestedCount: number
    unlocked: boolean
    limitHit: boolean
    
    // Actions
    setActiveSearch: (id: string) => void
    setProgress: (progress: number, message: string) => void
    setResults: (leads: LeadListItem[], total: number) => void
    appendResults: (leads: LeadListItem[]) => void  // Deduplicates
    clearActiveSearch: () => void
}
```

### `leadStore.ts`

```typescript
interface LeadState {
    leads: LeadListItem[]
    totalCount: number
    filters: {
        status: string
        category: string
        isFavorite: boolean
        search: string
        searchId: string
        source: string
        postType: string
        page: number
        limit: number
    }
    
    // Actions
    setLeads: (leads: LeadListItem[], total: number) => void
    setFilters: (filters: Partial<FilterState>) => void  // Resets page to 1
    updateLeadInStore: (id: string, updates: Partial<LeadListItem>) => void
}
```

---

## API Client (`lib/api.ts`)

```typescript
const api = axios.create({
    baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
    timeout: 330000,  // 5.5 minutes
})

// Auth interceptor
api.interceptors.request.use(async (config) => {
    const { data: { session } } = await supabase.auth.getSession()
    if (session?.access_token) {
        config.headers.Authorization = `Bearer ${session.access_token}`
    }
    return config
})

// 401 handler
api.interceptors.response.use(
    (response) => response,
    async (error) => {
        if (error.response?.status === 401) {
            await supabase.auth.signOut()
            window.location.href = "/login"
        }
        return Promise.reject(error)
    }
)
```

---

## Supabase Client (`lib/supabase.ts`)

```typescript
// Lazy initialization with graceful fallback
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseKey) {
    // Mock client for builds without env vars
    export const supabase = new Proxy({}, {
        get: () => ({
            auth: { getSession: () => Promise.resolve({ data: { session: null } }) }
        })
    })
} else {
    export const supabase = createBrowserClient(supabaseUrl, supabaseKey)
}
```

---

## Design System (`globals.css`)

### Brand Colors

```css
:root {
    --primary: #0D4F4A;        /* Teal */
    --primary-light: #1A7A73;
    --accent: #FFB020;         /* Amber */
    --background: #06231F;     /* Deep Green */
    --surface: #0A2E29;
    --text: #F5F5F5;
    --text-muted: #94A3B8;
}
```

### Key Classes

```css
/* Glass card effect */
.glass-card {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 12px;
}

/* Neon button */
.btn-neon {
    background: linear-gradient(135deg, #0D4F4A, #1A7A73);
    box-shadow: 0 0 20px rgba(13, 79, 74, 0.5);
    transition: all 0.3s ease;
}
.btn-neon:hover {
    box-shadow: 0 0 30px rgba(13, 79, 74, 0.8);
    transform: translateY(-2px);
}

/* Gradient button */
.btn-gradient-cyan {
    background: linear-gradient(135deg, #06B6D4, #0891B2);
}

/* Shimmer loading */
.shimmer {
    background: linear-gradient(90deg, 
        rgba(255,255,255,0.05) 25%, 
        rgba(255,255,255,0.1) 50%, 
        rgba(255,255,255,0.05) 75%
    );
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
}
```

---

## Animations (`animations.tsx`)

```typescript
// Stagger container for lists
export const staggerContainer = {
    hidden: { opacity: 0 },
    show: {
        opacity: 1,
        transition: { staggerChildren: 0.1 }
    }
}

// Fade in up
export const fadeInUp = {
    hidden: { opacity: 0, y: 20 },
    show: { opacity: 1, y: 0 }
}

// Card hover
export const cardHover = {
    rest: { scale: 1 },
    hover: { scale: 1.02, transition: { duration: 0.2 } }
}

// Scroll reveal wrapper
export function ScrollReveal({ children }) {
    return (
        <motion.div
            initial="hidden"
            whileInView="show"
            viewport={{ once: true }}
            variants={staggerContainer}
        >
            {children}
        </motion.div>
    )
}
```

---

## Routing

| Path | Page | Auth |
|------|------|------|
| `/` | Landing page | No |
| `/login` | Login | No |
| `/auth/callback` | OAuth callback | No |
| `/pricing` | Pricing plans | No |
| `/dashboard` | Overview stats | Yes |
| `/dashboard/search` | LinkedIn search | Yes |
| `/dashboard/leads` | Lead list | Yes |
| `/dashboard/leads/[id]` | Lead detail | Yes |
| `/dashboard/history` | Search history | Yes |
| `/dashboard/billing` | Subscription | Yes |
| `/dashboard/settings` | Account settings | Yes |
| `/dashboard/team` | Team management | Yes (Pro/Agency) |
| `/admin` | Admin dashboard | Admin |
| `/admin/login` | Admin login | No |
| `/blogs` | Blog list | No |
| `/blogs/[slug]` | Blog post | No |
| `/about-us` | About page | No |
| `/terms` | Terms of service | No |
| `/privacy-policy` | Privacy policy | No |
| `/refund-policy` | Refund policy | No |
| `/tools/seo-score-checker` | SEO tool | No |
