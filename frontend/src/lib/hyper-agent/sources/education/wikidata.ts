// Wikidata SPARQL — Free company/people data from world's largest knowledge base
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface WikidataBinding {
  company?: { value: string }
  companyLabel?: { value: string }
  industryLabel?: { value: string }
  inception?: { value: string }
  headquartersLabel?: { value: string }
  website?: { value: string }
  description?: { value: string }
  numberOfEmployees?: { value: string }
  revenueLabel?: { value: string }
  ceoLabel?: { value: string }
  countryLabel?: { value: string }
}

interface WikidataResult {
  results: {
    bindings: WikidataBinding[]
  }
}

export class WikidataSource extends BaseSource {
  name = "Wikidata"
  id = "wikidata"
  category = "company"
  requiresApiKey = false
  rateLimit = 10 // Wikidata asks for polite usage

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 50)
    const results = await this.queryCompanies(query, count)
    if (!results.length) return []

    return results.map((r) => {
      const name = r.companyLabel?.value || ""
      const parts = name.trim().split(/\s+/)

      return this.makeLead({
        firstName: parts[0] || name,
        lastName: parts.length > 1 ? parts.slice(1).join(" ") : "",
        company: name,
        title: r.industryLabel?.value || "Company",
        website: r.website?.value,
        location: r.headquartersLabel?.value,
        confidence: r.website?.value ? 0.7 : 0.5,
        tags: [
          "company",
          "wikidata",
          ...(r.industryLabel?.value ? [r.industryLabel.value] : []),
          ...(r.countryLabel?.value ? [r.countryLabel.value] : []),
        ],
        metadata: {
          source: "Wikidata",
          wikidataUri: r.company?.value,
          industry: r.industryLabel?.value,
          founded: r.inception?.value?.split("T")[0], // ISO date
          headquarters: r.headquartersLabel?.value,
          website: r.website?.value,
          employees: r.numberOfEmployees?.value,
          ceo: r.ceoLabel?.value,
          country: r.countryLabel?.value,
        },
      })
    })
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    // Search by domain name as company name
    const companyName = domain.replace(/\.(com|io|co|org|net|dev|ai)$/, "")
    const results = await this.queryCompanies(companyName, 5)

    if (!results.length) return null

    const best = results[0]
    const name = best.companyLabel?.value || companyName

    return this.makeCompany({
      name,
      domain,
      website: best.website?.value || `https://${domain}`,
      description: best.description?.value,
      industry: best.industryLabel?.value,
      headquarters: best.headquartersLabel?.value,
      founded: best.inception?.value?.split("T")[0],
      metadata: {
        source: "Wikidata",
        wikidataUri: best.company?.value,
        employees: best.numberOfEmployees?.value,
        ceo: best.ceoLabel?.value,
        country: best.countryLabel?.value,
      },
    })
  }

  async getContact(email: string): Promise<ContactData | null> {
    const domain = email.split("@")[1]
    if (!domain) return null

    const companyName = domain.replace(/\.(com|io|co|org|net|dev|ai)$/, "")
    const results = await this.queryCompanies(companyName, 1)
    if (!results.length) return null

    const [local] = email.split("@")
    const parts = local.split(/[._-]/)

    return {
      name: parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" "),
      email,
      company: results[0].companyLabel?.value || companyName,
      confidence: 0.4,
      source: this.name,
    }
  }

  private async queryCompanies(query: string, limit: number): Promise<WikidataBinding[]> {
    const sparql = `
      SELECT ?company ?companyLabel ?industryLabel ?inception ?headquartersLabel ?website ?description ?numberOfEmployees ?ceoLabel ?countryLabel WHERE {
        ?company wdt:P31/wdt:P279* wd:Q783794 .
        ?company rdfs:label ?companyLabel .
        FILTER(LANG(?companyLabel) = "en")
        FILTER(CONTAINS(LCASE(?companyLabel), LCASE("${this.escapeSparql(query)}")))
        OPTIONAL { ?company wdt:P452 ?industry }
        OPTIONAL { ?company wdt:P571 ?inception }
        OPTIONAL { ?company wdt:P159 ?headquarters }
        OPTIONAL { ?company wdt:P856 ?website }
        OPTIONAL { ?company schema:description ?description . FILTER(LANG(?description) = "en") }
        OPTIONAL { ?company wdt:P1128 ?numberOfEmployees }
        OPTIONAL { ?company wdt:P169 ?ceo }
        OPTIONAL { ?company wdt:P17 ?country }
        SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
      }
      LIMIT ${limit}
    `.trim()

    const url = `https://query.wikidata.org/sparql?query=${encodeURIComponent(sparql)}`

    try {
      const res = await fetch(url, {
        headers: {
          Accept: "application/sparql-results+json",
          "User-Agent": "Hyper Agent/1.0 (https://Hyper Agent.com; contact@Hyper Agent.com)",
        },
        signal: AbortSignal.timeout(15000),
      })

      if (!res.ok) return []

      const data = (await res.json()) as WikidataResult
      return data.results?.bindings || []
    } catch {
      return []
    }
  }

  private escapeSparql(input: string): string {
    // Escape special characters for SPARQL string literals
    return input
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\n/g, "\\n")
      .replace(/\r/g, "\\r")
  }
}

export default new WikidataSource()
