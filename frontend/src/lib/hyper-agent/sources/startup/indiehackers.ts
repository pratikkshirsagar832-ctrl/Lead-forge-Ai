// Indie Hackers — Indie Hackers founder and product scraping
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

export class IndieHackersSourceSource extends BaseSource {
  name = "Indie Hackers"
  id = "indiehackers"
  category = "startup"
  requiresApiKey = false
  rateLimit = 15

  private readonly USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    // Try the Algolia-powered search API first (Indie Hackers uses Algolia)
    const leads = await this.tryAlgoliaSearch(query, options)
    if (leads.length > 0) return leads

    // Fallback to HTML scraping
    return this.tryHtmlSearch(query, options)
  }

  private async tryAlgoliaSearch(query: string, options?: SearchOptions): Promise<Lead[]> {
    // Indie Hackers posts are indexed — try fetching recent posts
    const url = `https://www.indiehackers.com/api/v2/search?q=${encodeURIComponent(query)}&limit=${options?.count || 10}`

    try {
      const res = await fetch(url, {
        headers: {
          "User-Agent": this.USER_AGENT,
          "Accept": "application/json",
        },
      })

      if (!res.ok) return []

      const data = await res.json() as { results?: Array<{ title?: string; url?: string; author?: string; content?: string }> }
      if (!data?.results?.length) return []

      const leads: Lead[] = []
      const seen = new Set<string>()

      for (const result of data.results) {
        const title = result.title || ""
        if (!title) continue

        // Try to extract founder/product name from title
        const nameParts = title.split(/\s+[-–—:]\s+/)
        const mainTitle = nameParts[0]?.trim() || title

        if (seen.has(mainTitle)) continue
        seen.add(mainTitle)

        leads.push(this.makeLead({
          firstName: mainTitle,
          lastName: "",
          company: mainTitle,
          title: "Indie Hacker / Founder",
          website: result.url || undefined,
          confidence: 0.45,
          tags: ["startup", "indiehackers", "founder"],
          metadata: {
            source: "Indie Hackers",
            postTitle: title,
            postUrl: result.url,
            author: result.author,
            snippet: result.content?.slice(0, 200),
          },
        }))
      }

      return leads
    } catch {
      return []
    }
  }

  private async tryHtmlSearch(query: string, options?: SearchOptions): Promise<Lead[]> {
    const url = `https://www.indiehackers.com/search?q=${encodeURIComponent(query)}`

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

    // Indie Hackers posts and discussions
    // Post links: <a href="/post/...">Title</a>
    // User profiles: <a href="/@username">Name</a>
    // Product pages: <a href="/product/product-name">Product Name</a>

    // Extract user profiles
    const userPattern = /href="\/@([^"]+)"[^>]*>([^<]+)<\/a>/g
    let match: RegExpExecArray | null

    while ((match = userPattern.exec(html)) !== null) {
      const username = match[1]
      const displayName = match[2].trim()
      if (!displayName || displayName.length < 2 || seen.has(displayName)) continue
      seen.add(displayName)

      const parts = displayName.split(/\s+/)
      const firstName = parts[0] || displayName
      const lastName = parts.length > 1 ? parts.slice(1).join(" ") : ""

      leads.push(this.makeLead({
        firstName,
        lastName,
        title: "Indie Hacker / Founder",
        website: `https://www.indiehackers.com/@${username}`,
        confidence: 0.5,
        tags: ["startup", "indiehackers", "founder"],
        metadata: {
          source: "Indie Hackers",
          username,
        },
      }))
    }

    // Extract product names
    const productPattern = /href="\/product\/([^"]+)"[^>]*>([\s\S]*?)<\/a>/g
    while ((match = productPattern.exec(html)) !== null) {
      const slug = match[1]
      const rawName = match[2].replace(/<[^>]+>/g, "").trim()
      if (!rawName || rawName.length < 2 || seen.has(rawName)) continue
      seen.add(rawName)

      leads.push(this.makeLead({
        firstName: rawName,
        lastName: "",
        company: rawName,
        title: "Product / Startup",
        website: `https://www.indiehackers.com/product/${slug}`,
        confidence: 0.45,
        tags: ["startup", "indiehackers", "product"],
        metadata: {
          source: "Indie Hackers",
          productSlug: slug,
        },
      }))
    }

    // Extract post titles
    const postPattern = /href="\/post\/([^"]+)"[^>]*>([\s\S]*?)<\/a>/g
    while ((match = postPattern.exec(html)) !== null) {
      const postId = match[1]
      const rawTitle = match[2].replace(/<[^>]+>/g, "").trim()
      if (!rawTitle || rawTitle.length < 5 || seen.has(rawTitle)) continue
      seen.add(rawTitle)

      leads.push(this.makeLead({
        firstName: rawTitle.slice(0, 50),
        lastName: "",
        title: rawTitle.length > 100 ? rawTitle.slice(0, 100) + "…" : rawTitle,
        website: `https://www.indiehackers.com/post/${postId}`,
        confidence: 0.4,
        tags: ["startup", "indiehackers", "discussion"],
        metadata: {
          source: "Indie Hackers",
          postTitle: rawTitle,
          postId,
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
      description: "Startup data from Indie Hackers",
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

export default new IndieHackersSourceSource()
