// US Census — US Census business data
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

// County Business Patterns response: [[header...], [row...], ...]
type CensusCBPResponse = string[][]

export class CensusSourceSource extends BaseSource {
  name = "US Census"
  id = "census"
  category = "government"
  requiresApiKey = false
  rateLimit = 30

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    // Try to use the query as a NAICS code (2-6 digits)
    const naicsCode = query.replace(/\D/g, "")
    if (naicsCode.length < 2 || naicsCode.length > 6) {
      // If not a valid NAICS, try common industry mappings
      const mappedNaics = this.mapIndustryToNaics(query)
      if (!mappedNaics) return []
      return this.searchByNaics(mappedNaics, options)
    }
    return this.searchByNaics(naicsCode, options)
  }

  private async searchByNaics(naicsCode: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 50)
    // County Business Patterns: establishments, employment, payroll by NAICS and state
    const url = `https://api.census.gov/data/2021/cbp?get=NAME,ESTAB,EMP,PAYANN&for=state:*&NAICS2017=${encodeURIComponent(naicsCode)}`
    const data = await this.fetchJson<CensusCBPResponse>(url)
    if (!data || data.length < 2) return []

    // First row is headers, rest are data
    const headers = data[0]
    const nameIdx = headers.indexOf("NAME")
    const estabIdx = headers.indexOf("ESTAB")
    const empIdx = headers.indexOf("EMP")
    const payrollIdx = headers.indexOf("PAYANN")
    const stateIdx = headers.indexOf("state")

    if (nameIdx === -1) return []

    const leads: Lead[] = []
    const rows = data.slice(1).sort((a, b) => {
      const empA = parseInt(a[empIdx] || "0") || 0
      const empB = parseInt(b[empIdx] || "0") || 0
      return empB - empA
    })

    for (const row of rows.slice(0, count)) {
      const stateName = row[nameIdx]
      const establishments = parseInt(row[estabIdx] || "0") || 0
      const employment = parseInt(row[empIdx] || "0") || 0
      const payroll = parseInt(row[payrollIdx] || "0") || 0
      const stateCode = row[stateIdx]

      if (!stateName) continue

      const payrollFormatted = payroll >= 1_000_000
        ? `$${(payroll / 1_000_000).toFixed(0)}M`
        : payroll >= 1_000
          ? `$${(payroll / 1_000).toFixed(0)}K`
          : `$${payroll}`

      leads.push(this.makeLead({
        firstName: stateName,
        lastName: "",
        company: stateName,
        title: `${this.naicsToIndustry(naicsCode)} Industry Data`,
        location: stateName,
        confidence: 0.6,
        tags: ["government", "census", "business-patterns", `naics:${naicsCode}`],
        metadata: {
          source: "US Census",
          stateCode,
          naicsCode,
          industry: this.naicsToIndustry(naicsCode),
          establishments: parseInt(row[estabIdx] || "0") || 0,
          employment,
          annualPayroll: payroll,
          annualPayrollFormatted: payrollFormatted,
          year: 2021,
        },
      }))
    }
    return leads
  }

  private mapIndustryToNaics(query: string): string | null {
    const q = query.toLowerCase()
    const map: Record<string, string> = {
      "tech": "54", "technology": "54",
      "software": "5112", "saas": "5112",
      "healthcare": "62", "health": "62",
      "finance": "52", "banking": "52",
      "retail": "44", "ecommerce": "4541",
      "manufacturing": "31",
      "construction": "23",
      "education": "61",
      "real estate": "53",
      "restaurant": "722", "food": "722",
      "consulting": "5416",
      "marketing": "5418",
      "legal": "5411",
      "insurance": "524",
    }
    for (const [key, naics] of Object.entries(map)) {
      if (q.includes(key)) return naics
    }
    return null
  }

  private naicsToIndustry(naics: string): string {
    const prefix = naics.slice(0, 2)
    const map: Record<string, string> = {
      "11": "Agriculture", "21": "Mining", "22": "Utilities", "23": "Construction",
      "31": "Manufacturing", "32": "Manufacturing", "33": "Manufacturing",
      "42": "Wholesale Trade", "44": "Retail Trade", "45": "Retail Trade",
      "48": "Transportation", "49": "Transportation",
      "51": "Information", "52": "Finance", "53": "Real Estate",
      "54": "Professional Services", "55": "Management", "56": "Admin Services",
      "61": "Education", "62": "Healthcare", "71": "Arts & Entertainment",
      "72": "Accommodation & Food", "81": "Other Services", "92": "Public Administration",
    }
    return map[prefix] || "Unknown"
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    // Census doesn't have per-company data, return industry overview
    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net)$/, ""),
      domain,
      website: `https://${domain}`,
      description: "Industry data available via US Census County Business Patterns",
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

export default new CensusSourceSource()
