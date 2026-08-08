// Better Business Bureau — BBB business directory scraping
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

export class BBBSourceSource extends BaseSource {
  name = "Better Business Bureau"
  id = "bbb"
  category = "local"
  requiresApiKey = false
  rateLimit = 10

  private readonly USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const url = `https://www.bbb.org/search?find_text=${encodeURIComponent(query)}&find_type=Category`

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

    // BBB search results:
    // Business name in: <h3 class="..."><a href="/us/...">Business Name</a></h3>
    // Rating in: <div class="bds-rating">A+</div> or data attributes
    // Address in various address elements
    // Phone in: <p class="...">Phone: (555) 123-4567</p>

    // Split by result cards — BBB uses result-card or similar class
    const cardPattern = /<article[^>]*class="[^"]*result[^"]*"[\s\S]*?<\/article>/g
    let match: RegExpExecArray | null

    // Alternative: split by listing links
    const blocks = html.split(/<article\b/)
    for (let i = 1; i < blocks.length; i++) {
      const block = blocks[i]
      if (block.length > 5000) continue // Skip overly large blocks

      // Extract business name
      const nameMatch = block.match(/<h[23][^>]*>\s*(?:<a[^>]*>)?([\s\S]*?)(?:<\/a>)?\s*<\/h[23]>/)
      if (!nameMatch) continue
      const businessName = nameMatch[1].replace(/<[^>]+>/g, "").trim()
      if (!businessName || businessName.length < 2 || seen.has(businessName)) continue
      seen.add(businessName)

      // Extract BBB profile URL
      const profileMatch = block.match(/href="(\/us\/[^"]+)"/)
      const profileUrl = profileMatch ? `https://www.bbb.org${profileMatch[1]}` : undefined

      // Extract rating (A+, A, B+, etc.)
      const ratingMatch = block.match(/\b([A-F][+-]?)\b(?=[^<]*(?:rating|grade|bbb))/i) ||
                          block.match(/>([A-F][+-]?)<\//)
      const rating = ratingMatch ? ratingMatch[1] : undefined

      // Extract phone
      const phoneMatch = block.match(/(?:Phone|Tel|ph)[^>]*>[:\s]*([\d\s\-\(\)\+\.]{7,})/i) ||
                         block.match(/(\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4})/)
      const phone = phoneMatch ? phoneMatch[1].trim() : undefined

      // Extract address
      const streetMatch = block.match(/class="[^"]*street[^"]*"[^>]*>([\s\S]*?)<\//)
      const cityMatch = block.match(/class="[^"]*locality[^"]*"[^>]*>([\s\S]*?)<\//)
      const street = streetMatch ? streetMatch[1].replace(/<[^>]+>/g, "").trim() : ""
      const city = cityMatch ? cityMatch[1].replace(/<[^>]+>/g, "").trim() : ""
      const location = [street, city].filter(Boolean).join(", ")

      // Extract categories
      const catMatch = block.match(/class="[^"]*categories?[^"]*"[^>]*>([\s\S]*?)<\//)
      const categories = catMatch
        ? catMatch[1].replace(/<[^>]+>/g, "").split(",").map(c => c.trim()).filter(Boolean)
        : []

      leads.push(this.makeLead({
        firstName: businessName,
        lastName: "",
        company: businessName,
        phone,
        location: location || options?.location,
        website: profileUrl,
        confidence: rating ? 0.6 : 0.5,
        tags: ["local", "bbb", "business", ...(rating ? [`bbb-${rating}`] : []), ...categories.slice(0, 3)],
        metadata: {
          source: "BBB",
          businessName,
          bbbRating: rating,
          categories,
          street,
          city,
          profileUrl,
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
      description: "Business data from Better Business Bureau",
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

export default new BBBSourceSource()
