// Chamber of Commerce — Chamber of Commerce business directory scraping
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

export class ChamberOfCommerceSourceSource extends BaseSource {
  name = "Chamber of Commerce"
  id = "chamberofcommerce"
  category = "local"
  requiresApiKey = false
  rateLimit = 10

  private readonly USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const url = `https://www.chamberofcommerce.com/search?query=${encodeURIComponent(query)}`

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

    // Chamber of Commerce listings typically have:
    // Business name in heading links
    // Address in structured address divs
    // Phone in phone-specific elements

    // Look for business listing blocks
    const listingPattern = /class="[^"]*(?:business-listing|listing-card|search-result|result-item)[^"]*"[\s\S]*?(?=class="[^"]*(?:business-listing|listing-card|search-result|result-item)|$)/g
    let match: RegExpExecArray | null

    // Also try a simpler approach: find all business name links
    // Pattern: links that look like business names
    const nameLinkPattern = /<(?:h[234]|a)[^>]*class="[^"]*(?:business-name|listing-name|result-title)[^"]*"[^>]*>([\s\S]*?)<\/(?:h[234]|a)>/g
    const names: string[] = []

    while ((match = nameLinkPattern.exec(html)) !== null) {
      const name = match[1].replace(/<[^>]+>/g, "").trim()
      if (name && name.length > 1) names.push(name)
    }

    // If no structured names found, try generic heading links
    if (names.length === 0) {
      const headingPattern = /<h[23][^>]*>\s*<a[^>]*href="[^"]*\/[^"]*"[^>]*>([\s\S]*?)<\/a>\s*<\/h[23]>/g
      while ((match = headingPattern.exec(html)) !== null) {
        const name = match[1].replace(/<[^>]+>/g, "").trim()
        if (name && name.length > 2 && name.length < 100) names.push(name)
      }
    }

    // Extract phones from the page
    const phones: string[] = []
    const phonePattern = /(?:\(?(\d{3})\)?[\s\-.](\d{3})[\s\-.](\d{4}))/g
    while ((match = phonePattern.exec(html)) !== null) {
      phones.push(`(${match[1]}) ${match[2]}-${match[3]}`)
    }

    // Extract addresses
    const addresses: string[] = []
    const addressPattern = /class="[^"]*(?:street-address|address)[^"]*"[^>]*>([\s\S]*?)<\//g
    while ((match = addressPattern.exec(html)) !== null) {
      const addr = match[1].replace(/<[^>]+>/g, "").trim()
      if (addr) addresses.push(addr)
    }

    // Build leads from extracted data
    for (let i = 0; i < names.length; i++) {
      const businessName = names[i]
      if (seen.has(businessName)) continue
      seen.add(businessName)

      leads.push(this.makeLead({
        firstName: businessName,
        lastName: "",
        company: businessName,
        phone: phones[i] || undefined,
        location: addresses[i] || options?.location,
        confidence: 0.5,
        tags: ["local", "chamberofcommerce", "business"],
        metadata: {
          source: "Chamber of Commerce",
          businessName,
          address: addresses[i],
          phone: phones[i],
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
      description: "Business data from Chamber of Commerce",
      industry: "Local Business",
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

export default new ChamberOfCommerceSourceSource()
