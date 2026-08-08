// USPTO Trademarks — USPTO TSDR & IBd API (FREE, no key needed)
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface TrademarkResult {
  serialNumber: string
  markIdentification: string
  applicationDate?: string
  registrationDate?: string
  status?: string
  statusCode?: string
  ownerName?: string
  ownerAddress?: string
  ownerCity?: string
  ownerState?: string
  ownerCountry?: string
  markDescription?: string
  internationalClass?: string[]
  currentOwner?: string
  attorneyName?: string
  correspondentName?: string
  correspondentAddress?: string
}

interface IBdResponse {
  total?: number
  trademarks?: TrademarkResult[]
}

export class TrademarksSourceSource extends BaseSource {
  name = "USPTO Trademarks"
  id = "trademarks"
  category = "government"
  requiresApiKey = false
  rateLimit = 30

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 50)

    // USPTO Integrated Business Data (IBd) API — free, no key needed
    const params = new URLSearchParams({
      searchText: query,
      rows: String(Math.min(count, 50)),
      start: "0",
    })

    const url = `https://developer.uspto.gov/ibd-api/v1/trademark/search?${params}`

    let data: IBdResponse | null = null
    try {
      const res = await fetch(url, {
        headers: {
          "Accept": "application/json",
          "User-Agent": "Hyper Agent/1.0",
        },
      })
      if (res.ok) data = await res.json() as IBdResponse
    } catch { /* ignore */ }

    if (!data?.trademarks?.length) return []

    const leads: Lead[] = []
    const seen = new Set<string>()

    for (const tm of data.trademarks) {
      const ownerName = tm.currentOwner || tm.ownerName || tm.correspondentName
      if (!ownerName || seen.has(ownerName)) continue
      seen.add(ownerName)

      const isCompany = !ownerName.includes(" ") || ownerName.length > 30
      const parts = ownerName.split(/\s+/)
      const firstName = isCompany ? ownerName : (parts[0] || "")
      const lastName = isCompany ? "" : (parts.slice(1).join(" ") || "")

      leads.push(this.makeLead({
        firstName,
        lastName,
        company: isCompany ? ownerName : undefined,
        title: "Trademark Owner",
        location: [tm.ownerCity || tm.correspondentAddress, tm.ownerState, tm.ownerCountry].filter(Boolean).join(", "),
        confidence: 0.65,
        tags: ["government", "trademarks", ...(tm.internationalClass || []).slice(0, 3)],
        metadata: {
          source: "USPTO Trademarks",
          serialNumber: tm.serialNumber,
          markName: tm.markIdentification,
          applicationDate: tm.applicationDate,
          registrationDate: tm.registrationDate,
          status: tm.status,
          description: tm.markDescription?.slice(0, 200),
          classes: tm.internationalClass,
          attorney: tm.attorneyName,
        },
      }))
    }

    return leads.slice(0, count)
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const query = domain.replace(/\.(com|io|co|org|net)$/, "")
    const url = `https://developer.uspto.gov/ibd-api/v1/trademark/search?searchText=${encodeURIComponent(query)}&rows=5`

    try {
      const res = await fetch(url, {
        headers: { "Accept": "application/json", "User-Agent": "Hyper Agent/1.0" },
      })
      if (!res.ok) return null
      const data = await res.json() as IBdResponse
      if (!data.trademarks?.length) return null

      const tm = data.trademarks[0]
      return this.makeCompany({
        name: tm.currentOwner || tm.ownerName || query,
        domain,
        website: `https://${domain}`,
        description: `Trademark holder — ${tm.markIdentification}`,
        headquarters: [tm.ownerCity, tm.ownerState, tm.ownerCountry].filter(Boolean).join(", "),
        metadata: {
          trademarkCount: data.total,
          latestMark: tm.markIdentification,
          status: tm.status,
        },
      })
    } catch { return null }
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

export default new TrademarksSourceSource()
