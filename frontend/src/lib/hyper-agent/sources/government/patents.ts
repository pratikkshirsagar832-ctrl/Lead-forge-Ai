// USPTO Patents — PatentsView API (FREE, no key needed)
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface PatentInventor {
  inventor_first_name: string
  inventor_last_name: string
  inventor_city?: string
  inventor_state?: string
  inventor_country?: string
}

interface PatentAssignee {
  assignee_organization?: string
  assignee_first_name?: string
  assignee_last_name?: string
  assignee_city?: string
  assignee_state?: string
  assignee_country?: string
  assignee_type?: string
}

interface Patent {
  patent_number: string
  patent_title: string
  patent_date: string
  patent_abstract?: string
  inventors?: PatentInventor[]
  assignees?: PatentAssignee[]
}

interface PatentsViewResponse {
  count: number
  patents: Patent[]
}

export class PatentsSourceSource extends BaseSource {
  name = "USPTO Patents"
  id = "patents"
  category = "government"
  requiresApiKey = false
  rateLimit = 45

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 50)

    // PatentsView API — completely free, no key needed
    const body = {
      q: { _text_any: { patent_title: query } },
      f: ["patent_number", "patent_title", "patent_date", "patent_abstract",
        "inventors.inventor_first_name", "inventors.inventor_last_name",
        "inventors.inventor_city", "inventors.inventor_state", "inventors.inventor_country",
        "assignees.assignee_organization", "assignees.assignee_first_name",
        "assignees.assignee_last_name", "assignees.assignee_city",
        "assignees.assignee_state", "assignees.assignee_country", "assignees.assignee_type"],
      o: { page: 1, per_page: count },
      s: [{ patent_date: "desc" }],
    }

    const data = await this.fetchJson<PatentsViewResponse>(
      "https://api.patentsview.org/patents/query",
      {
        "Content-Type": "application/json",
        "Accept": "application/json",
      }
    )

    // fetchJson does GET — PatentsView needs POST, so use fetch directly
    let result: PatentsViewResponse | null = null
    try {
      const res = await fetch("https://api.patentsview.org/patents/query", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(body),
      })
      if (res.ok) result = await res.json() as PatentsViewResponse
    } catch { /* ignore */ }

    if (!result?.patents?.length) return []

    const leads: Lead[] = []
    const seen = new Set<string>()

    for (const patent of result.patents) {
      // Extract inventors as leads
      if (patent.inventors) {
        for (const inv of patent.inventors) {
          const name = `${inv.inventor_first_name || ""} ${inv.inventor_last_name || ""}`.trim()
          if (!name || seen.has(name)) continue
          seen.add(name)

          const assigneeOrg = patent.assignees?.[0]?.assignee_organization
          leads.push(this.makeLead({
            firstName: inv.inventor_first_name || "",
            lastName: inv.inventor_last_name || "",
            company: assigneeOrg,
            title: "Inventor",
            location: [inv.inventor_city, inv.inventor_state, inv.inventor_country].filter(Boolean).join(", "),
            confidence: 0.7,
            tags: ["government", "patents", "inventor"],
            metadata: {
              source: "USPTO Patents",
              patentNumber: patent.patent_number,
              patentTitle: patent.patent_title,
              patentDate: patent.patent_date,
              abstract: patent.patent_abstract?.slice(0, 200),
            },
          }))
        }
      }

      // Extract assignees (companies) as leads
      if (patent.assignees) {
        for (const asgn of patent.assignees) {
          const orgName = asgn.assignee_organization || `${asgn.assignee_first_name || ""} ${asgn.assignee_last_name || ""}`.trim()
          if (!orgName || seen.has(orgName)) continue
          seen.add(orgName)

          const isCompany = asgn.assignee_type === "2" || !!asgn.assignee_organization
          leads.push(this.makeLead({
            firstName: isCompany ? orgName : (asgn.assignee_first_name || ""),
            lastName: isCompany ? "" : (asgn.assignee_last_name || ""),
            company: isCompany ? orgName : undefined,
            title: isCompany ? "Patent Holder" : "Individual Patent Holder",
            location: [asgn.assignee_city, asgn.assignee_state, asgn.assignee_country].filter(Boolean).join(", "),
            confidence: 0.75,
            tags: ["government", "patents", "assignee"],
            metadata: {
              source: "USPTO Patents",
              patentNumber: patent.patent_number,
              patentTitle: patent.patent_title,
              patentDate: patent.patent_date,
              assigneeType: asgn.assignee_type === "2" ? "Company" : "Individual",
            },
          }))
        }
      }
    }

    return leads.slice(0, count)
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const body = {
      q: { _text_any: { assignee_organization: domain.replace(/\.(com|io|co|org|net)$/, "") } },
      f: ["assignees.assignee_organization", "assignees.assignee_city", "assignees.assignee_state"],
      o: { page: 1, per_page: 1 },
    }

    try {
      const res = await fetch("https://api.patentsview.org/patents/query", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(body),
      })
      if (!res.ok) return null
      const data = await res.json() as PatentsViewResponse
      const assignee = data.patents?.[0]?.assignees?.[0]
      if (!assignee?.assignee_organization) return null

      return this.makeCompany({
        name: assignee.assignee_organization,
        domain,
        website: `https://${domain}`,
        description: `Patent holder with ${data.count} patent(s)`,
        headquarters: [assignee.assignee_city, assignee.assignee_state].filter(Boolean).join(", "),
        metadata: { patentCount: data.count },
      })
    } catch { return null }
  }

  async getContact(email: string): Promise<ContactData | null> {
    const [local, domain] = email.split("@")
    if (!domain) return null
    const parts = local.split(/[._-]/)
    return {
      name: parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" "),
      email,
      company: domain.replace(/\.(com|io|co|org|net)$/, ""),
      confidence: 0.5,
      source: this.name,
    }
  }
}

export default new PatentsSourceSource()
