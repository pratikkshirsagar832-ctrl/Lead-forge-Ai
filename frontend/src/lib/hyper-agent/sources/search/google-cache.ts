// Google Cache & Wayback Machine — Historical web data (FREE)
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface CDXEntry {
  urlkey: string
  timestamp: string
  original: string
  mimetype: string
  statuscode: string
  digest: string
  length: string
}

interface WaybackSnapshot {
  url: string
  timestamp: string
  archivedUrl: string
}

export class GoogleCacheSource extends BaseSource {
  name = "Google Cache & Wayback"
  id = "google-cache"
  category = "search"
  requiresApiKey = false
  rateLimit = 10

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const domain = this.extractDomain(query)
    if (!domain) return []

    const leads: Lead[] = []

    // Query Wayback Machine CDX API
    const snapshots = await this.getWaybackSnapshots(domain, options?.count || 5)

    for (const snapshot of snapshots) {
      // Extract company info from archived URL
      const urlDomain = this.extractDomain(snapshot.url) || domain
      const companyName = urlDomain.replace(/\.(com|io|co|org|net|dev|ai)$/, "")

      leads.push(
        this.makeLead({
          firstName: companyName.charAt(0).toUpperCase() + companyName.slice(1),
          lastName: "",
          company: companyName,
          title: `Archived ${snapshot.timestamp.slice(0, 4)}-${snapshot.timestamp.slice(4, 6)}-${snapshot.timestamp.slice(6, 8)}`,
          website: snapshot.url,
          confidence: 0.5,
          tags: ["search", "wayback-machine", "historical", `year-${snapshot.timestamp.slice(0, 4)}`],
          metadata: {
            source: "Wayback Machine",
            originalUrl: snapshot.url,
            archivedUrl: snapshot.archivedUrl,
            timestamp: snapshot.timestamp,
            captureDate: `${snapshot.timestamp.slice(0, 4)}-${snapshot.timestamp.slice(4, 6)}-${snapshot.timestamp.slice(6, 8)}`,
          },
        })
      )
    }

    // Also try Google Cache for the domain
    const cached = await this.checkGoogleCache(domain)
    if (cached) {
      leads.push(
        this.makeLead({
          firstName: domain.split(".")[0].charAt(0).toUpperCase() + domain.split(".")[0].slice(1),
          lastName: "",
          company: domain.split(".")[0],
          title: "Google Cached Page",
          website: cached.cacheUrl,
          confidence: 0.4,
          tags: ["search", "google-cache", "cached"],
          metadata: {
            source: "Google Cache",
            originalUrl: cached.originalUrl,
            cacheUrl: cached.cacheUrl,
          },
        })
      )
    }

    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    // Get historical snapshots to build company profile
    const snapshots = await this.getWaybackSnapshots(domain, 10)
    if (!snapshots.length) return null

    const years = snapshots.map((s) => parseInt(s.timestamp.slice(0, 4)))
    const oldestYear = Math.min(...years)
    const newestYear = Math.max(...years)

    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net|dev|ai)$/, ""),
      domain,
      website: `https://${domain}`,
      description: `Web presence tracked from ${oldestYear} to ${newestYear} with ${snapshots.length} archived snapshots`,
      metadata: {
        source: "Wayback Machine",
        snapshotCount: snapshots.length,
        oldestSnapshot: oldestYear,
        newestSnapshot: newestYear,
        snapshots: snapshots.slice(0, 5).map((s) => ({
          url: s.url,
          date: s.timestamp,
          archivedUrl: s.archivedUrl,
        })),
      },
    })
  }

  async getContact(email: string): Promise<ContactData | null> {
    const domain = email.split("@")[1]
    if (!domain) return null

    const snapshots = await this.getWaybackSnapshots(domain, 3)
    if (!snapshots.length) return null

    const [local] = email.split("@")
    const parts = local.split(/[._-]/)

    return {
      name: parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" "),
      email,
      company: domain.replace(/\.(com|io|co|org|net|dev|ai)$/, ""),
      confidence: 0.4,
      source: this.name,
    }
  }

  private async getWaybackSnapshots(domain: string, limit: number): Promise<WaybackSnapshot[]> {
    try {
      const url = `https://web.archive.org/cdx/search/cdx?url=${encodeURIComponent(domain)}&output=json&limit=${limit}&fl=urlkey,timestamp,original,mimetype,statuscode&filter=statuscode:200&filter=mimetype:text/html&collapse=urlkey`

      const res = await fetch(url, {
        headers: {
          "User-Agent": "Hyper Agent/1.0 (https://Hyper Agent.com)",
        },
        signal: AbortSignal.timeout(10000),
      })

      if (!res.ok) return []

      const data = (await res.json()) as CDXEntry[][]
      if (!Array.isArray(data) || data.length < 2) return []

      // First row is headers, rest are data
      const headers = data[0] as unknown as string[]
      const snapshots: WaybackSnapshot[] = []

      for (let i = 1; i < data.length; i++) {
        const row = data[i] as unknown as string[]
        const entry: Record<string, string> = {}
        headers.forEach((h, idx) => {
          entry[h] = row[idx] || ""
        })

        if (entry.timestamp && entry.original) {
          snapshots.push({
            url: entry.original,
            timestamp: entry.timestamp,
            archivedUrl: `https://web.archive.org/web/${entry.timestamp}/${entry.original}`,
          })
        }
      }

      return snapshots
    } catch {
      return []
    }
  }

  private async checkGoogleCache(domain: string): Promise<{
    originalUrl: string
    cacheUrl: string
  } | null> {
    try {
      const cacheUrl = `https://webcache.googleusercontent.com/search?q=cache:${encodeURIComponent(domain)}`
      const res = await fetch(cacheUrl, {
        headers: {
          "User-Agent": "Mozilla/5.0 (compatible; Hyper Agent/1.0)",
          Accept: "text/html",
        },
        signal: AbortSignal.timeout(8000),
        redirect: "manual",
      })

      // Google cache returns 200 if cached, 404 if not
      if (res.status === 200) {
        return {
          originalUrl: `https://${domain}`,
          cacheUrl,
        }
      }

      return null
    } catch {
      return null
    }
  }

  private extractDomain(input: string): string | null {
    // If it's already a domain
    if (/^[a-z0-9][a-z0-9.-]+\.[a-z]{2,}$/i.test(input)) {
      return input.toLowerCase()
    }
    // If it's a URL
    try {
      const url = new URL(input.startsWith("http") ? input : `https://${input}`)
      return url.hostname
    } catch {
      return null
    }
  }
}

export default new GoogleCacheSource()
