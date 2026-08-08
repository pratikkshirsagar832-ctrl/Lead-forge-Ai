// ORCID — ORCID researcher IDs
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface ORCIDIdentifier {
  uri: string
  path: string
  host: string
}

interface ORCIDName {
  "given-names"?: { value: string }
  "family-name"?: { value: string }
}

interface ORCIDEmail {
  email: string
  verified: boolean
  primary: boolean
  visibility: string
}

interface ORCIDAffiliationSummary {
  "employment-summary": {
    organization: { name: string; "disambiguated-organization"?: { "disambiguation-source": string } }
    "role-title"?: { value: string }
    "start-date"?: { year?: { value: string } }
    "end-date"?: { year?: { value: string } }
  }
}

interface ORCIDResult {
  "orcid-identifier": ORCIDIdentifier
}

interface ORCIDSearchResponse {
  "num-found": number
  result: ORCIDResult[]
}

export class ORCIDSourceSource extends BaseSource {
  name = "ORCID"
  id = "orcid"
  category = "education"
  requiresApiKey = false
  rateLimit = 30

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 50)
    const url = `https://pub.orcid.org/v3.0/search/?q=${encodeURIComponent(query)}&rows=${count}`
    const data = await this.fetchJson<ORCIDSearchResponse>(url, { Accept: "application/json" })
    if (!data?.result?.length) return []

    const leads: Lead[] = []
    for (const entry of data.result) {
      const orcidId = entry["orcid-identifier"]
      if (!orcidId?.path) continue

      // Fetch person details
      const personUrl = `https://pub.orcid.org/v3.0/${orcidId.path}/person`
      const person = await this.fetchJson<{
        name?: ORCIDName
        emails?: { email: ORCIDEmail[] }
      }>(personUrl, { Accept: "application/json" })

      // Fetch employments
      const empUrl = `https://pub.orcid.org/v3.0/${orcidId.path}/employments`
      const employments = await this.fetchJson<{
        "affiliation-group"?: ORCIDAffiliationSummary[]
      }>(empUrl, { Accept: "application/json" })

      const firstName = person?.name?.["given-names"]?.value || ""
      const lastName = person?.name?.["family-name"]?.value || ""
      if (!firstName && !lastName) continue

      const email = person?.emails?.email?.find(e => e.primary)?.email
        || person?.emails?.email?.[0]?.email

      // Get current employment
      let company: string | undefined
      let title: string | undefined
      const affiliations = employments?.["affiliation-group"] || []
      for (const aff of affiliations) {
        const summary = aff["employment-summary"]
        if (summary?.organization?.name) {
          company = summary.organization.name
          title = summary["role-title"]?.value
          break // Take most recent
        }
      }

      leads.push(this.makeLead({
        firstName,
        lastName,
        email,
        company: company || options?.company,
        title: title || "Researcher",
        website: orcidId.uri,
        confidence: email ? 0.85 : 0.7,
        tags: ["education", "researcher", "orcid"],
        metadata: {
          source: "ORCID",
          orcidId: orcidId.path,
          orcidUrl: orcidId.uri,
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
      description: "Company data from ORCID",
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
      company: domain.replace(/\.(com|io|co|org|net)$/, ""),
      confidence: 0.5,
      source: this.name,
    }
  }
}

export default new ORCIDSourceSource()
