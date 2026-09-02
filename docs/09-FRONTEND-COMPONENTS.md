# 09 — FRONTEND COMPONENTS GUIDE

## Complete Component Reference

---

## Component Architecture

```
frontend/src/components/
├── landing/           # Marketing pages
│   ├── Hero.tsx       # Main hero section
│   ├── Features.tsx   # Feature cards
│   ├── HowItWorks.tsx # Step-by-step
│   ├── Header.tsx     # Navigation
│   ├── Footer.tsx     # Footer
│   └── ContentPage.tsx # Generic content
│
├── dashboard/         # App components
│   ├── Sidebar.tsx    # Dashboard sidebar
│   ├── StatsCards.tsx # Overview stats
│   ├── LeadCard.tsx   # Lead list item
│   ├── FiltersBar.tsx # Filter dropdowns
│   ├── SearchProgressCard.tsx # Live progress
│   ├── PostTypeBadge.tsx # Buyer/Hiring badge
│   ├── ScoreBreakdown.tsx # Score visualization
│   ├── DeepAnalysisReport.tsx # Website analysis
│   ├── EmptyState.tsx # No results
│   └── PlanGuard.tsx  # Upgrade prompt
│
├── auth/              # Authentication
│   └── AuthGuard.tsx  # Protected route
│
├── shared/            # Reusable UI
│   ├── GlassCard.tsx  # Glass effect card
│   ├── Badge.tsx      # Status badge
│   ├── Modal.tsx      # Dialog modal
│   ├── Toast.tsx      # Notifications
│   ├── Skeleton.tsx   # Loading skeleton
│   ├── LoadingButton.tsx # Button with spinner
│   └── UpgradeModal.tsx # Upgrade prompt
│
└── ui/                # Radix primitives
    ├── button.tsx
    ├── input.tsx
    ├── textarea.tsx
    ├── card.tsx
    ├── dialog.tsx
    ├── checkbox.tsx
    ├── switch.tsx
    ├── tabs.tsx
    ├── progress.tsx
    └── badge.tsx
```

---

## Dashboard Components

### Sidebar.tsx

**Purpose:** Dashboard navigation and user info.

```tsx
"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { motion } from "framer-motion"

const navItems = [
    { href: "/dashboard", label: "Overview", icon: "📊" },
    { href: "/dashboard/search", label: "Search", icon: "🔍" },
    { href: "/dashboard/leads", label: "Leads", icon: "👥" },
    { href: "/dashboard/history", label: "History", icon: "📜" },
    { href: "/dashboard/billing", label: "Billing", icon: "💳" },
    { href: "/dashboard/settings", label: "Settings", icon: "⚙️" },
    { href: "/dashboard/team", label: "Team", icon: "👥", badge: "Pro" },
]

export function Sidebar() {
    const pathname = usePathname()
    
    return (
        <aside className="fixed left-0 top-0 h-full w-64 bg-surface border-r border-white/10">
            {/* Logo */}
            <div className="p-6">
                <h1 className="text-xl font-bold text-white">Lead Forge AI</h1>
            </div>
            
            {/* Navigation */}
            <nav className="px-4 space-y-1">
                {navItems.map((item) => (
                    <Link
                        key={item.href}
                        href={item.href}
                        className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                            pathname === item.href
                                ? "bg-primary/20 text-primary-light"
                                : "text-gray-400 hover:bg-white/5"
                        }`}
                    >
                        <span>{item.icon}</span>
                        <span>{item.label}</span>
                        {item.badge && (
                            <span className="ml-auto px-2 py-0.5 text-xs bg-accent/20 text-accent rounded">
                                {item.badge}
                            </span>
                        )}
                    </Link>
                ))}
            </nav>
            
            {/* User Info */}
            <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-white/10">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
                        {user?.email?.charAt(0).toUpperCase()}
                    </div>
                    <div>
                        <p className="text-sm text-white">{user?.email}</p>
                        <p className="text-xs text-gray-400">Free Trial</p>
                    </div>
                </div>
            </div>
        </aside>
    )
}
```

---

### LeadCard.tsx

**Purpose:** Display a single lead in the list.

```tsx
"use client"

import Link from "next/link"
import { motion } from "framer-motion"
import { PostTypeBadge } from "./PostTypeBadge"
import { ScoreRing } from "./ScoreBreakdown"

interface LeadCardProps {
    lead: {
        id: string
        full_name: string
        company: string
        headline: string
        ai_confidence_score: number
        post_type: string
        lead_category: string
        is_favorite: boolean
        created_at: string
    }
    onToggleFavorite: (id: string) => void
}

