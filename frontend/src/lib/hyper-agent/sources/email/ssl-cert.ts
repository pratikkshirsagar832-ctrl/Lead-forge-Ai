// SSL Certificate — Certificate Transparency logs via crt.sh
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface CrtShEntry {
  issuer_ca_id: number
  issuer_name: string
  common_name: string
  name_value: string
  id: number
  entry_timestamp: string
  not_before: string
  not_after: string
  serial_number: string
}

export class SSLCertSourceSource extends BaseSource {
  name = "SSL Certificate"
  id = "ssl-cert"
  category = "email"
  requiresApiKey = false
  rateLimit = 30

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    // Extract domain from query (could be domain, email, or company name)
    const domain = query.includes("@") ? query.split("@")[1] : query
    if (!domain || !domain.includes(".")) return []

    const url = `https://crt.sh/?q=${encodeURIComponent(domain)}&output=json`
    const data = await this.fetchJson<CrtShEntry[]>(url)
    if (!data?.length) return []

    // Deduplicate by issuer + common_name
    const seen = new Set<string>()
    const uniqueEntries: CrtShEntry[] = []
    for (const entry of data) {
      const key = `${entry.issuer_name}|${entry.common_name}`
      if (!seen.has(key)) {
        seen.add(key)
        uniqueEntries.push(entry)
      }
    }

    const leads: Lead[] = []
    const count = Math.min(options?.count || 10, 20)

    for (const entry of uniqueEntries.slice(0, count)) {
      // Parse issuer name (format: "CN=..., O=..., C=...")
      const issuerParts = this.parseDN(entry.issuer_name)
      const cnParts = this.parseDN(entry.common_name)

      const orgName = issuerParts.O || cnParts.O
      const cn = issuerParts.CN || cnParts.CN || entry.common_name

      if (!cn && !orgName) continue

      const company = orgName || cn
      const now = new Date()
      const notAfter = new Date(entry.not_after)
      const isValid = notAfter > now

      leads.push(this.makeLead({
        firstName: company,
        lastName: "",
        company: orgName || undefined,
        title: isValid ? "Active Certificate Holder" : "Certificate Holder",
        confidence: orgName ? 0.6 : 0.4,
        tags: [
          "email", "ssl", "certificate",
          ...(isValid ? ["active-cert"] : ["expired-cert"]),
        ],
        metadata: {
          source: "SSL Certificate",
          commonName: entry.common_name,
          issuerName: entry.issuer_name,
          issuerOrg: issuerParts.O,
          issuerCountry: issuerParts.C,
          validFrom: entry.not_before,
          validUntil: entry.not_after,
          isValid,
          crtShId: entry.id,
        },
      }))
    }
    return leads
  }

  private parseDN(dn: string): Record<string, string> {
    const result: Record<string, string> = {}
    if (!dn) return result
    const parts = dn.split(",")
    for (const part of parts) {
      const [key, ...vals] = part.trim().split("=")
      if (key && vals.length) result[key.trim()] = vals.join("=").trim()
    }
    return result
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const url = `https://crt.sh/?q=${encodeURIComponent(domain)}&output=json`
    const data = await this.fetchJson<CrtShEntry[]>(url)
    if (!data?.length) return null

    const latest = data[0]
    const issuerParts = this.parseDN(latest.issuer_name)
    const cnParts = this.parseDN(latest.common_name)
    const orgName = issuerParts.O || cnParts.O || domain.split(".")[0]

    return this.makeCompany({
      name: orgName,
      domain,
      website: `https://${domain}`,
      description: `SSL certificate issued by ${latest.issuer_name}`,
      industry: "Technology",
      metadata: {
        certIssuer: latest.issuer_name,
        certValidUntil: latest.not_after,
      },
    })
  }

  async getContact(email: string): Promise<ContactData | null> {
    const [local, domain] = email.split("@")
    if (!domain) return null

    const url = `https://crt.sh/?q=${encodeURIComponent(domain)}&output=json`
    const data = await this.fetchJson<CrtShEntry[]>(url)
    const issuerOrg = data?.[0] ? this.parseDN(data[0].issuer_name).O : undefined

    return {
      name: local,
      email,
      company: issuerOrg || domain.replace(/\.(com|io|co|org|net)$/, ""),
      confidence: data?.length ? 0.6 : 0.3,
      source: this.name,
    }
  }
}

export default new SSLCertSourceSource()
