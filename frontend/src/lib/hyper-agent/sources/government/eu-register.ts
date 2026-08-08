// EU Transparency Register — EU Transparency Register
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface EURegisterEntry {
  id: string
  name: string
  location?: string
  registerNumber?: string
  registrationDate?: string
  status?: string
  category?: string
  subcategory?: string
  legalEntityType?: string
  mainDomain?: string
  countryCode?: string
  interests?: string[]
  personNames?: string[]
}

interface EURegisterResponse {
  data?: EURegisterEntry[]
  total?: number
  page?: number
}

export class EURegisterSourceSource extends BaseSource {
  name = "EU Transparency Register"
  id = "eu-register"
  category = "government"
  requiresApiKey = false
  rateLimit = 10

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    // The EU Transparency Register has a JSON API
    const count = Math.min(options?.count || 10, 50)
    const url = `https://ec.europa.eu/transparencyregister/public/consultation/displaylobbyist.do?id=${encodeURIComponent(query)}&locale=en`

    // Try the search endpoint first (returns HTML, but we can parse key data)
    const searchUrl = `https://ec.europa.eu/transparencyregister/public/consultation/search.do?locale=en&searchText=${encodeURIComponent(query)}&page=1&pageSize=${count}`

    try {
      const res = await fetch(searchUrl, {
        headers: {
          Accept: "text/html",
          "User-Agent": "Hyper Agent/1.0",
        },
      })
      if (!res.ok) return []
      const html = await res.text()

      // Parse lobby registration entries from HTML
      // Look for patterns like: <a href="displaylobbyist.do?id=...">Name</a>
      const entries = this.parseHtmlResults(html)
      if (!entries.length) return []

      const leads: Lead[] = []
      for (const entry of entries.slice(0, count)) {
        leads.push(this.makeLead({
          firstName: entry.name,
          lastName: "",
          company: entry.name,
          title: entry.category || "EU Registered Lobbyist",
          location: entry.location || entry.countryCode,
          website: entry.mainDomain || undefined,
          confidence: 0.7,
          tags: [
            "government", "eu-register", "lobbyist",
            ...(entry.countryCode ? [entry.countryCode.toLowerCase()] : []),
            ...(entry.category ? [entry.category.toLowerCase().replace(/\s+/g, "-")] : []),
          ],
          metadata: {
            source: "EU Transparency Register",
            registerId: entry.id,
            registerNumber: entry.registerNumber,
            registrationDate: entry.registrationDate,
            status: entry.status,
            category: entry.category,
            subcategory: entry.subcategory,
            legalEntityType: entry.legalEntityType,
            countryCode: entry.countryCode,
            interests: entry.interests,
          },
        }))
      }
      return leads
    } catch {
      return []
    }
  }

  private parseHtmlResults(html: string): EURegisterEntry[] {
    const entries: EURegisterEntry[] = []

    // Extract lobby registration links and names
    // Pattern: displaylobbyist.do?id=XXXXX followed by name text
    const linkRegex = /displaylobbyist\.do\?id=(\d+)[^>]*>([^<]+)</g
    let match
    const seen = new Set<string>()

    while ((match = linkRegex.exec(html)) !== null) {
      const id = match[1]
      const name = match[2].trim()
      if (!name || seen.has(id)) continue
      seen.add(id)

      // Try to extract additional context from surrounding HTML
      const contextStart = Math.max(0, match.index - 500)
      const contextEnd = Math.min(html.length, match.index + 1000)
      const context = html.slice(contextStart, contextEnd)

      // Look for country code (2 uppercase letters often near the entry)
      const countryMatch = context.match(/\b([A-Z]{2})\b/)
      const countryCode = countryMatch && countryMatch[1] !== "EU" && countryMatch[1] !== "ID"
        ? countryMatch[1] : undefined

      // Look for category
      const categoryMatch = context.match(/category[^>]*>([^<]+)</i)
      const category = categoryMatch?.[1]?.trim()

      entries.push({
        id,
        name,
        countryCode,
        category,
      })
    }

    // If regex didn't find much, try simpler patterns
    if (entries.length === 0) {
      const simpleRegex = />([^<]{5,100})<\/a>/g
      while ((match = simpleRegex.exec(html)) !== null) {
        const text = match[1].trim()
        if (text.length > 3 && !text.includes("http") && !seen.has(text)) {
          seen.add(text)
          entries.push({ id: String(entries.length), name: text })
        }
      }
    }

    return entries
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const name = domain.replace(/\.(com|io|co|org|net)$/, "").replace(/-/g, " ")
    const searchUrl = `https://ec.europa.eu/transparencyregister/public/consultation/search.do?locale=en&searchText=${encodeURIComponent(name)}&page=1&pageSize=1`

    try {
      const res = await fetch(searchUrl, { headers: { "User-Agent": "Hyper Agent/1.0" } })
      if (!res.ok) return null
      const html = await res.text()
      const entries = this.parseHtmlResults(html)
      if (!entries.length) return null

      return this.makeCompany({
        name: entries[0].name,
        domain,
        website: `https://${domain}`,
        description: "EU Transparency Register participant",
        metadata: {
          registerId: entries[0].id,
          category: entries[0].category,
        },
      })
    } catch {
      return null
    }
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

export default new EURegisterSourceSource()
