// Beta List — Beta List startup directory scraping
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

export class BetaListSourceSource extends BaseSource {
  name = "Beta List"
  id = "betalist"
  category = "startup"
  requiresApiKey = false
  rateLimit = 15

  private readonly USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const url = `https://betalist.com/?q=${encodeURIComponent(query)}`

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
      return this.parseHtml(html, options)
    } catch {
      return []
    }
  }

  private parseHtml(html: string, options?: SearchOptions): Lead[] {
    const leads: Lead[] = []
    const seen = new Set<string>()

    // Beta List startup cards:
    // Startup name in heading or link
    // Tagline/description in paragraph
    // Category tags

    // Extract startup cards
    // Beta List uses patterns like: <a href="/startup/slug"> or data attributes
    const startupPattern = /href="\/startup\/([^"]+)"[^>]*>([\s\S]*?)<\/a>/g
    let match: RegExpExecArray | null

    while ((match = startupPattern.exec(html)) !== null) {
      const slug = match[1]
      const rawText = match[2].replace(/<[^>]+>/g, "").trim()
      if (!rawText || rawText.length < 2 || seen.has(rawText)) continue
      seen.add(rawText)

      // Extract context around this match for more info
      const contextStart = Math.max(0, match.index - 500)
      const contextEnd = Math.min(html.length, match.index + 500)
      const context = html.slice(contextStart, contextEnd)

      // Look for description/tagline nearby
      const descMatch = context.match(/<p[^>]*class="[^"]*(?:tagline|description|excerpt)[^"]*"[^>]*>([\s\S]*?)<\/p>/)
      const description = descMatch ? descMatch[1].replace(/<[^>]+>/g, "").trim().slice(0, 200) : undefined

      // Look for category
      const catMatch = context.match(/class="[^"]*(?:category|tag|badge)[^"]*"[^>]*>([\s\S]*?)<\//)
      const category = catMatch ? catMatch[1].replace(/<[^>]+>/g, "").trim() : undefined

      leads.push(this.makeLead({
        firstName: rawText,
        lastName: "",
        company: rawText,
        title: description || "Beta Startup",
        website: `https://betalist.com/startup/${slug}`,
        confidence: 0.5,
        tags: ["startup", "betalist", ...(category ? [category] : [])],
        metadata: {
          source: "Beta List",
          startupName: rawText,
          startupSlug: slug,
          description,
          category,
        },
      }))
    }

    // Fallback: look for generic startup/company links
    if (leads.length === 0) {
      const genericPattern = /<h[23][^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>\s*<\/h[23]>/g
      while ((match = genericPattern.exec(html)) !== null) {
        const href = match[1]
        const name = match[2].replace(/<[^>]+>/g, "").trim()
        if (!name || name.length < 2 || seen.has(name)) continue
        seen.add(name)

        leads.push(this.makeLead({
          firstName: name,
          lastName: "",
          company: name,
          title: "Beta Startup",
          website: href.startsWith("http") ? href : `https://betalist.com${href}`,
          confidence: 0.4,
          tags: ["startup", "betalist"],
          metadata: {
            source: "Beta List",
            startupName: name,
          },
        }))
      }
    }

    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net)$/, ""),
      domain,
      website: `https://${domain}`,
      description: "Startup data from Beta List",
      industry: "Technology",
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

export default new BetaListSourceSource()
