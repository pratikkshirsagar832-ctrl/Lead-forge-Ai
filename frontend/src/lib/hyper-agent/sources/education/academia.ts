// Academia.edu — Academia.edu researcher and paper scraping
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

export class AcademiaSourceSource extends BaseSource {
  name = "Academia.edu"
  id = "academia"
  category = "education"
  requiresApiKey = false
  rateLimit = 10

  private readonly USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const url = `https://www.academia.edu/search?q=${encodeURIComponent(query)}`

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

      if (html.includes("captcha") || html.includes("Access denied")) {
        return []
      }

      return this.parseHtml(html, options)
    } catch {
      return []
    }
  }

  private parseHtml(html: string, options?: SearchOptions): Lead[] {
    const leads: Lead[] = []
    const seen = new Set<string>()

    // Academia.edu search results contain researcher profiles and papers
    // Profile links: /profiles/name-NNNNN
    // Paper links: /papers/paper-title

    // Extract researcher profile links with names
    const profilePattern = /href="\/profiles\/([^"]+)"[^>]*>([^<]+)<\/a>/g
    let match: RegExpExecArray | null

    while ((match = profilePattern.exec(html)) !== null) {
      const slug = match[1]
      const rawName = match[2].trim()
      if (!rawName || rawName.length < 2 || seen.has(rawName)) continue
      seen.add(rawName)

      const parts = rawName.split(/\s+/)
      const firstName = parts[0] || rawName
      const lastName = parts.length > 1 ? parts.slice(1).join(" ") : ""

      // Look for university/institution near the name
      const contextStart = Math.max(0, match.index - 300)
      const contextEnd = Math.min(html.length, match.index + 300)
      const context = html.slice(contextStart, contextEnd)

      let institution: string | undefined
      const instMatch = context.match(/(?:at|University|Institute|College|Lab(?:oratory)?)\s+([A-Z][a-zA-Z\s&]+?)(?:<|,|\.)/)
      if (instMatch) institution = instMatch[0].trim()

      leads.push(this.makeLead({
        firstName,
        lastName,
        company: institution || options?.company,
        title: "Researcher / Academic",
        website: `https://www.academia.edu/profiles/${slug}`,
        confidence: 0.45,
        tags: ["education", "academia", "researcher"],
        metadata: {
          source: "Academia.edu",
          profileSlug: slug,
          institution,
        },
      }))
    }

    // Also extract paper titles and their authors
    const paperPattern = /href="\/(\d+\/[^"]+)"[^>]*>([\s\S]*?)<\/a>/g
    while ((match = paperPattern.exec(html)) !== null) {
      const paperPath = match[1]
      const rawTitle = match[2].replace(/<[^>]+>/g, "").trim()
      if (!rawTitle || rawTitle.length < 10 || seen.has(rawTitle)) continue
      seen.add(rawTitle)

      // Look for author near paper
      const contextStart = Math.max(0, match.index - 200)
      const contextEnd = Math.min(html.length, match.index + 200)
      const context = html.slice(contextStart, contextEnd)
      const authorMatch = context.match(/href="\/profiles\/([^"]+)"[^>]*>([^<]+)<\/a>/)

      if (authorMatch) {
        const authorName = authorMatch[2].trim()
        if (!seen.has(authorName)) {
          seen.add(authorName)
          const parts = authorName.split(/\s+/)
          leads.push(this.makeLead({
            firstName: parts[0] || authorName,
            lastName: parts.length > 1 ? parts.slice(1).join(" ") : "",
            company: options?.company,
            title: "Academic Author",
            website: `https://www.academia.edu/${paperPath}`,
            confidence: 0.45,
            tags: ["education", "academia", "paper-author"],
            metadata: {
              source: "Academia.edu",
              paperTitle: rawTitle,
            },
          }))
        }
      }
    }

    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net|edu)$/, ""),
      domain,
      website: `https://${domain}`,
      description: "Academic institution data from Academia.edu",
      industry: "Education",
    })
  }

  async getContact(email: string): Promise<ContactData | null> {
    const [local, domain] = email.split("@")
    if (!domain) return null
    const parts = local.split(/[._-]/)
    return {
      name: parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" "),
      email,
      company: domain.replace(/\.(com|io|co|org|net|edu)$/, ""),
      confidence: 0.5,
      source: this.name,
    }
  }
}

export default new AcademiaSourceSource()
