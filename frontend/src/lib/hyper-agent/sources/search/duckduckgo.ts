// DuckDuckGo — DuckDuckGo Instant Answer API (FREE)
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface DDGRelatedTopic {
  Text?: string
  FirstURL?: string
  Result?: string
  Icon?: { URL: string; Width: number; Height: number }
}

interface DDGResponse {
  Abstract: string
  AbstractText: string
  AbstractSource: string
  AbstractURL: string
  Image: string
  Heading: string
  RelatedTopics: DDGRelatedTopic[]
  Results: DDGRelatedTopic[]
  Type: string
}

export class DuckDuckGoSourceSource extends BaseSource {
  name = "DuckDuckGo"
  id = "duckduckgo"
  category = "search"
  requiresApiKey = false
  rateLimit = 30

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const url = `https://api.duckduckgo.com/?q=${encodeURIComponent(query)}&format=json&no_html=1&skip_disambig=1`
    const data = await this.fetchJson<DDGResponse>(url)
    if (!data) return []

    const leads: Lead[] = []
    const count = Math.min(options?.count || 10, 20)

    // If we got an abstract (direct answer), that's a strong signal
    if (data.AbstractText && data.AbstractURL) {
      const orgName = data.Heading || data.AbstractSource
      if (orgName) {
        leads.push(this.makeLead({
          firstName: orgName,
          lastName: "",
          company: orgName,
          title: data.Type === "D" ? "Organization" : "Entity",
          website: data.AbstractURL,
          confidence: 0.7,
          tags: ["search", "duckduckgo", "direct-answer"],
          metadata: {
            source: "DuckDuckGo",
            abstract: data.AbstractText.slice(0, 200),
            abstractSource: data.AbstractSource,
            abstractUrl: data.AbstractURL,
            heading: data.Heading,
            type: data.Type,
          },
        }))
      }
    }

    // Extract leads from related topics
    const topics = [...(data.RelatedTopics || []), ...(data.Results || [])]
    const seen = new Set<string>()

    for (const topic of topics) {
      if (leads.length >= count) break
      if (!topic.Text || !topic.FirstURL) continue

      // Parse name from the topic text (often "Name - Description" format)
      const textParts = topic.Text.split(" - ")
      const nameStr = textParts[0]?.trim()
      const description = textParts.slice(1).join(" - ").trim()

      if (!nameStr || seen.has(nameStr)) continue
      seen.add(nameStr)

      // Extract URL path as potential org name
      const urlPath = new URL(topic.FirstURL).pathname.split("/").pop() || ""
      const entityName = urlPath.replace(/_/g, " ")

      const parts = nameStr.split(/\s+/)
      const isLikelyOrg = parts.length === 1 || nameStr.includes(" ") === false

      leads.push(this.makeLead({
        firstName: isLikelyOrg ? nameStr : parts[0],
        lastName: isLikelyOrg ? "" : parts.slice(1).join(" "),
        company: isLikelyOrg ? nameStr : undefined,
        title: description.slice(0, 100) || undefined,
        website: topic.FirstURL,
        confidence: 0.5,
        tags: ["search", "duckduckgo", "related-topic"],
        metadata: {
          source: "DuckDuckGo",
          text: topic.Text,
          url: topic.FirstURL,
          entityName,
        },
      }))
    }

    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const url = `https://api.duckduckgo.com/?q=${encodeURIComponent(domain)}&format=json&no_html=1`
    const data = await this.fetchJson<DDGResponse>(url)
    if (!data) return null

    if (data.AbstractText && data.Heading) {
      return this.makeCompany({
        name: data.Heading,
        domain,
        website: data.AbstractURL || `https://${domain}`,
        description: data.AbstractText.slice(0, 500),
        industry: data.AbstractSource || undefined,
        metadata: {
          type: data.Type,
          image: data.Image,
        },
      })
    }

    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net)$/, ""),
      domain,
      website: `https://${domain}`,
    })
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

export default new DuckDuckGoSourceSource()
