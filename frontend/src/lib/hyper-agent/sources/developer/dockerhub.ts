// Docker Hub — Docker Hub publishers
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface DockerRepo {
  name: string
  namespace: string
  description: string
  user: string
  star_count: number
  pull_count: number
  is_official: boolean
  is_automated: boolean
  last_updated: string
}

interface DockerHubResponse {
  count: number
  results: DockerRepo[]
}

export class DockerHubSourceSource extends BaseSource {
  name = "Docker Hub"
  id = "dockerhub"
  category = "developer"
  requiresApiKey = false
  rateLimit = 60

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 100)
    const url = `https://hub.docker.com/v2/repositories/?page_size=${count}&ordering=stars&name=${encodeURIComponent(query)}`
    const data = await this.fetchJson<DockerHubResponse>(url)
    if (!data?.results?.length) return []

    const leads: Lead[] = []
    const seen = new Set<string>()

    for (const repo of data.results) {
      const owner = repo.user || repo.namespace
      if (!owner || seen.has(owner)) continue
      seen.add(owner)

      // Docker Hub usernames don't have real names, use namespace as company
      const isOrg = repo.namespace !== repo.user && repo.namespace !== "library"
      const company = isOrg ? repo.namespace : undefined

      leads.push(this.makeLead({
        firstName: owner,
        lastName: "",
        company: company || options?.company,
        title: repo.is_official ? "Official Publisher" : "Docker Publisher",
        website: `https://hub.docker.com/u/${owner}`,
        confidence: 0.5,
        tags: [
          "developer", "docker",
          ...(repo.is_official ? ["official"] : []),
          ...(repo.is_automated ? ["automated"] : []),
        ],
        metadata: {
          source: "Docker Hub",
          namespace: repo.namespace,
          repoName: repo.name,
          description: repo.description,
          stars: repo.star_count,
          pulls: repo.pull_count,
          lastUpdated: repo.last_updated,
        },
      }))
    }
    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    // Try to look up as Docker Hub org
    const url = `https://hub.docker.com/v2/repositories/${encodeURIComponent(domain.replace(/\.(com|io|co|org|net)$/, ""))}/?page_size=1`
    const data = await this.fetchJson<{ results?: DockerRepo[] }>(url)
    if (data?.results?.length) {
      const repo = data.results[0]
      return this.makeCompany({
        name: repo.namespace,
        domain,
        website: `https://hub.docker.com/u/${repo.namespace}`,
        description: repo.description || `Docker Hub publisher: ${repo.namespace}`,
        industry: "Technology",
      })
    }
    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net)$/, ""),
      domain,
      website: `https://${domain}`,
      description: "Company data from Docker Hub",
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

export default new DockerHubSourceSource()