export function LeadCard({ lead, onToggleFavorite }: LeadCardProps) {
    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            whileHover={{ scale: 1.02 }}
            className="glass-card p-4 cursor-pointer"
        >
            <Link href={`/dashboard/leads/${lead.id}`}>
                {/* Header */}
                <div className="flex justify-between items-start mb-3">
                    <div>
                        <h3 className="text-white font-medium">{lead.full_name}</h3>
                        <p className="text-sm text-gray-400">{lead.company}</p>
                    </div>
                    <PostTypeBadge type={lead.post_type} />
                </div>
                
                {/* Score */}
                <div className="flex items-center gap-3 mb-3">
                    <ScoreRing score={lead.ai_confidence_score} />
                    <div>
                        <p className="text-white font-medium">
                            {lead.ai_confidence_score}/100
                        </p>
                        <p className="text-xs text-gray-400">
                            {lead.lead_category === "hot" ? "🔥 Hot" : "🟡 Warm"}
                        </p>
                    </div>
                </div>
                
                {/* Headline */}
                <p className="text-sm text-gray-300 line-clamp-2 mb-3">
                    {lead.headline}
                </p>
                
                {/* Footer */}
                <div className="flex justify-between items-center">
                    <span className="text-xs text-gray-500">
                        {new Date(lead.created_at).toLocaleDateString()}
                    </span>
                    <button
                        onClick={(e) => {
                            e.preventDefault()
                            onToggleFavorite(lead.id)
                        }}
                        className="text-lg"
                    >
                        {lead.is_favorite ? "❤️" : "🤍"}
                    </button>
                </div>
            </Link>
        </motion.div>
    )
}
```

---

### SearchProgressCard.tsx

**Purpose:** Display live search progress.

```tsx
"use client"

import { motion } from "framer-motion"

interface SearchProgressCardProps {
    progress: number
    message: string
    resultsFound: number
    leadsGenerated: number
    onCancel: () => void
}

