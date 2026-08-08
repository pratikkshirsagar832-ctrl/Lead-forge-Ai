// WHOIS — Domain lookup via RDAP (free, no key needed)
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface RDAPEvent {
  eventAction: string
  eventDate: string
}

interface RDAPVCard {
  vcardArray: [string, Array<[string, ...string[]]>]
}

interface RDAPEntity {
  handle: string
  roles: string[]
  vcardArray?: [string, Array<[string, ...string[]]>]
  entities?: RDAPEntity[]
}

interface RDAPResponse {
  handle?: string
  ldhName?: string
  status?: string[]
  events?: RDAPEvent[]
  entities?: RDAPEntity[]
  nameservers?: Array<{ ldhName: string }>
  notices?: Array<{ title: string; description: string[] }>
}

export class WHOISSourceSource extends BaseSource {
  name = "WHOIS"
  id = "whois"
  category = "email"
  requiresApiKey = false
  rateLimit = 30

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const domain = query.includes("@") ? query.split("@")[1] : query
    if (!domain || !domain.includes(".")) return []

    const url = `https://rdap.org/domain/${encodeURIComponent(domain)}`
    const data = await this.fetchJson<RDAPResponse>(url)
    if (!data?.ldhName) return []

    const leads: Lead[] = []

    // Extract registrant info from entities
    const registrant = this.findEntity(data.entities || [], "registrant")
    const registrar = this.findEntity(data.entities || [], "registrar")

    const regName = this.extractFromVCard(registrant, "fn")
    const regEmail = this.extractFromVCard(registrant, "email")
    const regOrg = this.extractFromVCard(registrant, "org")
    const regAddr = this.extractFromVCard(registrant, "adr")
    const regPhone = this.extractFromVCard(registrant, "tel")

    const registrarName = this.extractFromVCard(registrar, "fn") || registrar?.handle

    // Registration dates
    const registrationDate = data.events?.find(e => e.eventAction === "registration")?.eventDate
    const expirationDate = data.events?.find(e => e.eventAction === "expiration")?.eventDate

    const fullName = regName || domain.split(".")[0]
    const parts = fullName.trim().split(/\s+/)
    const firstName = parts[0] || ""
    const lastName = parts.length > 1 ? parts.slice(1).join(" ") : ""

    if (firstName) {
      leads.push(this.makeLead({
        firstName,
        lastName,
        email: regEmail || undefined,
        phone: regPhone || undefined,
        company: regOrg || options?.company,
        title: "Domain Registrant",
        website: `https://${domain}`,
        confidence: regEmail ? 0.75 : 0.5,
        tags: ["email", "whois", "domain-registrant"],
        metadata: {
          source: "WHOIS/RDAP",
          domain: data.ldhName,
          registrar: registrarName,
          registrationDate,
          expirationDate,
          status: data.status,
          address: regAddr,
        },
      }))
    }

    // Add registrar as a secondary lead if different
    if (registrarName && registrarName !== fullName) {
      leads.push(this.makeLead({
        firstName: registrarName,
        lastName: "",
        company: registrarName,
        title: "Domain Registrar",
        confidence: 0.4,
        tags: ["email", "whois", "registrar"],
        metadata: {
          source: "WHOIS/RDAP",
          role: "registrar",
          registrarHandle: registrar?.handle,
        },
      }))
    }

    return leads
  }

  private findEntity(entities: RDAPEntity[], role: string): RDAPEntity | undefined {
    for (const entity of entities) {
      if (entity.roles?.includes(role)) return entity
      // Check nested entities (some RDAP servers nest registrar under registrant)
      if (entity.entities) {
        const found = this.findEntity(entity.entities, role)
        if (found) return found
      }
    }
    return undefined
  }

  private extractFromVCard(entity: RDAPEntity | undefined, field: string): string | undefined {
    if (!entity?.vcardArray) return undefined
    const vcard = entity.vcardArray[1]
    if (!Array.isArray(vcard)) return undefined

    for (const entry of vcard) {
      if (!Array.isArray(entry) || entry.length < 2) continue
      const key = entry[0] as string
      const value = entry.length >= 4 ? entry[3] : entry[2]
      if (key === field) {
        if (typeof value === "string") return value
        if (Array.isArray(value)) return (value as string[]).filter(Boolean).join(", ")
      }
    }
    return undefined
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const url = `https://rdap.org/domain/${encodeURIComponent(domain)}`
    const data = await this.fetchJson<RDAPResponse>(url)
    if (!data?.ldhName) return null

    const registrant = this.findEntity(data.entities || [], "registrant")
    const org = this.extractFromVCard(registrant, "org")
    const regDate = data.events?.find(e => e.eventAction === "registration")?.eventDate

    return this.makeCompany({
      name: org || domain.split(".")[0],
      domain,
      website: `https://${domain}`,
      founded: regDate?.split("T")[0],
      description: `Domain: ${data.ldhName}`,
      industry: "Technology",
      metadata: {
        registrationDate: regDate,
        status: data.status,
      },
    })
  }

  async getContact(email: string): Promise<ContactData | null> {
    const [local, domain] = email.split("@")
    if (!domain) return null

    const url = `https://rdap.org/domain/${encodeURIComponent(domain)}`
    const data = await this.fetchJson<RDAPResponse>(url)

    const registrant = this.findEntity(data?.entities || [], "registrant")
    const regName = this.extractFromVCard(registrant, "fn")
    const regEmail = this.extractFromVCard(registrant, "email")
    const regOrg = this.extractFromVCard(registrant, "org")

    return {
      name: regName || local,
      email: regEmail || email,
      company: regOrg || domain.replace(/\.(com|io|co|org|net)$/, ""),
      confidence: data?.ldhName ? 0.7 : 0.4,
      source: this.name,
    }
  }
}

export default new WHOISSourceSource()
