"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Progress } from "@/components/ui/progress"
import {
  Search, Linkedin, ExternalLink, Loader2, Star, Mail,
  MapPin, MessageSquare, ThumbsUp, Trash2, StickyNote, Clock,
  Users, TrendingUp, Sparkles
} from "lucide-react"
import api from "@/lib/api"

interface LinkedInLead {
  id: string
  full_name: string
  headline: string
  company: string
  location: string
  linkedin_url: string
  post_url: string
  post_text: string
  posted_at: string | null
  engagement_likes: number
  engagement_comments: number
  email: string
  profile_picture_url: string
  connections_count: number
  user_status: string
  is_favorite: boolean
  user_notes: string
  search_id: string | null
  created_at: string
}

interface SearchRow {
  id: string
  query: string
  enrich_emails: boolean
  max_results: number
  status: string
  progress_percent: number
  message: string
  total_results: number
  emails_found: number
  error_message: string | null
  created_at: string
  completed_at: string | null
}

const STATUS_OPTIONS = ["new", "contacted", "replied", "converted", "lost"] as const
type LeadStatus = (typeof STATUS_OPTIONS)[number]

function initials(name: string) {
  return name.split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase()
}

function timeAgo(iso: string | null | undefined) {
  if (!iso) return ""
  const date = new Date(iso)
  const diff = (Date.now() - date.getTime()) / 1000
  if (diff < 60) return "just now"
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`
  return date.toLocaleDateString()
}

function statusColor(status: string) {
  switch (status) {
    case "completed": return "bg-emerald/10 text-emerald border-emerald/30"
    case "running": return "bg-amber/10 text-amber border-amber/30"
    case "failed": return "bg-red-500/10 text-red-400 border-red-500/30"
    case "cancelled": return "bg-zinc-500/10 text-zinc-400 border-zinc-500/30"
    default: return "bg-ice/10 text-ice/60 border-ice/20"
  }
}

function statusLabel(status: string) {
  switch (status) {
    case "completed": return "Completed"
    case "running": return "Running"
    case "queued": return "Queued"
    case "failed": return "Failed"
    case "cancelled": return "Cancelled"
    default: return status
  }
}

interface LeadCardProps {
  lead: LinkedInLead
  onUpdate: (id: string, patch: Partial<LinkedInLead>) => Promise<void>
  onDelete: (id: string) => Promise<void>
}

function LeadCard({ lead, onUpdate, onDelete }: LeadCardProps) {
  const [savingNotes, setSavingNotes] = useState(false)
  const [notesOpen, setNotesOpen] = useState(false)
  const [notes, setNotes] = useState(lead.user_notes || "")
  const [deleting, setDeleting] = useState(false)

  const saveNotes = async () => {
    setSavingNotes(true)
    try {
      await onUpdate(lead.id, { user_notes: notes })
      setNotesOpen(false)
    } finally {
      setSavingNotes(false)
    }
  }

  return (
    <Card className="bg-ocean border-ocean/20 hover:border-amber/20 transition">
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          {lead.profile_picture_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={lead.profile_picture_url}
              alt={lead.full_name}
              className="w-12 h-12 rounded-full object-cover flex-shrink-0 bg-white/10"
            />
          ) : (
            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-primary to-brand-accent flex items-center justify-center font-bold text-navy flex-shrink-0">
              {initials(lead.full_name)}
            </div>
          )}

          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-semibold truncate">{lead.full_name || "Unknown"}</h3>
              <button
                onClick={() => onUpdate(lead.id, { is_favorite: !lead.is_favorite })}
                className={`transition ${lead.is_favorite ? "text-amber" : "text-ice/40 hover:text-amber"}`}
                aria-label="Toggle favorite"
              >
                <Star className={`w-4 h-4 ${lead.is_favorite ? "fill-current" : ""}`} />
              </button>
              {lead.email && (
                <Badge variant="outline" className="border-emerald/40 text-emerald text-xs gap-1">
                  <Mail className="w-3 h-3" /> {lead.email}
                </Badge>
              )}
              {lead.posted_at && (
                <span className="flex items-center gap-1 text-xs text-ice/40">
                  <Clock className="w-3 h-3" /> posted {timeAgo(lead.posted_at)}
                </span>
              )}
            </div>

            {lead.headline && (
              <p className="text-sm text-ice/70 line-clamp-2 mt-0.5">{lead.headline}</p>
            )}

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-xs text-ice/50">
              {lead.location && (
                <span className="flex items-center gap-1">
                  <MapPin className="w-3 h-3" /> {lead.location}
                </span>
              )}
              {lead.company && (
                <span className="flex items-center gap-1">
                  <Users className="w-3 h-3" /> {lead.company}
                </span>
              )}
              {lead.connections_count > 0 && (
                <span className="flex items-center gap-1">
                  <Users className="w-3 h-3" /> {lead.connections_count} connections
                </span>
              )}
              {lead.engagement_likes > 0 && (
                <span className="flex items-center gap-1">
                  <ThumbsUp className="w-3 h-3" /> {lead.engagement_likes}
                </span>
              )}
              {lead.engagement_comments > 0 && (
                <span className="flex items-center gap-1">
                  <MessageSquare className="w-3 h-3" /> {lead.engagement_comments}
                </span>
              )}
            </div>

            {lead.post_text && (
              <p className="text-sm text-ice/60 line-clamp-3 mt-2 border-l-2 border-primary/40 pl-3 italic">
                "{lead.post_text}"
              </p>
            )}

            <div className="flex flex-wrap items-center gap-2 mt-3">
              <select
                value={lead.user_status}
                onChange={(e) => onUpdate(lead.id, { user_status: e.target.value as LeadStatus })}
                className="bg-white/5 border border-ocean/20 rounded-md px-2 py-1 text-xs text-ice/80 focus:outline-none"
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s} className="bg-[#06231F]">
                    {s.charAt(0).toUpperCase() + s.slice(1)}
                  </option>
                ))}
              </select>
              <button
                onClick={() => { setNotes(lead.user_notes || ""); setNotesOpen((v) => !v) }}
                className="flex items-center gap-1 text-xs text-ice/60 hover:text-ice px-2 py-1 rounded-md hover:bg-white/5"
              >
                <StickyNote className="w-3.5 h-3.5" /> Notes
              </button>
              {lead.linkedin_url && (
                <a
                  href={lead.linkedin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-ice/60 hover:text-amber px-2 py-1 rounded-md hover:bg-white/5"
                >
                  <Linkedin className="w-3.5 h-3.5" /> Profile
                </a>
              )}
              {lead.post_url && (
                <a
                  href={lead.post_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-xs text-ice/60 hover:text-amber px-2 py-1 rounded-md hover:bg-white/5"
                >
                  <ExternalLink className="w-3.5 h-3.5" /> View Post
                </a>
              )}
              <button
                onClick={async () => {
                  setDeleting(true)
                  try { await onDelete(lead.id) } finally { setDeleting(false) }
                }}
                disabled={deleting}
                className="flex items-center gap-1 text-xs text-red-400/70 hover:text-red-400 px-2 py-1 rounded-md hover:bg-red-500/10 ml-auto"
              >
                <Trash2 className="w-3.5 h-3.5" /> Delete
              </button>
            </div>

            {notesOpen && (
              <div className="mt-3">
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Add notes about this lead..."
                  rows={2}
                  className="w-full bg-white/5 border border-ocean/20 rounded-md px-3 py-2 text-sm text-ice/80 placeholder:text-ice/30 focus:outline-none focus:border-amber/40"
                />
                <div className="flex justify-end gap-2 mt-2">
                  <Button variant="outline" size="sm" className="border-ocean/20 text-ice/60" onClick={() => setNotesOpen(false)}>
                    Cancel
                  </Button>
                  <Button size="sm" className="btn-gradient-cyan text-navy" onClick={saveNotes} disabled={savingNotes}>
                    {savingNotes ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : null} Save
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default function FinderPage() {
  const [tab, setTab] = useState("finder")
  const [query, setQuery] = useState("")
  const [maxResults, setMaxResults] = useState(20)
  const [enrichEmails, setEnrichEmails] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState("")

  const [activeSearch, setActiveSearch] = useState<SearchRow | null>(null)
  const [results, setResults] = useState<LinkedInLead[]>([])
  const [history, setHistory] = useState<SearchRow[]>([])
  const [historyLoaded, setHistoryLoaded] = useState(false)

  const [savedLeads, setSavedLeads] = useState<LinkedInLead[]>([])
  const [savedFilter, setSavedFilter] = useState<string>("")
  const [savedOnlyFav, setSavedOnlyFav] = useState(false)
  const [savedName, setSavedName] = useState("")
  const [savedPage, setSavedPage] = useState(1)
  const [savedTotal, setSavedTotal] = useState(0)
  const [savedLoading, setSavedLoading] = useState(false)
  const [viewingSearch, setViewingSearch] = useState<SearchRow | null>(null)

  const loadHistory = useCallback(async () => {
    try {
      const res = await api.get("/api/linkedin/searches?page=1&per_page=20")
      setHistory(res.data.items || [])
      setHistoryLoaded(true)
    } catch {
      /* ignore */
    }
  }, [])

  const loadResults = useCallback(async (searchId: string) => {
    try {
      const res = await api.get(`/api/linkedin/searches/${searchId}/results?page=1&per_page=100`)
      setResults(res.data.items || [])
      return res.data.items || []
    } catch {
      return []
    }
  }, [])

  const loadSaved = useCallback(async (page = 1, filter = savedFilter, fav = savedOnlyFav, name = savedName) => {
    setSavedLoading(true)
    try {
      const params: string[] = [`page=${page}`, "per_page=50"]
      if (filter) params.push(`user_status=${filter}`)
      if (fav) params.push("is_favorite=true")
      if (name.trim()) params.push(`search=${encodeURIComponent(name.trim())}`)
      const res = await api.get(`/api/linkedin/leads?${params.join("&")}`)
      const items: LinkedInLead[] = res.data.items || []
      setSavedLeads(page === 1 ? items : (prev) => [...prev, ...items])
      setSavedTotal(res.data.total || 0)
      setSavedPage(page)
    } catch {
      /* ignore */
    } finally {
      setSavedLoading(false)
    }
  }, [savedFilter, savedOnlyFav, savedName])

  useEffect(() => {
    if (tab === "saved") {
      setSavedLeads([])
      setSavedPage(1)
      loadSaved(1)
    }
  }, [tab, loadSaved])

  useEffect(() => {
    if (!historyLoaded) loadHistory()
  }, [historyLoaded, loadHistory])

  useEffect(() => {
    if (!activeSearch) return
    const active = activeSearch.status === "queued" || activeSearch.status === "running"
    if (!active) return
    const id = setInterval(async () => {
      try {
        const res = await api.get(`/api/linkedin/searches/${activeSearch.id}/status`)
        const s = res.data as SearchRow
        setActiveSearch(s)
        if (s.status === "completed" || s.status === "failed") {
          if (s.status === "completed") await loadResults(s.id)
          await loadHistory()
        }
      } catch {
        /* ignore */
      }
    }, 3000)
    return () => clearInterval(id)
  }, [activeSearch?.id, activeSearch?.status, loadHistory, loadResults])

  const startSearch = async () => {
    if (!query.trim()) {
      setError("Please enter what people are looking for.")
      return
    }
    setStarting(true)
    setError("")
    setResults([])
    setViewingSearch(null)
    try {
      const res = await api.post("/api/linkedin/searches", {
        query: query.trim(),
        enrich_emails: enrichEmails,
        max_results: maxResults,
      })
      setActiveSearch(res.data)
      await loadHistory()
    } catch (e: unknown) {
      const status = (e as { response?: { status?: number; data?: unknown } })?.response?.status
      const detail = (e as { response?: { data?: unknown } })?.response?.data as
        | { message?: string; detail?: unknown }
        | undefined
      const msg =
        (typeof detail?.message === "string" && detail.message) ||
        (typeof detail?.detail === "string" && detail.detail) ||
        "Search failed. Please try again."
      if (status === 429) setError(`Daily search limit reached. ${msg}`)
      else setError(String(msg))
    } finally {
      setStarting(false)
    }
  }

  const viewSearch = async (search: SearchRow) => {
    setViewingSearch(search)
    setTab("finder")
    await loadResults(search.id)
  }

  const updateLead = useCallback(async (id: string, patch: Partial<LinkedInLead>) => {
    await api.patch(`/api/linkedin/leads/${id}`, patch)
    setResults((prev) => prev.map((l) => (l.id === id ? { ...l, ...patch } : l)))
    setSavedLeads((prev) => prev.map((l) => (l.id === id ? { ...l, ...patch } : l)))
  }, [])

  const deleteLead = useCallback(async (id: string) => {
    await api.delete(`/api/linkedin/leads/${id}`)
    setResults((prev) => prev.filter((l) => l.id !== id))
    setSavedLeads((prev) => prev.filter((l) => l.id !== id))
  }, [])

  const isRunning = activeSearch && (activeSearch.status === "queued" || activeSearch.status === "running")

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">LinkedIn Intent Finder</h1>
        <p className="text-ice/60 text-sm mt-1">
          Find people who <span className="text-amber">posted on LinkedIn</span> that they need a service like yours — then
          contact them directly.
        </p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="bg-white/5 border border-ocean/20">
          <TabsTrigger value="finder" className="gap-1.5">
            <Search className="w-3.5 h-3.5" /> Intent Finder
          </TabsTrigger>
          <TabsTrigger value="saved" className="gap-1.5">
            <Users className="w-3.5 h-3.5" /> Saved Leads
            {savedTotal > 0 && <Badge className="bg-amber/20 text-amber ml-1">{savedTotal}</Badge>}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="finder" className="space-y-6">
          {/* Search Form */}
          <Card className="bg-ocean border-ocean/20">
            <CardContent className="p-6">
              <div className="flex items-start gap-2 mb-3">
                <Sparkles className="w-4 h-4 text-amber mt-0.5 flex-shrink-0" />
                <p className="text-sm text-ice/60">
                  Type the need people are posting about. Example: <em>I need SEO</em>, <em>website developer</em>,{" "}
                  <em>logo design</em>.
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
                <div className="sm:col-span-2">
                  <label className="text-xs text-ice/60 mb-1.5 block">What are people asking for?</label>
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && startSearch()}
                    placeholder="e.g. I need SEO, website developer, logo design..."
                    className="bg-white/5 border-ocean/20"
                  />
                </div>
                <div>
                  <label className="text-xs text-ice/60 mb-1.5 block">Max leads</label>
                  <select
                    value={maxResults}
                    onChange={(e) => setMaxResults(Number(e.target.value))}
                    className="w-full bg-white/5 border border-ocean/20 rounded-md px-3 py-2 text-sm text-ice/80 focus:outline-none"
                  >
                    <option value={10} className="bg-[#06231F]">10 leads</option>
                    <option value={20} className="bg-[#06231F]">20 leads</option>
                    <option value={30} className="bg-[#06231F]">30 leads</option>
                    <option value={50} className="bg-[#06231F]">50 leads</option>
                  </select>
                </div>
              </div>
              <div className="flex items-center gap-2 mb-4">
                <Switch checked={enrichEmails} onCheckedChange={setEnrichEmails} />
                <label className="text-sm text-ice/70 cursor-pointer" onClick={() => setEnrichEmails((v) => !v)}>
                  Try to find their email addresses
                </label>
              </div>
              <div className="flex gap-2 items-center">
                <Button onClick={startSearch} disabled={starting || !!isRunning} className="btn-gradient-cyan text-navy font-semibold">
                  {starting ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Search className="w-4 h-4 mr-2" />}
                  {isRunning ? "Searching..." : "Find Intent Leads"}
                </Button>
                {error && <p className="text-red-400 text-sm">{error}</p>}
              </div>
            </CardContent>
          </Card>

          {/* Progress */}
          {activeSearch && (
            <Card className="bg-ocean border-ocean/20">
              <CardContent className="p-5">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Badge className={statusColor(activeSearch.status)}>{statusLabel(activeSearch.status)}</Badge>
                    <span className="text-sm text-ice/70">
                      {activeSearch.query}
                      {activeSearch.enrich_emails ? " • emails on" : ""}
                    </span>
                  </div>
                  {activeSearch.total_results > 0 && (
                    <span className="text-sm text-ice/70">
                      <TrendingUp className="w-3.5 h-3.5 inline mr-1" />
                      {activeSearch.total_results} leads
                      {activeSearch.emails_found > 0 ? `, ${activeSearch.emails_found} emails` : ""}
                    </span>
                  )}
                </div>
                {isRunning && (
                  <>
                    <Progress value={activeSearch.progress_percent} className="h-2 [&>div]:bg-brand-accent" />
                    <p className="text-xs text-ice/50 mt-2">{activeSearch.message}</p>
                  </>
                )}
                {!isRunning && activeSearch.message && activeSearch.status !== "completed" && (
                  <p className="text-xs text-ice/50 mt-2">{activeSearch.message}</p>
                )}
              </CardContent>
            </Card>
          )}

          {/* Results */}
          {results.length === 0 && !isRunning && !starting && !viewingSearch && (
            <div className="text-center py-16">
              <Search className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
              <p className="text-ice/60">Search LinkedIn posts to find buyers</p>
              <p className="text-ice/40 text-sm mt-1">We filter out recruiters and hiring posts automatically</p>
            </div>
          )}

          {results.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <p className="text-sm text-ice/60">
                  {results.length} intent lead{results.length === 1 ? "" : "s"}
                  {viewingSearch ? ` from "${viewingSearch.query}"` : ""}
                </p>
              </div>
              {results.map((lead) => (
                <LeadCard key={lead.id} lead={lead} onUpdate={updateLead} onDelete={deleteLead} />
              ))}
            </div>
          )}

          {/* History */}
          {history.length > 0 && (
            <Card className="bg-ocean border-ocean/20">
              <CardContent className="p-5">
                <h3 className="font-semibold mb-3">Recent Searches</h3>
                <div className="space-y-2">
                  {history.map((s) => (
                    <button
                      key={s.id}
                      onClick={() => viewSearch(s)}
                      className="w-full flex items-center justify-between gap-3 p-3 rounded-lg bg-white/[0.03] hover:bg-white/[0.06] transition text-left"
                    >
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{s.query}</p>
                        <p className="text-xs text-ice/50 mt-0.5">
                          {timeAgo(s.created_at)} • {s.total_results} leads
                          {s.emails_found > 0 ? ` • ${s.emails_found} emails` : ""}
                        </p>
                      </div>
                      <Badge className={statusColor(s.status)}>{statusLabel(s.status)}</Badge>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="saved" className="space-y-4">
          <Card className="bg-ocean border-ocean/20">
            <CardContent className="p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Input
                  value={savedName}
                  onChange={(e) => { setSavedName(e.target.value); loadSaved(1, savedFilter, savedOnlyFav, e.target.value) }}
                  placeholder="Search by name..."
                  className="bg-white/5 border-ocean/20 max-w-[220px]"
                />
                <div className="flex flex-wrap gap-1.5">
                  {["", ...STATUS_OPTIONS].map((s) => (
                    <button
                      key={s || "all"}
                      onClick={() => { setSavedFilter(s); loadSaved(1, s, savedOnlyFav, savedName) }}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${
                        savedFilter === s
                          ? "bg-brand-accent text-navy"
                          : "bg-white/5 text-ice/60 hover:bg-white/10"
                      }`}
                    >
                      {s ? s.charAt(0).toUpperCase() + s.slice(1) : "All"}
                    </button>
                  ))}
                  <button
                    onClick={() => { setSavedOnlyFav((v) => !v); loadSaved(1, savedFilter, !savedOnlyFav, savedName) }}
                    className={`px-3 py-1.5 rounded-md text-xs font-medium transition flex items-center gap-1 ${
                      savedOnlyFav ? "bg-amber text-navy" : "bg-white/5 text-ice/60 hover:bg-white/10"
                    }`}
                  >
                    <Star className={`w-3 h-3 ${savedOnlyFav ? "fill-current" : ""}`} /> Favorites
                  </button>
                </div>
              </div>
            </CardContent>
          </Card>

          {savedLoading && savedLeads.length === 0 && (
            <div className="text-center py-12">
              <Loader2 className="w-10 h-10 mx-auto mb-3 text-amber animate-spin" />
              <p className="text-ice/60">Loading leads...</p>
            </div>
          )}

          {!savedLoading && savedLeads.length === 0 && (
            <div className="text-center py-16">
              <Users className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
              <p className="text-ice/60">No saved leads yet</p>
              <p className="text-ice/40 text-sm mt-1">Run an intent search to start building your list</p>
            </div>
          )}

          {savedLeads.length > 0 && (
            <div className="space-y-3">
              {savedLeads.map((lead) => (
                <LeadCard key={lead.id} lead={lead} onUpdate={updateLead} onDelete={deleteLead} />
              ))}
              {savedLeads.length < savedTotal && (
                <div className="text-center pt-2">
                  <Button variant="outline" className="border-ocean/20 text-ice/70" onClick={() => loadSaved(savedPage + 1)} disabled={savedLoading}>
                    {savedLoading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : null}
                    Load more ({savedTotal - savedLeads.length} remaining)
                  </Button>
                </div>
              )}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}