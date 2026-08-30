"use client"

import { useState, useRef, useEffect } from "react"
import { Card } from "@/components/ui/card"
import { Zap, Send, Loader2, Check, ArrowLeft, Bot, User, History } from "lucide-react"
import Link from "next/link"
import api from "@/lib/api"
import PlanGuard from "@/components/dashboard/PlanGuard"

interface Message {
  role: "user" | "assistant"
  content: string
  timestamp: Date
}

interface Lead {
  name: string
  headline: string
  company: string
  location: string
  linkedin_url: string
  post_url: string
  score: number
  tier: string
  lead_type: string
  work_type: string
  evidence_strength: string
  outreach_competition: string
  buying_intent: number
  requirement_clarity: number
  decision_maker_likelihood: number
  urgency: number
  commercial_potential: number
  reason: string
  outreach_angle: string
  post_content: string
  engagement: { likes: number; comments: number }
}

export default function HyperAgentChat() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: `👋 **Welcome to HyperAgent!**

I'm your AI-powered lead generation assistant. I'll help you find high-quality B2B leads from LinkedIn.

Tell me about your ideal customers:
- What do you sell/serve?
- Who are your ideal customers?
- What location are you targeting?

For example: *"I'm a web developer looking for SaaS startups in San Francisco that need a new website"*

Or be direct: *"Find 20 CTOs of SaaS companies in New York"*

I'll understand your needs, confirm the details, then scrape LinkedIn and qualify the best leads for you.`,
      timestamp: new Date(),
    },
  ])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [searchStep, setSearchStep] = useState<string | null>(null)
  const [leads, setLeads] = useState<Lead[]>([])
  const [searchId, setSearchId] = useState<string | null>(null)
  const [leadTypePrompt, setLeadTypePrompt] = useState<any>(null)
  const [selectedLeadTypes, setSelectedLeadTypes] = useState<string[]>([])
  const [servicesPrompt, setServicesPrompt] = useState<any>(null)
  const [selectedServices, setSelectedServices] = useState<string[]>([])
  const [customService, setCustomService] = useState("")
  const [locationPrompt, setLocationPrompt] = useState<any>(null)
  const [selectedLocations, setSelectedLocations] = useState<string[]>([])
  const [leadCountPrompt, setLeadCountPrompt] = useState<any>(null)
  const [selectedLeadCount, setSelectedLeadCount] = useState<string>("")
  const [pendingContext, setPendingContext] = useState<any>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [history, setHistory] = useState<any[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, leads, searchStep])

  const loadHistory = async () => {
    setShowHistory(true)
    setHistoryLoading(true)
    try {
      const res = await api.get("/api/searches", { params: { per_page: 30 } })
      const items = res.data?.items || []
      setHistory(items.filter((s: any) => s.source === "hyper_agent"))
    } catch {
      setHistory([])
    } finally {
      setHistoryLoading(false)
    }
  }

  const loadHistorySearch = async (id: string) => {
    try {
      setLoading(true)
      setSearchStep("📂 Loading previous search...")
      const res = await api.get(`/api/hyper-agent/results/${id}`)
      const search = res.data?.search
      const rawLeads = res.data?.leads || []
      const normLeads = rawLeads.map((l: any) => {
        const score = l.ai_confidence_score != null ? Math.round(l.ai_confidence_score * 100) : 0
        const workMatch = (l.headline || "").match(/^(🌍 Remote|📄 Contract|⏱️ Part-time|🏢 On-site)\s*—?\s*(.*)$/)
        const workMap: Record<string, string> = {
          "🌍 Remote": "remote",
          "📄 Contract": "contract",
          "⏱️ Part-time": "part_time",
          "🏢 On-site": "full_time_onsite",
        }
        return {
          id: l.id,
          name: l.business_name || "Unknown",
          headline: workMatch ? workMatch[2] : (l.headline || ""),
          company: l.category || "",
          location: l.full_address || "",
          linkedin_url: l.linkedin_url || "",
          post_url: l.post_url || "",
          score,
          tier: score >= 85 ? "HOT" : "WARM",
          lead_type: l.post_type || "buyer",
          work_type: workMatch ? workMap[workMatch[1]] : "unknown",
          reason: l.ai_reason || "",
          outreach_angle: l.ai_pitch || "",
          post_content: l.post_text || "",
        }
      })
      setLeads(normLeads)
      setSearchId(id)
      setSearchStep(null)
      const msg: Message = {
        role: "assistant",
        content: `📂 **Loaded previous search** — ${search?.niche || "Search"} (${search?.location || "—"}). Found **${normLeads.length}** leads.`,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, msg])
    } catch (e: any) {
      setSearchStep(null)
      const msg: Message = {
        role: "assistant",
        content: `❌ Failed to load search: ${e?.response?.data?.detail || e?.message || "unknown error"}`,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, msg])
    } finally {
      setLoading(false)
    }
  }

  const sendMessage = async (overrideMsg?: string) => {
    const content = overrideMsg !== undefined ? overrideMsg : input
    if (!content.trim() || loading) return

    const userMessage: Message = {
      role: "user",
      content,
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput("")
    setLoading(true)

    try {
      const history = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }))

      const res = await api.post("/api/hyper-agent/chat", {
        message: content,
        history,
        lead_types: selectedLeadTypes.length > 0 ? selectedLeadTypes : [],
      })

      if (res.status !== 200) {
        throw new Error("Failed to get response")
      }

      const data = res.data

      const assistantMessage: Message = {
        role: "assistant",
        content: data.response,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, assistantMessage])

      // Lead-type question → show checkbox modal
      if (data.action === "lead_types") {
        setLeadTypePrompt(data.data || { options: [] })
        setPendingContext(data.data?.context || null)
        setSelectedLeadTypes([])
        return
      }

      // Services question → show checkbox modal
      if (data.action === "services") {
        setServicesPrompt(data.data || { options: [] })
        setPendingContext(data.data?.context || null)
        setSelectedServices([])
        setCustomService("")
        return
      }

      // Location question → show checkbox modal
      if (data.action === "location") {
        setLocationPrompt(data.data || { options: [] })
        setPendingContext(data.data?.context || null)
        setSelectedLocations([])
        return
      }

      // Lead count question → show radio modal
      if (data.action === "lead_count") {
        setLeadCountPrompt(data.data || { options: [] })
        setPendingContext(data.data?.context || null)
        setSelectedLeadCount("")
        return
      }

      // If action is scrape, execute the search with progress steps
      if (data.action === "scrape" && data.data) {
        setLoading(true)

        setSearchStep("🔍 Connecting to LinkedIn...")
        await new Promise((r) => setTimeout(r, 800))

        try {
          // Queue the scrape job — returns instantly with a search_id
          const contextData = { ...data.data }
          if (selectedLeadTypes.length > 0) {
            contextData.lead_types = selectedLeadTypes
          }
          if (selectedLeadCount) {
            contextData.count = parseInt(selectedLeadCount, 10) || 20
          }
          if (selectedLocations.length > 0) {
            contextData.locations = selectedLocations.join(",")
          }
          const scrapeRes = await api.post("/api/hyper-agent/scrape", { context: contextData })

          if (scrapeRes.status !== 200) {
            throw new Error("Failed to start search")
          }

          const { search_id } = scrapeRes.data

          // Poll results until the background job completes
          let status = "queued"
          let pollData: any = null
          for (let attempt = 0; attempt < 100; attempt++) {
            await new Promise((r) => setTimeout(r, 3000))

            const res = await api.get(`/api/hyper-agent/results/${search_id}`)
            if (res.status !== 200) continue

            pollData = res.data
            status = pollData?.search?.status || "queued"

            if (status === "scraping") setSearchStep("🔎 Searching for matching posts and profiles...")
            else if (status === "qualifying") setSearchStep("📊 Analyzing and scoring leads with AI...")
            else if (status === "completed" || status === "failed") break
          }

          if (status === "failed") {
            const errMsg = pollData?.search?.message || "Search failed"
            setSearchStep(null)
            const errMessage: Message = {
              role: "assistant",
              content: `❌ ${errMsg}`,
              timestamp: new Date(),
            }
            setMessages((prev) => [...prev, errMessage])
            return
          }

          setSearchStep("✅ Qualifying top leads...")
          await new Promise((r) => setTimeout(r, 500))

          // Normalize DB rows to the display format used by the table below
          const leads = (pollData?.leads || []).map((l: any) => {
            const score = l.ai_confidence_score != null ? Math.round(l.ai_confidence_score * 100) : 0
            const workMatch = (l.headline || "").match(/^(🌍 Remote|📄 Contract|⏱️ Part-time|🏢 On-site)\s*—?\s*(.*)$/)
            const workMap: Record<string, string> = {
              "🌍 Remote": "remote",
              "📄 Contract": "contract",
              "⏱️ Part-time": "part_time",
              "🏢 On-site": "full_time_onsite",
            }
            return {
              id: l.id,
              name: l.business_name || "Unknown",
              headline: workMatch ? workMatch[2] : (l.headline || ""),
              company: l.category || "",
              location: l.full_address || "",
              linkedin_url: l.linkedin_url || "",
              post_url: l.post_url || "",
              score,
              tier: score >= 75 ? "HOT" : "WARM",
              lead_type: l.post_type || "buyer",
              work_type: workMatch ? workMap[workMatch[1]] : "unknown",
              reason: l.ai_reason || "",
              outreach_angle: l.ai_pitch || "",
              post_content: l.post_text || "",
            }
          })
          setLeads(leads)
          setSearchId(search_id)
          setSearchStep(null)

          const resultMessage: Message = {
            role: "assistant",
            content: `✅ **Search Complete!**

Found **${leads.length}** qualified leads.

Here are your top leads (scored 0-100):`,
            timestamp: new Date(),
          }
          setMessages((prev) => [...prev, resultMessage])
        } catch (scrapeErr: any) {
          setSearchStep(null)
          throw scrapeErr
        }
      }
    } catch (err: any) {
      setSearchStep(null)
      const errorMessage = err?.response?.data?.detail || err?.message || "An error occurred"
      const msg: Message = {
        role: "assistant",
        content: `❌ Error: ${errorMessage}. Please try again.`,
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, msg])
    } finally {
      setLoading(false)
      setSearchStep(null)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <PlanGuard>
    <div className="h-[calc(100vh-2rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs text-steel hover:text-offwhite hover:bg-ocean/30 transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Back
          </Link>
          <div className="bg-violet/20 rounded-lg p-2">
            <Zap className="w-5 h-5 text-violet" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-offwhite">HyperAgent</h1>
            <p className="text-xs text-ice/50">AI-Powered Lead Discovery</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={loadHistory}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-ice/70 hover:bg-ocean/30 hover:text-offwhite border border-steel/20 transition-colors"
          >
            <History className="w-3.5 h-3.5" />
            History
          </button>
          {searchId && (
            <Link
              href="/dashboard/leads"
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-violet hover:bg-violet/10 border border-violet/30 transition-colors"
            >
              View All Leads →
            </Link>
          )}
        </div>
      </div>

      {/* History Panel */}
      {showHistory && (
        <div className="border border-steel/20 bg-navy/80 rounded-xl p-4 mb-4 flex-shrink-0 max-h-72 overflow-y-auto">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-offwhite">📂 Previous Searches</h3>
            <button onClick={() => setShowHistory(false)} className="text-ice/50 hover:text-offwhite text-xs">✕ Close</button>
          </div>
          {historyLoading ? (
            <div className="text-sm text-steel">Loading history...</div>
          ) : history.length === 0 ? (
            <div className="text-sm text-steel">No previous HyperAgent searches yet.</div>
          ) : (
            <div className="space-y-2">
              {history.map((s) => (
                <button
                  key={s.id}
                  onClick={() => { setShowHistory(false); loadHistorySearch(s.id) }}
                  className="w-full flex items-center justify-between gap-3 bg-ocean/40 hover:bg-ocean/70 border border-steel/15 rounded-lg px-3 py-2 text-left transition-colors"
                >
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-offwhite truncate">{s.niche}</p>
                    <p className="text-[10px] text-ice/50 truncate">{s.location} • {new Date(s.created_at).toLocaleDateString()}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.status === 'completed' ? 'bg-emerald/20 text-emerald' : s.status === 'failed' ? 'bg-rose/20 text-rose-400' : 'bg-amber/20 text-amber'}`}>
                      {s.status}
                    </span>
                    <span className="text-[10px] text-ice/60">{s.total_results || 0} leads</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Chat Area */}
      <Card className="flex-1 bg-ocean border-ocean/20 overflow-hidden flex flex-col">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map((msg, i) => (
            <div
              key={i}
              className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {msg.role === "assistant" && (
                <div className="w-8 h-8 rounded-lg bg-violet/20 flex items-center justify-center flex-shrink-0">
                  <Bot className="w-4 h-4 text-violet" />
                </div>
              )}
              <div
                className={`max-w-[70%] rounded-xl px-4 py-3 ${
                  msg.role === "user"
                    ? "bg-violet text-white"
                    : "bg-navy border border-steel/20 text-ice"
                }`}
              >
                <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
              </div>
              {msg.role === "user" && (
                <div className="w-8 h-8 rounded-lg bg-steel/20 flex items-center justify-center flex-shrink-0">
                  <User className="w-4 h-4 text-steel" />
                </div>
              )}
            </div>
          ))}

          {/* Loading indicator */}
          {loading && (
            <div className="flex gap-3 justify-start">
              <div className="w-8 h-8 rounded-lg bg-violet/20 flex items-center justify-center flex-shrink-0">
                <Bot className="w-4 h-4 text-violet" />
              </div>
              <div className="bg-navy border border-steel/20 rounded-xl px-4 py-3">
                {searchStep ? (
                  <div className="flex items-center gap-2 text-violet">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm font-medium">{searchStep}</span>
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-steel">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span className="text-sm">Thinking...</span>
                  </div>
                )}
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Leads Table */}
        {leads.length > 0 && (
          <div className="border-t border-steel/20 p-4 max-h-80 overflow-y-auto">
            <h3 className="text-sm font-semibold text-offwhite mb-3">
              🎯 Qualified Leads ({leads.length})
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-steel border-b border-steel/20">
                    <th className="text-left py-2 px-2">Name</th>
                    <th className="text-left py-2 px-2">Company</th>
                    <th className="text-left py-2 px-2">Headline</th>
                    <th className="text-left py-2 px-2">Score</th>
                    <th className="text-left py-2 px-2">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.slice(0, 10).map((lead, i) => (
                    <tr key={i} className="border-b border-steel/10 hover:bg-navy/50">
                      <td className="py-2 px-2 text-offwhite font-medium">
                        {lead.name}
                        <div className="flex gap-1 mt-0.5 flex-wrap">
                          {lead.tier && (
                            <span className={`text-[9px] px-1 py-0.5 rounded font-bold ${
                              lead.tier === 'HOT' ? 'bg-rose-500/20 text-rose-400' :
                              'bg-amber-500/20 text-amber-400'
                            }`}>
                              {lead.tier}
                            </span>
                          )}
                          {lead.lead_type && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-ocean/20 text-ice/60">
                              {lead.lead_type.replace(/_/g, ' ')}
                            </span>
                          )}
                          {lead.work_type && lead.work_type !== 'unknown' && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-violet/20 text-violet">
                              {lead.work_type === 'remote' ? '🌍 Remote' :
                               lead.work_type === 'contract' ? '📄 Contract' :
                               lead.work_type === 'part_time' ? '⏱️ PT' :
                               lead.work_type}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2 px-2 text-ice/70">{lead.company || "-"}</td>
                      <td className="py-2 px-2 text-ice/50 max-w-[200px] truncate">
                        {lead.headline || "-"}
                      </td>
                      <td className="py-2 px-2">
                        <span
                          className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                            lead.score >= 75
                              ? "bg-emerald/20 text-emerald"
                              : lead.score >= 40
                              ? "bg-cyan/20 text-cyan"
                              : "bg-orange/20 text-orange"
                          }`}
                        >
                          {lead.score}
                        </span>
                      </td>
                      <td className="py-2 px-2">
                        {lead.post_url && (
                          <a
                            href={lead.post_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-violet hover:underline"
                          >
                            View Post →
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {leads.length > 10 && (
              <p className="text-xs text-steel mt-2 text-center">
                Showing 10 of {leads.length} leads.{" "}
                <Link href="/dashboard/leads" className="text-violet hover:underline">
                  View all →
                </Link>
              </p>
            )}
          </div>
        )}

        {/* Input */}
        <div className="border-t border-steel/20 p-4">
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Describe your ideal lead..."
              className="flex-1 bg-navy border border-steel/20 rounded-xl px-4 py-3 text-sm text-offwhite placeholder-steel resize-none focus:outline-none focus:border-violet/50"
              rows={1}
              style={{ minHeight: "44px", maxHeight: "120px" }}
            />
            <button
              onClick={() => sendMessage()}
              disabled={!input.trim() || loading}
              className="w-10 h-10 rounded-xl bg-violet hover:bg-violet/80 disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center transition-colors"
            >
              <Send className="w-4 h-4 text-white" />
            </button>
          </div>
        </div>
      </Card>

      {/* Lead Type Checkbox Modal */}
      {leadTypePrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-navy/70 backdrop-blur-sm" onClick={() => setLeadTypePrompt(null)} />
          <div className="relative w-full max-w-md bg-ocean border border-violet/30 rounded-2xl p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <h3 className="text-lg font-bold text-offwhite mb-1">Which kind of leads would you want?</h3>
            <p className="text-xs text-ice/60 mb-4">Select one or more. This decides what we search for on LinkedIn.</p>

            <div className="space-y-2.5 mb-5">
              {(leadTypePrompt.options || []).map((opt: any) => {
                const checked = selectedLeadTypes.includes(opt.id)
                return (
                  <button
                    key={opt.id}
                    onClick={() => {
                      setSelectedLeadTypes((prev) =>
                        checked ? prev.filter((x) => x !== opt.id) : [...prev, opt.id]
                      )
                    }}
                    className={`w-full flex items-start gap-3 p-3.5 rounded-xl border transition-all text-left ${
                      checked
                        ? "border-violet/60 bg-violet/10"
                        : "border-steel/20 bg-navy/60 hover:border-steel/40"
                    }`}
                  >
                    <div className={`mt-0.5 w-4 h-4 shrink-0 rounded border flex items-center justify-center transition-colors ${
                      checked ? "bg-violet border-violet" : "border-steel/50"
                    }`}>
                      {checked && <Check className="w-3 h-3 text-white" />}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-offwhite">{opt.label}</p>
                      <p className="text-[11px] text-ice/50 mt-0.5">{opt.description}</p>
                    </div>
                  </button>
                )
              })}
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setLeadTypePrompt(null)}
                className="flex-1 py-2.5 rounded-xl text-sm font-medium text-ice/60 hover:text-offwhite border border-steel/20 hover:bg-steel/10 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (selectedLeadTypes.length === 0) {
                    setLeadTypePrompt(null)
                    return
                  }
                  const labels = selectedLeadTypes
                    .map((id) => (leadTypePrompt.options || []).find((o: any) => o.id === id)?.label || id)
                    .join(", ")
                  // Send the selection back to the agent, which will confirm + start
                  setLeadTypePrompt(null)
                  sendMessage(`I want: ${labels} (lead_types: ${selectedLeadTypes.join(",")})`)
                }}
                className="flex-1 py-2.5 rounded-xl text-sm font-bold text-white bg-violet hover:bg-violet/80 transition-colors"
              >
                Confirm & Continue
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Services Checkbox Modal */}
      {servicesPrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-navy/70 backdrop-blur-sm" onClick={() => setServicesPrompt(null)} />
          <div className="relative w-full max-w-lg bg-ocean border border-amber/30 rounded-2xl p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <h3 className="text-lg font-bold text-offwhite mb-1">🛠️ What services do you provide?</h3>
            <p className="text-xs text-ice/60 mb-4">Type ANY service — we find leads for every niche. Pick from quick options below or type your own.</p>

            {/* Custom input — always visible at top */}
            <div className="mb-4">
              <label className="block text-xs font-semibold text-amber/70 mb-1.5">Your services</label>
              <input
                type="text"
                value={customService}
                onChange={(e) => setCustomService(e.target.value)}
                placeholder="e.g. 3D animation, podcast editing, VR development, anything..."
                className="w-full px-3 py-2.5 rounded-lg bg-navy/60 border border-amber/40 text-offwhite text-sm placeholder-steel/40 focus:outline-none focus:border-amber/60"
              />
              <p className="text-[10px] text-ice/40 mt-1">Comma-separated for multiple services. Type anything — not limited to the list below.</p>
            </div>

            {/* Quick-select chips */}
            <div className="mb-5">
              <p className="text-[11px] text-ice/50 mb-2 font-medium">Quick select (adds to your list above):</p>
              <div className="flex flex-wrap gap-1.5">
                {(servicesPrompt.options || []).filter((o: any) => o.id !== "other").map((opt: any) => {
                  const active = selectedServices.includes(opt.id)
                  return (
                    <button
                      key={opt.id}
                      onClick={() => {
                        setSelectedServices((prev) =>
                          active ? prev.filter((x) => x !== opt.id) : [...prev, opt.id]
                        )
                        // Auto-append label to custom input
                        if (!active) {
                          setCustomService((prev) => {
                            const existing = prev.trim()
                            if (!existing) return opt.label
                            const parts = existing.split(",").map((s: string) => s.trim()).filter(Boolean)
                            if (parts.some((p: string) => p.toLowerCase() === opt.label.toLowerCase())) return prev
                            return existing + ", " + opt.label
                          })
                        } else {
                          // Remove label from custom input
                          setCustomService((prev) => {
                            const parts = prev.split(",").map((s: string) => s.trim()).filter(Boolean)
                            return parts
                              .filter((p: string) => p.toLowerCase() !== opt.label.toLowerCase())
                              .join(", ")
                          })
                        }
                      }}
                      className={`px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all ${
                        active
                          ? "border-amber/60 bg-amber/15 text-amber"
                          : "border-steel/20 bg-navy/40 text-ice/60 hover:border-steel/40 hover:text-ice/80"
                      }`}
                    >
                      {opt.label}
                    </button>
                  )
                })}
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setServicesPrompt(null)}
                className="flex-1 py-2.5 rounded-xl text-sm font-medium text-ice/60 hover:text-offwhite border border-steel/20 hover:bg-steel/10 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  const serviceText = customService.trim()
                  if (!serviceText) {
                    setServicesPrompt(null)
                    return
                  }
                  setServicesPrompt(null)
                  sendMessage(`I provide: ${serviceText} (services: ${serviceText})`)
                }}
                className="flex-1 py-2.5 rounded-xl text-sm font-bold text-white bg-amber hover:bg-amber/80 transition-colors"
              >
                Confirm & Continue
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Location Checkbox Modal */}
      {locationPrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-navy/70 backdrop-blur-sm" onClick={() => setLocationPrompt(null)} />
          <div className="relative w-full max-w-md bg-ocean border border-cyan/30 rounded-2xl p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <h3 className="text-lg font-bold text-offwhite mb-1">📍 Where are your buyers?</h3>
            <p className="text-xs text-ice/60 mb-4">Select one or more regions. We'll search for leads in these markets.</p>

            <div className="space-y-2.5 mb-5">
              {(locationPrompt.options || []).map((opt: any) => {
                const checked = selectedLocations.includes(opt.id)
                return (
                  <button
                    key={opt.id}
                    onClick={() => {
                      setSelectedLocations((prev) =>
                        checked ? prev.filter((x) => x !== opt.id) : [...prev, opt.id]
                      )
                    }}
                    className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${
                      checked
                        ? "border-cyan/60 bg-cyan/10"
                        : "border-steel/20 bg-navy/60 hover:border-steel/40"
                    }`}
                  >
                    <div className={`w-4 h-4 shrink-0 rounded border flex items-center justify-center transition-colors ${
                      checked ? "bg-cyan border-cyan" : "border-steel/50"
                    }`}>
                      {checked && <Check className="w-3 h-3 text-white" />}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-offwhite">{opt.label}</p>
                      {opt.countries && (
                        <p className="text-[10px] text-ice/40 mt-0.5">{opt.countries}</p>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setLocationPrompt(null)}
                className="flex-1 py-2.5 rounded-xl text-sm font-medium text-ice/60 hover:text-offwhite border border-steel/20 hover:bg-steel/10 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (selectedLocations.length === 0) {
                    setLocationPrompt(null)
                    return
                  }
                  const labels = selectedLocations
                    .map((id) => (locationPrompt.options || []).find((o: any) => o.id === id)?.label || id)
                    .join(", ")
                  setLocationPrompt(null)
                  sendMessage(`My buyers are in: ${labels} (locations: ${selectedLocations.join(",")})`)
                }}
                className="flex-1 py-2.5 rounded-xl text-sm font-bold text-white bg-cyan hover:bg-cyan/80 transition-colors"
              >
                Confirm & Continue
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Lead Count Radio Modal */}
      {leadCountPrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-navy/70 backdrop-blur-sm" onClick={() => setLeadCountPrompt(null)} />
          <div className="relative w-full max-w-md bg-ocean border border-emerald/30 rounded-2xl p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <h3 className="text-lg font-bold text-offwhite mb-1">📊 How many leads do you need?</h3>
            <p className="text-xs text-ice/60 mb-4">Pick one option. More leads = wider search but same quality.</p>

            <div className="space-y-2.5 mb-5">
              {(leadCountPrompt.options || []).map((opt: any) => {
                const checked = selectedLeadCount === opt.id
                return (
                  <button
                    key={opt.id}
                    onClick={() => setSelectedLeadCount(opt.id)}
                    className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${
                      checked
                        ? "border-emerald/60 bg-emerald/10"
                        : "border-steel/20 bg-navy/60 hover:border-steel/40"
                    }`}
                  >
                    <div className={`w-4 h-4 shrink-0 rounded-full border-2 flex items-center justify-center transition-colors ${
                      checked ? "border-emerald bg-emerald" : "border-steel/50"
                    }`}>
                      {checked && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-offwhite">{opt.label}</p>
                      {opt.description && (
                        <p className="text-[11px] text-ice/50 mt-0.5">{opt.description}</p>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setLeadCountPrompt(null)}
                className="flex-1 py-2.5 rounded-xl text-sm font-medium text-ice/60 hover:text-offwhite border border-steel/20 hover:bg-steel/10 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (!selectedLeadCount) {
                    setLeadCountPrompt(null)
                    return
                  }
                  const label = (leadCountPrompt.options || []).find((o: any) => o.id === selectedLeadCount)?.label || selectedLeadCount
                  setLeadCountPrompt(null)
                  sendMessage(`I need ${label} (count: ${selectedLeadCount})`)
                }}
                className="flex-1 py-2.5 rounded-xl text-sm font-bold text-white bg-emerald hover:bg-emerald/80 transition-colors"
              >
                Confirm & Search
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </PlanGuard>
  )
}
