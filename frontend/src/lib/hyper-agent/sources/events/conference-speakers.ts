// Conference Speakers — Conference speaker discovery via PaperCall.io and Sessionize
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

export class ConferenceSpeakersSourceSource extends BaseSource {
  name = "Conference Speakers"
  id = "conference-speakers"
  category = "events"
  requiresApiKey = false
  rateLimit = 15

  private readonly USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    // Try multiple sources in parallel
    const [papercallLeads, sessionizeLeads] = await Promise.all([
      this.searchPaperCall(query, options),
      this.searchSessionize(query, options),
    ])

    const allLeads = [...papercallLeads, ...sessionizeLeads]

    // Deduplicate by name
    const seen = new Set<string>()
    const deduped: Lead[] = []
    for (const lead of allLeads) {
      const key = `${lead.firstName} ${lead.lastName}`.toLowerCase()
      if (!seen.has(key) && key.trim().length > 1) {
        seen.add(key)
        deduped.push(lead)
      }
    }

    return deduped
  }

  private async searchPaperCall(query: string, options?: SearchOptions): Promise<Lead[]> {
    const url = `https://www.papercall.io/speakers?search=${encodeURIComponent(query)}`

    try {
      const res = await fetch(url, {
        headers: {
          "User-Agent": this.USER_AGENT,
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
          "Accept-Language": "en-US,en;q=0.5",
        },
      })

      if (!res.ok) return []

      const html = await res.text()
      return this.parsePaperCallHtml(html, options)
    } catch {
      return []
    }
  }

  private parsePaperCallHtml(html: string, options?: SearchOptions): Lead[] {
    const leads: Lead[] = []

    // PaperCall.io speaker cards:
    // Speaker name in heading or link
    // Bio/description in paragraph
    // Talk title in nearby elements

    // Extract speaker cards
    const speakerPattern = /class="[^"]*(?:speaker|presenter)[^"]*"[\s\S]*?<h[234][^>]*>([\s\S]*?)<\/h[234]>/g
    let match: RegExpExecArray | null

    while ((match = speakerPattern.exec(html)) !== null) {
      const rawName = match[1].replace(/<[^>]+>/g, "").trim()
      if (!rawName || rawName.length < 2) continue

      const contextStart = Math.max(0, match.index - 200)
      const contextEnd = Math.min(html.length, match.index + 1000)
      const context = html.slice(contextStart, contextEnd)

      // Extract bio
      const bioMatch = context.match(/<p[^>]*class="[^"]*(?:bio|description|about)[^"]*"[^>]*>([\s\S]*?)<\/p>/)
      const bio = bioMatch ? bioMatch[1].replace(/<[^>]+>/g, "").trim().slice(0, 300) : undefined

      // Extract talk title
      const talkMatch = context.match(/class="[^"]*(?:talk|session|presentation)[^"]*"[^>]*>([\s\S]*?)<\//)
      const talkTitle = talkMatch ? talkMatch[1].replace(/<[^>]+>/g, "").trim() : undefined

      // Extract company/affiliation
      const companyMatch = context.match(/class="[^"]*(?:company|organization|affiliation)[^"]*"[^>]*>([\s\S]*?)<\//)
      const company = companyMatch ? companyMatch[1].replace(/<[^>]+>/g, "").trim() : undefined

      // Extract social links
      const twitterMatch = context.match(/href="https?:\/\/(?:www\.)?twitter\.com\/([^"/\s]+)/)
      const githubMatch = context.match(/href="https?:\/\/(?:www\.)?github\.com\/([^"/\s]+)/)

      const parts = rawName.split(/\s+/)
      const firstName = parts[0] || rawName
      const lastName = parts.length > 1 ? parts.slice(1).join(" ") : ""

      leads.push(this.makeLead({
        firstName,
        lastName,
        company: company || options?.company,
        title: talkTitle || "Conference Speaker",
        twitter: twitterMatch ? `@${twitterMatch[1]}` : undefined,
        website: githubMatch ? `https://github.com/${githubMatch[1]}` : undefined,
        confidence: 0.55,
        tags: ["events", "conference-speakers", "papercall"],
        metadata: {
          source: "PaperCall.io",
          bio,
          talkTitle,
          company,
        },
      }))
    }

    // Fallback: generic heading links
    if (leads.length === 0) {
      const linkPattern = /<a[^>]*href="\/speakers\/([^"]+)"[^>]*>([\s\S]*?)<\/a>/g
      while ((match = linkPattern.exec(html)) !== null) {
        const slug = match[1]
        const name = match[2].replace(/<[^>]+>/g, "").trim()
        if (!name || name.length < 2) continue

        const parts = name.split(/\s+/)
        leads.push(this.makeLead({
          firstName: parts[0] || name,
          lastName: parts.length > 1 ? parts.slice(1).join(" ") : "",
          title: "Conference Speaker",
          website: `https://www.papercall.io/speakers/${slug}`,
          confidence: 0.5,
          tags: ["events", "conference-speakers", "papercall"],
          metadata: {
            source: "PaperCall.io",
            speakerSlug: slug,
          },
        }))
      }
    }

    return leads
  }

  private async searchSessionize(query: string, options?: SearchOptions): Promise<Lead[]> {
    // Sessionize has some public event APIs — try common event IDs
    // Many events expose: https://sessionize.com/api/v2/{eventId}/view/speakers
    // We'll try a search on their site instead
    const url = `https://sessionize.com/events?q=${encodeURIComponent(query)}`

    try {
      const res = await fetch(url, {
        headers: {
          "User-Agent": this.USER_AGENT,
          "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
      })

      if (!res.ok) return []

      const html = await res.text()
      return this.parseSessionizeHtml(html, options)
    } catch {
      return []
    }
  }

  private parseSessionizeHtml(html: string, options?: SearchOptions): Lead[] {
    const leads: Lead[] = []

    // Sessionize event/speaker pages
    // Speaker names in links: /speaker/slug or event-specific URLs
    const speakerPattern = /href="[^"]*\/speaker\/([^"]+)"[^>]*>([\s\S]*?)<\/a>/g
    let match: RegExpExecArray | null

    while ((match = speakerPattern.exec(html)) !== null) {
      const slug = match[1]
      const rawName = match[2].replace(/<[^>]+>/g, "").trim()
      if (!rawName || rawName.length < 2) continue

      const parts = rawName.split(/\s+/)
      leads.push(this.makeLead({
        firstName: parts[0] || rawName,
        lastName: parts.length > 1 ? parts.slice(1).join(" ") : "",
        title: "Conference Speaker",
        website: `https://sessionize.com/speaker/${slug}`,
        confidence: 0.5,
        tags: ["events", "conference-speakers", "sessionize"],
        metadata: {
          source: "Sessionize",
          speakerSlug: slug,
        },
      }))
    }

    // Also look for event links with speaker counts
    const eventPattern = /href="\/([^"]+)"[^>]*class="[^"]*event[^"]*"[^>]*>[\s\S]*?<h[23][^>]*>([\s\S]*?)<\/h[23]>/g
    while ((match = eventPattern.exec(html)) !== null) {
      const eventSlug = match[1]
      const eventName = match[2].replace(/<[^>]+>/g, "").trim()
      if (!eventName || eventName.length < 2) continue

      leads.push(this.makeLead({
        firstName: eventName,
        lastName: "",
        company: eventName,
        title: "Conference / Event",
        website: `https://sessionize.com/${eventSlug}`,
        confidence: 0.4,
        tags: ["events", "conference", "sessionize"],
        metadata: {
          source: "Sessionize",
          eventName,
          eventSlug,
        },
      }))
    }

    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net)$/, ""),
      domain,
      website: `https://${domain}`,
      description: "Conference/event data",
      industry: "Events",
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

export default new ConferenceSpeakersSourceSource()
