// NPM — NPM package authors
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface NPMPackage {
  package: {
    name: string
    description: string
    author?: { name: string; email?: string; url?: string }
    publisher?: { username: string; email?: string }
    links?: { repository?: string; homepage?: string; npm?: string }
    maintainers?: Array<{ username: string; email?: string }>
    keywords?: string[]
    date?: string
  }
}

interface NPMSearchResponse {
  objects: NPMPackage[]
  total: number
}

export class NPMSourceSource extends BaseSource {
  name = "NPM"
  id = "npm"
  category = "developer"
  requiresApiKey = false
  rateLimit = 60

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 50)
    const url = `https://registry.npmjs.org/-/v1/search?text=${encodeURIComponent(query)}&size=${count}`
    const data = await this.fetchJson<NPMSearchResponse>(url)
    if (!data?.objects?.length) return []

    const leads: Lead[] = []
    for (const obj of data.objects) {
      const pkg = obj.package
      const author = pkg.author
      const publisher = pkg.publisher
      const maintainers = pkg.maintainers || []

      // Try to extract a name from author or publisher
      const nameStr = author?.name || publisher?.username || ""
      if (!nameStr) continue

      const parts = nameStr.trim().split(/\s+/)
      const firstName = parts[0] || ""
      const lastName = parts.length > 1 ? parts.slice(1).join(" ") : ""

      // Extract email from author, publisher, or first maintainer
      const email = author?.email || publisher?.email || maintainers[0]?.email || undefined

      // Try to infer company from links
      let company: string | undefined
      const repo = pkg.links?.repository || ""
      const homepage = pkg.links?.homepage || ""
      const urlMatch = (repo || homepage).match(/github\.com\/([^/]+)/)
      if (urlMatch) company = urlMatch[1]

      leads.push(this.makeLead({
        firstName,
        lastName,
        email,
        company: company || options?.company,
        title: "Package Author",
        website: pkg.links?.homepage || pkg.links?.repository || undefined,
        confidence: email ? 0.8 : 0.6,
        tags: ["developer", "npm", ...(pkg.keywords?.slice(0, 5) || [])],
        metadata: {
          source: "NPM",
          packageName: pkg.name,
          description: pkg.description,
          repository: pkg.links?.repository,
          lastPublished: pkg.date,
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
      description: "Company data from NPM",
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

export default new NPMSourceSource()
