// USASpending — US government spending data
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface USASpendingResult {
  "Award ID": string
  "Recipient Name": string
  "Award Amount": number
  "Start Date": string
  "End Date"?: string
  "Awarding Agency"?: string
  "Awarding Sub Agency"?: string
  "Contract Award Type"?: string
  "Award Type"?: string
  "Description"?: string
  "Awarding Office Name"?: string
  "Recipient Address Line 1"?: string
  "Recipient City"?: string
  "Recipient State"?: string
  "Recipient Zip Code"?: string
  "Recipient Country"?: string
}

interface USASpendingResponse {
  results: USASpendingResult[]
  limit: number
  page_metadata: {
    page: number
    hasNext: boolean
    lastPage: number
  }
  messages: string[]
}

export class USASpendingSourceSource extends BaseSource {
  name = "USASpending"
  id = "usaspending"
  category = "government"
  requiresApiKey = false
  rateLimit = 30

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 50)
    const url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    const body = {
      filters: {
        keywords: [query],
      },
      fields: [
        "Award ID",
        "Recipient Name",
        "Award Amount",
        "Start Date",
        "End Date",
        "Awarding Agency",
        "Awarding Sub Agency",
        "Award Type",
        "Description",
        "Recipient City",
        "Recipient State",
        "Recipient Country",
      ],
      limit: count,
      page: 1,
      sort: "Award Amount",
      order: "desc",
      subawards: false,
    }

    let data: USASpendingResponse | null = null
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!res.ok) return []
      data = (await res.json()) as USASpendingResponse
    } catch {
      return []
    }

    if (!data?.results?.length) return []

    const leads: Lead[] = []
    const seen = new Set<string>()

    for (const result of data.results) {
      const recipientName = result["Recipient Name"]
      if (!recipientName || seen.has(recipientName)) continue
      seen.add(recipientName)

      const location = [result["Recipient City"], result["Recipient State"], result["Recipient Country"]]
        .filter(Boolean).join(", ")

      const awardAmount = result["Award Amount"]
      const amountStr = awardAmount >= 1_000_000
        ? `$${(awardAmount / 1_000_000).toFixed(1)}M`
        : awardAmount >= 1_000
          ? `$${(awardAmount / 1_000).toFixed(0)}K`
          : `$${awardAmount.toFixed(0)}`

      leads.push(this.makeLead({
        firstName: recipientName,
        lastName: "",
        company: recipientName,
        title: result["Award Type"] || "Government Contractor",
        location: location || undefined,
        confidence: 0.75,
        tags: [
          "government", "usaspending", "federal-contractor",
          ...(result["Awarding Agency"] ? [result["Awarding Agency"].toLowerCase().replace(/\s+/g, "-")] : []),
        ],
        metadata: {
          source: "USASpending",
          awardId: result["Award ID"],
          awardAmount: awardAmount,
          awardAmountFormatted: amountStr,
          startDate: result["Start Date"],
          endDate: result["End Date"],
          awardingAgency: result["Awarding Agency"],
          awardingSubAgency: result["Awarding Sub Agency"],
          awardType: result["Award Type"],
          description: result["Description"]?.slice(0, 200),
          recipientCity: result["Recipient City"],
          recipientState: result["Recipient State"],
          recipientCountry: result["Recipient Country"],
        },
      }))
    }
    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const name = domain.replace(/\.(com|io|co|org|net)$/, "").replace(/-/g, " ")
    const url = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
    const body = {
      filters: { keywords: [name] },
      fields: ["Recipient Name", "Award Amount", "Awarding Agency", "Recipient City", "Recipient State"],
      limit: 1,
      page: 1,
      sort: "Award Amount",
      order: "desc",
      subawards: false,
    }

    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!res.ok) return null
      const data = (await res.json()) as USASpendingResponse
      const result = data.results?.[0]
      if (!result) return null

      return this.makeCompany({
        name: result["Recipient Name"],
        domain,
        website: `https://${domain}`,
        headquarters: [result["Recipient City"], result["Recipient State"]].filter(Boolean).join(", "),
        metadata: {
          totalAwardAmount: result["Award Amount"],
          awardingAgency: result["Awarding Agency"],
        },
      })
    } catch {
      return null
    }
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

export default new USASpendingSourceSource()
