// Google Scholar — Academic researchers via HTML scraping
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

export class GoogleScholarSourceSource extends BaseSource {
  name = "Google Scholar"
  id = "google-scholar"
  category = "education"
  requiresApiKey = false
  rateLimit = 10 // Scholar is aggressive with rate limiting

  private readonly USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 20)
    const url = `https://scholar.google.com/scholar?q=${encodeURIComponent(query)}&hl=en&num=${count}`

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

      // Check for CAPTCHA/block
      if (html.includes("CAPTCHA") || html.includes("captcha") || html.includes("unusual traffic")) {
        return []
      }

      return this.parseScholarHtml(html, options)
    } catch {
      return []
    }
  }

  private parseScholarHtml(html: string, options?: SearchOptions): Lead[] {
    const leads: Lead[] = []
    const seen = new Set<string>()

    // Match each result block: <div class="gs_r gs_or gs_scl"> ... </div>
    // Scholar result pattern: title in <h3 class="gs_rt"><a href="URL">Title</a></h3>
    // Authors/journal in <div class="gs_a">Author1, Author2 - Journal, Year</div>
    // Snippet in <div class="gs_rs">...</div>

    const resultPattern = /<div class="gs_r gs_or gs_scl"[\s\S]*?<div class="gs_ri">([\s\S]*?)<\/div>\s*<\/div>\s*<\/div>/g
    let match: RegExpExecArray | null

    // Simpler approach: find each gs_ri block
    const blockPattern = /<div class="gs_ri">([\s\S]*?)<\/div>\s*(?:<div class="gs_fl">|<\/div>\s*<\/div>\s*<\/div>)/g

    // Even simpler: extract title + author lines
    const titlePattern = /<h3 class="gs_rt"[^>]*>(?:<span[^>]*>\[.*?\]<\/span>)?\s*(?:<a href="([^"]*)"[^>]*>)?([\s\S]*?)(?:<\/a>)?<\/h3>/g
    const authorPattern = /<div class="gs_a">([\s\S]*?)<\/div>/g

    const titles: { url: string; title: string }[] = []
    const authorLines: string[] = []

    // Extract titles
    while ((match = titlePattern.exec(html)) !== null) {
      const url = match[1] || ""
      const rawTitle = match[2].replace(/<[^>]+>/g, "").trim()
      if (rawTitle) {
        titles.push({ url, title: rawTitle })
      }
    }

    // Extract author lines
    while ((match = authorPattern.exec(html)) !== null) {
      const raw = match[1].replace(/<[^>]+>/g, "").trim()
      if (raw) authorLines.push(raw)
    }

    // Pair them up
    for (let i = 0; i < Math.min(titles.length, authorLines.length); i++) {
      const { url, title } = titles[i]
      const authorLine = authorLines[i]

      if (!title || seen.has(title)) continue
      seen.add(title)

      // Parse author line: "Author1, Author2, Author3 - Journal Name, 2023 - Publisher"
      const parts = authorLine.split(" - ")
      const authorsPart = parts[0] || ""
      const journalPart = parts[1] || ""
      const yearMatch = authorLine.match(/\b(19|20)\d{2}\b/)
      const year = yearMatch ? yearMatch[0] : undefined

      // Split authors by comma
      const authors = authorsPart.split(",").map(a => a.trim()).filter(Boolean)

      // Use first author as the primary lead
      if (authors.length > 0) {
        const firstAuthor = authors[0]
        const nameParts = firstAuthor.split(/\s+/)
        const firstName = nameParts[0] || firstAuthor
        const lastName = nameParts.length > 1 ? nameParts.slice(1).join(" ") : ""

        // Try to extract affiliation from author line (often after the last author, before the dash)
        let affiliation: string | undefined
        const affiliationMatch = authorLine.match(/(?:,\s*)([A-Z][a-zA-Z\s]+University|[A-Z][a-zA-Z\s]+Institute|[A-Z][a-zA-Z\s]+College|[A-Z][a-zA-Z\s]+Lab(?:oratory)?)/)
        if (affiliationMatch) affiliation = affiliationMatch[1].trim()

        leads.push(this.makeLead({
          firstName,
          lastName,
          company: affiliation || options?.company || journalPart.split(",")[0]?.trim(),
          title: title.length > 100 ? title.slice(0, 100) + "…" : title,
          website: url || undefined,
          confidence: 0.5,
          tags: ["education", "google-scholar", "academic", ...(year ? [year] : [])],
          metadata: {
            source: "Google Scholar",
            paperTitle: title,
            allAuthors: authors,
            journal: journalPart.split(",")[0]?.trim(),
            year,
            authorLine,
            url,
          },
        }))
      }
    }

    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net|edu)$/, ""),
      domain,
      website: `https://${domain}`,
      description: "Academic institution data from Google Scholar",
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

export default new GoogleScholarSourceSource()
