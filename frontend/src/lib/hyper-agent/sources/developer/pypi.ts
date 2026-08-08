// PyPI — Python package authors
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface PyPIInfo {
  name: string
  version: string
  author: string
  author_email: string
  home_page: string
  project_urls?: Record<string, string>
  summary: string
  license: string
  maintainer?: string
  maintainer_email?: string
}

interface PyPIResponse {
  info: PyPIInfo
}

export class PyPISourceSource extends BaseSource {
  name = "PyPI"
  id = "pypi"
  category = "developer"
  requiresApiKey = false
  rateLimit = 60

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    // PyPI doesn't have a search API, so we try exact package name match
    // and common variations (e.g. query as-is, with hyphens replaced by underscores)
    const candidates = [
      query,
      query.replace(/\s+/g, "-"),
      query.replace(/\s+/g, "_"),
      query.replace(/[\s-]+/g, "_"),
    ].filter((v, i, a) => a.indexOf(v) === i) // dedupe

    const leads: Lead[] = []
    const seen = new Set<string>()

    for (const pkgName of candidates.slice(0, 3)) {
      const url = `https://pypi.org/pypi/${encodeURIComponent(pkgName)}/json`
      const data = await this.fetchJson<PyPIResponse>(url)
      if (!data?.info) continue

      const info = data.info
      const authorName = info.author || info.maintainer || ""
      if (!authorName || seen.has(authorName)) continue
      seen.add(authorName)

      const parts = authorName.trim().split(/\s+/)
      const firstName = parts[0] || ""
      const lastName = parts.length > 1 ? parts.slice(1).join(" ") : ""

      const email = info.author_email || info.maintainer_email || undefined
      const website = info.home_page || info.project_urls?.Homepage || undefined

      // Try to extract company from project URLs
      let company: string | undefined
      const allUrls = Object.values(info.project_urls || {})
      for (const u of allUrls) {
        const m = u.match(/github\.com\/([^/]+)/)
        if (m) { company = m[1]; break }
      }

      leads.push(this.makeLead({
        firstName,
        lastName,
        email,
        company: company || options?.company,
        title: "Package Author",
        website,
        confidence: email ? 0.8 : 0.6,
        tags: ["developer", "pypi", "python"],
        metadata: {
          source: "PyPI",
          packageName: info.name,
          description: info.summary,
          license: info.license,
          latestVersion: info.version,
          projectUrls: info.project_urls,
        },
      }))

      if (leads.length >= (options?.count || 10)) break
    }
    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net)$/, ""),
      domain,
      website: `https://${domain}`,
      description: "Company data from PyPI",
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

export default new PyPISourceSource()
