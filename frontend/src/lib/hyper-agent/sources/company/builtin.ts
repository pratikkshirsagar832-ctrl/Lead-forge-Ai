// Builtin — Builtin.com tech company scraping
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

export class BuiltinSourceSource extends BaseSource {
  name = "Builtin"
  id = "builtin"
  category = "company"
  requiresApiKey = false
  rateLimit = 15

  private readonly USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const url = `https://builtin.com/companies?search=${encodeURIComponent(query)}`

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

    // Builtin.com company cards typically contain:
    // Company name in <h3> or heading links
    // Description in <p> tags
    // Location, tech stack, industry tags

    // Extract company cards — Builtin uses various card patterns
    // Try structured approach first
    const companyBlocks = html.split(/<div[^>]*class="[^"]*(?:company-card|company-item|card)[^"]*"/)

    for (let i = 1; i < companyBlocks.length; i++) {
      const block = companyBlocks[i].slice(0, 3000) // Limit block size

      // Company name in heading
      const nameMatch = block.match(/<h[23][^>]*>([\s\S]*?)<\/h[23]>/) ||
                        block.match(/<a[^>]*class="[^"]*company-name[^"]*"[^>]*>([\s\S]*?)<\/a>/)
      if (!nameMatch) continue
      const companyName = nameMatch[1].replace(/<[^>]+>/g, "").trim()
      if (!companyName || companyName.length < 2 || seen.has(companyName)) continue
      seen.add(companyName)

      // Company URL
      const urlMatch = block.match(/href="(https?:\/\/[^"]+|\/companies\/[^"]+)"/)
      const companyUrl = urlMatch
        ? (urlMatch[1].startsWith("http") ? urlMatch[1] : `https://builtin.com${urlMatch[1]}`)
        : undefined

      // Description
      const descMatch = block.match(/<p[^>]*>([\s\S]*?)<\/p>/)
      const description = descMatch ? descMatch[1].replace(/<[^>]+>/g, "").trim().slice(0, 300) : undefined

      // Location
      const locMatch = block.match(/class="[^"]*(?:location|city)[^"]*"[^>]*>([\s\S]*?)<\//)
      const location = locMatch ? locMatch[1].replace(/<[^>]+>/g, "").trim() : undefined

      // Tech stack tags
      const techTags: string[] = []
      const tagPattern = /class="[^"]*(?:tag|badge|chip|skill)[^"]*"[^>]*>([\s\S]*?)<\//g
      let tagMatch: RegExpExecArray | null
      while ((tagMatch = tagPattern.exec(block)) !== null) {
        const tag = tagMatch[1].replace(/<[^>]+>/g, "").trim()
        if (tag && tag.length < 30) techTags.push(tag)
      }

      // Industry
      const industryMatch = block.match(/class="[^"]*industry[^"]*"[^>]*>([\s\S]*?)<\//)
      const industry = industryMatch ? industryMatch[1].replace(/<[^>]+>/g, "").trim() : undefined

      // Size
      const sizeMatch = block.match(/class="[^"]*(?:size|employees|company-size)[^"]*"[^>]*>([\s\S]*?)<\//)
      const size = sizeMatch ? sizeMatch[1].replace(/<[^>]+>/g, "").trim() : undefined

      // Generate domain from company name
      const domain = companyName.toLowerCase().replace(/[^a-z0-9]/g, "") + ".com"

      leads.push(this.makeLead({
        firstName: companyName,
        lastName: "",
        company: companyName,
        title: description ? description.slice(0, 100) : undefined,
        location: location || options?.location,
        website: companyUrl,
        confidence: 0.5,
        tags: ["company", "builtin", "tech", ...techTags.slice(0, 5)],
        metadata: {
          source: "Builtin",
          companyName,
          description,
          industry,
          size,
          techStack: techTags,
          domain,
        },
      }))
    }

    // Fallback: if no company cards found, try generic pattern
    if (leads.length === 0) {
      const linkPattern = /href="\/companies\/([^"]+)"[^>]*>([\s\S]*?)<\/a>/g
      let match: RegExpExecArray | null
      while ((match = linkPattern.exec(html)) !== null) {
        const slug = match[1]
        const name = match[2].replace(/<[^>]+>/g, "").trim()
        if (!name || name.length < 2 || seen.has(name)) continue
        seen.add(name)

        leads.push(this.makeLead({
          firstName: name,
          lastName: "",
          company: name,
          website: `https://builtin.com/companies/${slug}`,
          confidence: 0.45,
          tags: ["company", "builtin"],
          metadata: {
            source: "Builtin",
            companySlug: slug,
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
      description: "Tech company data from Builtin",
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

export default new BuiltinSourceSource()