export function SearchProgressCard({
    progress,
    message,
    resultsFound,
    leadsGenerated,
    onCancel
}: SearchProgressCardProps) {
    return (
        <div className="glass-card p-6">
            {/* Progress Bar */}
            <div className="mb-4">
                <div className="flex justify-between text-sm mb-2">
                    <span className="text-gray-400">Progress</span>
                    <span className="text-white">{progress}%</span>
                </div>
                <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                    <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${progress}%` }}
                        className="h-full bg-gradient-to-r from-primary to-primary-light"
                    />
                </div>
            </div>
            
            {/* Status Message */}
            <p className="text-gray-300 text-sm mb-4">{message}</p>
            
            {/* Stats */}
            <div className="grid grid-cols-2 gap-4 mb-4">
                <div className="text-center">
                    <p className="text-2xl font-bold text-white">{resultsFound}</p>
                    <p className="text-xs text-gray-400">Results Found</p>
                </div>
                <div className="text-center">
                    <p className="text-2xl font-bold text-accent">{leadsGenerated}</p>
                    <p className="text-xs text-gray-400">Leads Generated</p>
                </div>
            </div>
            
            {/* Cancel Button */}
            <button
                onClick={onCancel}
                className="w-full py-2 px-4 bg-red-500/20 text-red-400 rounded-lg hover:bg-red-500/30 transition-colors"
            >
                Cancel Search
            </button>
        </div>
    )
}
```

---

### PostTypeBadge.tsx

**Purpose:** Display lead type badge.

```tsx
"use client"

const POST_TYPE_CONFIG = {
    buyer: {
        label: "Buyer",
        color: "bg-green-500/20 text-green-400 border-green-500/30"
    },
    hiring: {
        label: "Hiring",
        color: "bg-blue-500/20 text-blue-400 border-blue-500/30"
    },
    job_seeker: {
        label: "Job Seeker",
        color: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30"
    }
}

interface PostTypeBadgeProps {
    type: string
}

export function PostTypeBadge({ type }: PostTypeBadgeProps) {
    const config = POST_TYPE_CONFIG[type] || POST_TYPE_CONFIG.buyer
    
    return (
        <span className={`px-2 py-1 text-xs rounded-full border ${config.color}`}>
            {config.label}
        </span>
    )
}
```

---

### ScoreBreakdown.tsx

**Purpose:** Display 6-dimension score visualization.

```tsx
"use client"

interface ScoreBreakdownProps {
    scores: {
        intent: number
        fit: number
        urgency: number
        engagement: number
        recency: number
        decision_maker: number
    }
}

export function ScoreBreakdown({ scores }: ScoreBreakdownProps) {
    const dimensions = [
        { key: "intent", label: "Intent", weight: "30%" },
        { key: "fit", label: "Fit", weight: "20%" },
        { key: "urgency", label: "Urgency", weight: "15%" },
        { key: "engagement", label: "Engagement", weight: "10%" },
        { key: "recency", label: "Recency", weight: "10%" },
        { key: "decision_maker", label: "Decision Maker", weight: "15%" }
    ]
    
    return (
        <div className="space-y-3">
            <h3 className="text-white font-medium">Score Breakdown</h3>
            
            {dimensions.map((dim) => (
                <div key={dim.key}>
                    <div className="flex justify-between text-sm mb-1">
                        <span className="text-gray-400">
                            {dim.label} ({dim.weight})
                        </span>
                        <span className="text-white">
                            {scores[dim.key]}/100
                        </span>
                    </div>
                    <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                        <div
                            className={`h-full rounded-full ${
                                scores[dim.key] >= 80
                                    ? "bg-green-500"
                                    : scores[dim.key] >= 60
                                    ? "bg-yellow-500"
                                    : "bg-red-500"
                            }`}
                            style={{ width: `${scores[dim.key]}%` }}
                        />
                    </div>
                </div>
            ))}
        </div>
    )
}
```

---

### FiltersBar.tsx

**Purpose:** Lead filter dropdowns.

```tsx
"use client"

import { useLeadStore } from "@/stores/leadStore"

const STATUS_OPTIONS = [
    { value: "", label: "All Statuses" },
    { value: "new", label: "New" },
    { value: "contacted", label: "Contacted" },
    { value: "replied", label: "Replied" },
    { value: "converted", label: "Converted" },
    { value: "lost", label: "Lost" }
]

const CATEGORY_OPTIONS = [
    { value: "", label: "All Categories" },
    { value: "hot", label: "🔥 Hot" },
    { value: "warm", label: "🟡 Warm" }
]

const SOURCE_OPTIONS = [
    { value: "", label: "All Sources" },
    { value: "linkedin", label: "LinkedIn" },
    { value: "google_maps", label: "Google Maps" }
]

export function FiltersBar() {
    const { filters, setFilters } = useLeadStore()
    
    return (
        <div className="flex flex-wrap gap-4 p-4 bg-surface rounded-lg border border-white/10">
            {/* Status Filter */}
            <select
                value={filters.status}
                onChange={(e) => setFilters({ status: e.target.value })}
                className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm"
            >
                {STATUS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                        {opt.label}
                    </option>
                ))}
            </select>
            
            {/* Category Filter */}
            <select
                value={filters.category}
                onChange={(e) => setFilters({ category: e.target.value })}
                className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm"
            >
                {CATEGORY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                        {opt.label}
                    </option>
                ))}
            </select>
            
            {/* Source Filter */}
            <select
                value={filters.source}
                onChange={(e) => setFilters({ source: e.target.value })}
                className="bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm"
            >
                {SOURCE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                        {opt.label}
                    </option>
                ))}
            </select>
            
            {/* Favorites Toggle */}
            <button
                onClick={() => setFilters({ isFavorite: !filters.isFavorite })}
                className={`px-3 py-2 rounded-lg text-sm ${
                    filters.isFavorite
                        ? "bg-red-500/20 text-red-400"
                        : "bg-white/5 text-gray-400"
                }`}
            >
                ❤️ Favorites
            </button>
            
            {/* Search Input */}
            <input
                type="text"
                placeholder="Search leads..."
                value={filters.search}
                onChange={(e) => setFilters({ search: e.target.value })}
                className="flex-1 min-w-[200px] bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-white text-sm placeholder-gray-500"
            />
        </div>
    )
}
```

---

## Shared Components

### GlassCard.tsx

**Purpose:** Glass morphism card effect.

```tsx
"use client"

import { motion } from "framer-motion"

interface GlassCardProps {
    children: React.ReactNode
    className?: string
    hover?: boolean
}

export function GlassCard({ children, className = "", hover = true }: GlassCardProps) {
    return (
        <motion.div
            whileHover={hover ? { scale: 1.02 } : undefined}
            className={`glass-card ${className}`}
        >
            {children}
        </motion.div>
    )
}
```

### Toast.tsx

**Purpose:** Notification toasts.

```tsx
"use client"

import { motion, AnimatePresence } from "framer-motion"
import { useToast } from "@/hooks/useToast"

const TOAST_STYLES = {
    success: "bg-green-500/20 border-green-500/30 text-green-400",
    error: "bg-red-500/20 border-red-500/30 text-red-400",
    info: "bg-blue-500/20 border-blue-500/30 text-blue-400",
    warning: "bg-yellow-500/20 border-yellow-500/30 text-yellow-400"
}

export function Toast() {
    const { toasts, removeToast } = useToast()
    
    return (
        <div className="fixed bottom-4 right-4 z-50 space-y-2">
            <AnimatePresence>
                {toasts.map((toast) => (
                    <motion.div
                        key={toast.id}
                        initial={{ opacity: 0, x: 100 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: 100 }}
                        className={`px-4 py-3 rounded-lg border ${TOAST_STYLES[toast.type]}`}
                    >
                        <p>{toast.message}</p>
                        <button
                            onClick={() => removeToast(toast.id)}
                            className="absolute top-2 right-2 text-gray-400 hover:text-white"
                        >
                            ×
                        </button>
                    </motion.div>
                ))}
            </AnimatePresence>
        </div>
    )
}
```

---

## Landing Page Components

### Hero.tsx

**Purpose:** Main hero section with animated text.

```tsx
"use client"

import { motion } from "framer-motion"
import { fadeInUp, staggerContainer } from "@/lib/animations"

export function Hero() {
    return (
        <section className="min-h-screen flex items-center justify-center px-4">
            <motion.div
                variants={staggerContainer}
                initial="hidden"
                animate="show"
                className="text-center max-w-4xl"
            >
                <motion.h1
                    variants={fadeInUp}
                    className="text-5xl md:text-7xl font-bold text-white mb-6"
                >
                    AI-Powered Lead Generation
                </motion.h1>
                
                <motion.p
                    variants={fadeInUp}
                    className="text-xl text-gray-400 mb-8"
                >
                    Find high-quality leads on LinkedIn and Google Maps
                    with AI qualification and scoring.
                </motion.p>
                
                <motion.div variants={fadeInUp} className="flex gap-4 justify-center">
                    <a
                        href="/login"
                        className="btn-neon px-8 py-3 text-white font-medium rounded-lg"
                    >
                        Get Started Free
                    </a>
                    <a
                        href="/pricing"
                        className="px-8 py-3 text-white font-medium rounded-lg border border-white/20 hover:bg-white/5"
                    >
                        View Pricing
                    </a>
                </motion.div>
            </motion.div>
        </section>
    )
}
```

### Features.tsx

**Purpose:** Feature cards section.

```tsx
"use client"

import { motion } from "framer-motion"
import { fadeInUp, staggerContainer } from "@/lib/animations"

const features = [
    {
        icon: "🔍",
        title: "Smart Search",
        description: "Find leads on LinkedIn and Google Maps with AI-powered search"
    },
    {
        icon: "🤖",
        title: "AI Qualification",
        description: "Automatic lead scoring across 6 dimensions"
    },
    {
        icon: "📊",
        title: "Lead Management",
        description: "Track, filter, and manage all your leads in one place"
    },
    {
        icon: "✍️",
        title: "AI Pitches",
        description: "Generate personalized outreach pitches automatically"
    },
    {
        icon: "📈",
        title: "Analytics",
        description: "Track your pipeline and conversion rates"
    },
    {
        icon: "🔒",
        title: "Secure",
        description: "Enterprise-grade security with Supabase RLS"
    }
]

export function Features() {
    return (
        <section className="py-20 px-4">
            <motion.div
                variants={staggerContainer}
                initial="hidden"
                whileInView="show"
                viewport={{ once: true }}
                className="max-w-6xl mx-auto"
            >
                <motion.h2
                    variants={fadeInUp}
                    className="text-4xl font-bold text-white text-center mb-12"
                >
                    Everything You Need
                </motion.h2>
                
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {features.map((feature, i) => (
                        <motion.div
                            key={i}
                            variants={fadeInUp}
                            className="glass-card p-6"
                        >
                            <span className="text-4xl mb-4 block">{feature.icon}</span>
                            <h3 className="text-xl font-medium text-white mb-2">
                                {feature.title}
                            </h3>
                            <p className="text-gray-400">{feature.description}</p>
                        </motion.div>
                    ))}
                </div>
            </motion.div>
        </section>
    )
}
```
