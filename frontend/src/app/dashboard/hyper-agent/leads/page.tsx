"use client"

import { useState, useEffect } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Search, ExternalLink, Loader2 } from "lucide-react"
import Link from "next/link"
import api from "@/lib/api"
import type { LeadListItem } from "@/lib/types"

export default function LeadsPage() {
  const [leads, setLeads] = useState<LeadListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    let cancelled = false
    api
      .get("/api/leads", { params: { source: "hyper_agent", per_page: 100 } })
      .then((r) => {
        if (!cancelled) setLeads(r.data?.items || [])
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load leads. Please try again.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filteredLeads = leads.filter((lead) =>
    `${lead.business_name} ${lead.category || ""} ${lead.headline || ""}`
      .toLowerCase()
      .includes(searchQuery.toLowerCase())
  )

  const hotCount = leads.filter((l) => l.lead_category === "hot").length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold">HyperAgent Leads</h1>
          <p className="text-ice/60 text-sm mt-1">
            {leads.length} leads • {hotCount} hot
          </p>
        </div>
        <Link
          href="/dashboard/leads?search_id=&source=hyper_agent"
          className="text-xs text-violet hover:underline"
        >
          View in Pipeline →
        </Link>
      </div>

      <div className="relative flex-1 max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ice/60" />
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search leads..."
          className="pl-9 w-full bg-white/5 border border-ocean/20 rounded-md px-3 py-2 text-sm outline-none focus:border-violet/50"
        />
      </div>

      <Card className="bg-ocean border-ocean/20">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-steel">
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading leads...
            </div>
          ) : error ? (
            <div className="text-center py-16 text-rose-400 text-sm">{error}</div>
          ) : filteredLeads.length === 0 ? (
            <div className="text-center py-16 text-steel text-sm">
              No leads yet. Run a HyperAgent search to find leads.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-ocean/20">
                    <th className="text-left p-3 text-ice/60 font-medium">Name</th>
                    <th className="text-left p-3 text-ice/60 font-medium">Company</th>
                    <th className="text-left p-3 text-ice/60 font-medium">Headline</th>
                    <th className="text-left p-3 text-ice/60 font-medium">Score</th>
                    <th className="text-left p-3 text-ice/60 font-medium">Type</th>
                    <th className="text-left p-3 text-ice/60 font-medium">Status</th>
                    <th className="text-left p-3 w-24"></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLeads.map((lead) => (
                    <tr key={lead.id} className="border-b border-ocean/10 hover:bg-steel/10 transition">
                      <td className="p-3">
                        <div className="flex items-center gap-2">
                          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-violet to-cyan flex items-center justify-center text-xs font-bold shrink-0">
                            {(lead.business_name || "?")[0]}
                          </div>
                          <p className="font-medium text-offwhite">{lead.business_name}</p>
                        </div>
                      </td>
                      <td className="p-3 text-ice/80">{lead.category || "-"}</td>
                      <td className="p-3 text-ice/50 max-w-[220px] truncate">{lead.headline || "-"}</td>
                      <td className="p-3">
                        <Badge
                          className={
                            (lead.ai_confidence_score ?? 0) >= 0.75
                              ? "bg-emerald/20 text-emerald border-0"
                              : "bg-cyan/20 text-cyan border-0"
                          }
                        >
                          {Math.round((lead.ai_confidence_score ?? 0) * 100)}
                        </Badge>
                      </td>
                      <td className="p-3">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-ocean/40 text-ice/70 border border-steel/15">
                          {lead.post_type || "-"}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-steel/20 text-ice/60">
                          {lead.user_status}
                        </span>
                      </td>
                      <td className="p-3">
                        <div className="flex gap-2">
                          {lead.post_url && (
                            <a
                              href={lead.post_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-violet hover:underline flex items-center gap-1 text-xs"
                            >
                              Post <ExternalLink className="w-3 h-3" />
                            </a>
                          )}
                          <Link
                            href={`/dashboard/leads/${lead.id}`}
                            className="text-ice/60 hover:text-ice text-xs"
                          >
                            Detail
                          </Link>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
