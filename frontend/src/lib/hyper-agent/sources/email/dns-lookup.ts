// DNS Lookup — DNS/MX record lookup
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface DNSAnswer {
  name: string
  type: number
  TTL: number
  data: string
}

interface DNSResponse {
  Status: number
  Answer?: DNSAnswer[]
  Authority?: DNSAnswer[]
}

export class DNSLookupSourceSource extends BaseSource {
  name = "DNS Lookup"
  id = "dns-lookup"
  category = "email"
  requiresApiKey = false
  rateLimit = 120

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    // Accept domain or email
    const domain = query.includes("@") ? query.split("@")[1] : query
    if (!domain || !domain.includes(".")) return []

    const leads: Lead[] = []

    // Fetch A, MX, TXT records in parallel
    const [aRecords, mxRecords, txtRecords] = await Promise.all([
      this.fetchJson<DNSResponse>(`https://dns.google/resolve?name=${encodeURIComponent(domain)}&type=A`),
      this.fetchJson<DNSResponse>(`https://dns.google/resolve?name=${encodeURIComponent(domain)}&type=MX`),
      this.fetchJson<DNSResponse>(`https://dns.google/resolve?name=${encodeURIComponent(domain)}&type=TXT`),
    ])

    const hasA = aRecords?.Status === 0 && aRecords.Answer?.length
    const hasMx = mxRecords?.Status === 0 && mxRecords.Answer?.length

    if (!hasA && !hasMx) return []

    // Extract organization hints from TXT records
    let orgName: string | undefined
    const txtData = txtRecords?.Answer?.map(a => a.data) || []
    for (const txt of txtData) {
      // SPF often includes organization info
      const spfMatch = txt.match(/include:(\S+)/)
      if (spfMatch) {
        const spfDomain = spfMatch[1]
        if (!orgName) orgName = spfDomain.split(".").slice(-2, -1)[0]
      }
    }

    const company = options?.company || orgName || domain.split(".")[0]

    // Create a lead for the domain itself
    const ips = aRecords?.Answer?.map(a => a.data) || []
    const mxServers = mxRecords?.Answer?.map(a => a.data.split(" ").pop()) || []

    leads.push(this.makeLead({
      firstName: company.charAt(0).toUpperCase() + company.slice(1),
      lastName: "",
      company: company,
      title: "Domain Contact",
      email: `admin@${domain}`,
      website: `https://${domain}`,
      confidence: 0.4,
      tags: ["email", "dns", ...(hasMx ? ["has-mx"] : [])],
      metadata: {
        source: "DNS Lookup",
        domain,
        ips: ips.slice(0, 5),
        mxServers: mxServers.slice(0, 5),
        txtRecords: txtData.slice(0, 5),
        hasARecord: !!hasA,
        hasMxRecord: !!hasMx,
      },
    }))

    // If MX records point to known email providers, note that
    if (mxServers.length > 0) {
      const mxHost = mxServers[0] || ""
      let emailProvider = "custom"
      if (mxHost.includes("google") || mxHost.includes("gmail")) emailProvider = "Google Workspace"
      else if (mxHost.includes("outlook") || mxHost.includes("microsoft")) emailProvider = "Microsoft 365"
      else if (mxHost.includes("proton")) emailProvider = "ProtonMail"
      else if (mxHost.includes("zoho")) emailProvider = "Zoho"
      else if (mxHost.includes("amazon") || mxHost.includes("ses")) emailProvider = "Amazon SES"

      if (emailProvider !== "custom") {
        leads[0].metadata = { ...leads[0].metadata, emailProvider }
        leads[0].confidence = 0.5
      }
    }

    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const aRecords = await this.fetchJson<DNSResponse>(`https://dns.google/resolve?name=${encodeURIComponent(domain)}&type=A`)
    if (!aRecords || aRecords.Status !== 0 || !aRecords.Answer?.length) return null

    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net)$/, ""),
      domain,
      website: `https://${domain}`,
      description: `Domain resolved to ${aRecords.Answer[0].data}`,
      industry: "Technology",
      metadata: { ips: aRecords.Answer.map(a => a.data) },
    })
  }

  async getContact(email: string): Promise<ContactData | null> {
    const [local, domain] = email.split("@")
    if (!domain) return null

    const mxRecords = await this.fetchJson<DNSResponse>(`https://dns.google/resolve?name=${encodeURIComponent(domain)}&type=MX`)
    const hasMx = mxRecords?.Status === 0 && mxRecords.Answer?.length

    return {
      name: local,
      email,
      company: domain.replace(/\.(com|io|co|org|net)$/, ""),
      confidence: hasMx ? 0.7 : 0.3,
      source: this.name,
    }
  }
}

export default new DNSLookupSourceSource()
