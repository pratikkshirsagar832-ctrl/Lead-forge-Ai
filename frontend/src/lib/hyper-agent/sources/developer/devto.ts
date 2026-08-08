// Dev.to — Dev.to community
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface DevToUser {
  name: string
  username: string
  twitter_username?: string
  github_username?: string
  website_url?: string
  profile_image?: string
}

interface DevToArticle {
  title: string
  description: string
  url: string
  tag_list: string[]
  published_at: string
  user: DevToUser
  organization?: { name: string; username: string; url: string }
}

export class DevToSourceSource extends BaseSource {
  name = "Dev.to"
  id = "devto"
  category = "developer"
  requiresApiKey = false
  rateLimit = 60

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 30) // Dev.to max is 1000 but keep reasonable
    const tag = query.replace(/\s+/g, "").toLowerCase()
    const url = `https://dev.to/api/articles?per_page=${count}&tag=${encodeURIComponent(tag)}`
    const articles = await this.fetchJson<DevToArticle[]>(url)

    if (!articles?.length) {
      // Fallback: search by top articles
      const topUrl = `https://dev.to/api/articles?per_page=${count}&top=7`
      const topArticles = await this.fetchJson<DevToArticle[]>(topUrl)
      if (!topArticles?.length) return []
      return this.extractLeads(topArticles, options)
    }
    return this.extractLeads(articles, options)
  }

  private extractLeads(articles: DevToArticle[], options?: SearchOptions): Lead[] {
    const leads: Lead[] = []
    const seen = new Set<string>()

    for (const article of articles) {
      const user = article.user
      if (!user?.username || seen.has(user.username)) continue
      seen.add(user.username)

      const fullName = user.name || user.username
      const parts = fullName.trim().split(/\s+/)
      const firstName = parts[0] || user.username
      const lastName = parts.length > 1 ? parts.slice(1).join(" ") : ""

      const company = article.organization?.name || options?.company

      leads.push(this.makeLead({
        firstName,
        lastName,
        company,
        title: "Developer / Writer",
        website: user.website_url || undefined,
        twitter: user.twitter_username ? `@${user.twitter_username}` : undefined,
        confidence: user.website_url ? 0.7 : 0.55,
        tags: ["developer", "devto", ...(article.tag_list?.slice(0, 5) || [])],
        metadata: {
          source: "Dev.to",
          username: user.username,
          profileImage: user.profile_image,
          githubUsername: user.github_username,
          latestArticle: article.title,
          articleUrl: article.url,
          publishedAt: article.published_at,
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
      description: "Company data from Dev.to",
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

export default new DevToSourceSource()
