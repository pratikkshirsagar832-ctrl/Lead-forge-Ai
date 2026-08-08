// OpenCorporates — OpenCorporates API — 140+ country registries (FREE)
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface OCAddress {
  street_address?: string
  locality?: string
  region?: string
  postal_code?: string
  country?: string
}

interface OCDirector {
  name: string
  position?: string
  start_date?: string
  end_date?: string
  nationality?: string
}

interface OCCompany {
  name: string
  company_number: string
  jurisdiction_code: string
  registered_address?: OCAddress | string
  incorporation_date?: string
  inactive_date?: string
  company_type?: string
  current_status?: string
  directors?: OCDirector[]
  agent?: { name: string }
  industry_codes?: Array<{ code: string; description: string }>
  url?: string
  retrieved_at?: string
}

interface OCCompanyResult {
  company: OCCompany
}

interface OCSearchResponse {
  results: {
    companies: OCCompanyResult[]
    total_count: number
    page: number
    per_page: number
  }
}

export class OpenCorporatesSourceSource extends BaseSource {
  name = "OpenCorporates"
  id = "opencorporates"
  category = "company"
  requiresApiKey = false
  rateLimit = 5 // Free tier: limited

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 30)
    const url = `https://api.opencorporates.com/v0.4/companies/search?q=${encodeURIComponent(query)}&per_page=${count}`
    const data = await this.fetchJson<OCSearchResponse>(url)
    if (!data?.results?.companies?.length) return []

    const leads: Lead[] = []

    for (const result of data.results.companies) {
      const co = result.company
      if (!co.name) continue

      const address = typeof co.registered_address === "string"
        ? co.registered_address
        : [co.registered_address?.street_address, co.registered_address?.locality, co.registered_address?.region, co.registered_address?.country]
          .filter(Boolean).join(", ")

      // Add company as a lead
      leads.push(this.makeLead({
        firstName: co.name,
        lastName: "",
        company: co.name,
        title: co.company_type || "Registered Company",
        location: address || undefined,
        website: co.url || undefined,
        confidence: 0.7,
        tags: [
          "company", "opencorporates",
          co.jurisdiction_code,
          ...(co.current_status ? [co.current_status.toLowerCase()] : []),
          ...(co.company_type ? [co.company_type.toLowerCase()] : []),
        ],
        metadata: {
          source: "OpenCorporates",
          companyNumber: co.company_number,
          jurisdiction: co.jurisdiction_code,
          incorporationDate: co.incorporation_date,
          inactiveDate: co.inactive_date,
          status: co.current_status,
          companyType: co.company_type,
          registeredAddress: co.registered_address,
          agent: co.agent?.name,
          industryCodes: co.industry_codes,
        },
      }))

      // Add directors as separate leads
      if (co.directors?.length) {
        for (const dir of co.directors.slice(0, 3)) {
          if (!dir.name) continue
          const dirParts = dir.name.trim().split(/\s+/)
          leads.push(this.makeLead({
            firstName: dirParts[0] || dir.name,
            lastName: dirParts.length > 1 ? dirParts.slice(1).join(" ") : "",
            company: co.name,
            title: dir.position || "Director",
            confidence: 0.8,
            tags: ["company", "opencorporates", "director"],
            metadata: {
              source: "OpenCorporates",
              directorPosition: dir.position,
              startDate: dir.start_date,
              endDate: dir.end_date,
              nationality: dir.nationality,
              companyName: co.name,
            },
          }))
        }
      }
    }

    return leads.slice(0, count)
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const name = domain.replace(/\.(com|io|co|org|net)$/, "").replace(/-/g, " ")
    const url = `https://api.opencorporates.com/v0.4/companies/search?q=${encodeURIComponent(name)}&per_page=1`
    const data = await this.fetchJson<OCSearchResponse>(url)

    const co = data?.results?.companies?.[0]?.company
    if (!co) return null

    const address = typeof co.registered_address === "string"
      ? co.registered_address
      : [co.registered_address?.street_address, co.registered_address?.locality, co.registered_address?.region, co.registered_address?.country]
        .filter(Boolean).join(", ")

    return this.makeCompany({
      name: co.name,
      domain,
      website: co.url || `https://${domain}`,
      founded: co.incorporation_date,
      headquarters: address || undefined,
      industry: co.industry_codes?.[0]?.description || co.company_type,
      metadata: {
        companyNumber: co.company_number,
        jurisdiction: co.jurisdiction_code,
        status: co.current_status,
        companyType: co.company_type,
      },
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

export default new OpenCorporatesSourceSource()
