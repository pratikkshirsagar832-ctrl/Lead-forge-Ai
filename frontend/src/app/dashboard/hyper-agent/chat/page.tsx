"use client"

import { useState, useRef, useEffect } from "react"
import { Card } from "@/components/ui/card"
import { Zap, Send, Loader2, Check, ArrowLeft, Bot, User } from "lucide-react"
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
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, leads, searchStep])

  const sendMessage = async () => {
    if (!input.trim() || loading) return

    const userMessage: Message = {
      role: "user",
      content: input,
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

      const res = await api.post("/api/hyper-agent/chat", { message: input, history })

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

      // If action is scrape, execute the search with progress steps
      if (data.action === "scrape" && data.data) {
        setLoading(true)

        setSearchStep("🔍 Connecting to LinkedIn...")
        await new Promise((r) => setTimeout(r, 800))

        setSearchStep("🔎 Searching for matching posts and profiles...")
        await new Promise((r) => setTimeout(r, 1500))

        setSearchStep("📊 Analyzing and scoring leads with AI...")
        await new Promise((r) => setTimeout(r, 1000))

        setSearchStep("✅ Qualifying top leads...")
        await new Promise((r) => setTimeout(r, 500))

        try {
          const scrapeRes = await api.post("/api/hyper-agent/scrape", { context: data.data })

          if (scrapeRes.status !== 200) {
            throw new Error("Scrape failed")
          }

          const scrapeData = scrapeRes.data
          setLeads(scrapeData.leads)
          setSearchId(scrapeData.search_id)
          setSearchStep(null)

          const resultMessage: Message = {
            role: "assistant",
            content: `✅ **Search Complete!**

Found **${scrapeData.qualified}** qualified leads from **${scrapeData.total}** results.

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
        {searchId && (
          <Link
            href="/dashboard/leads"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-violet hover:bg-violet/10 border border-violet/30 transition-colors"
          >
            View All Leads →
          </Link>
        )}
      </div>

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
                        {lead.linkedin_url && (
                          <a
                            href={lead.linkedin_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-violet hover:underline"
                          >
                            View →
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
              onClick={sendMessage}
              disabled={!input.trim() || loading}
              className="w-10 h-10 rounded-xl bg-violet hover:bg-violet/80 disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center transition-colors"
            >
              <Send className="w-4 h-4 text-white" />
            </button>
          </div>
        </div>
      </Card>
    </div>
    </PlanGuard>
  )
}
