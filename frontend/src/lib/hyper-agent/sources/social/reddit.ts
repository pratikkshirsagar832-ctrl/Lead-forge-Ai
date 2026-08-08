// Reddit — Reddit user profiles
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface RedditPost {
  author: string
  title: string
  selftext: string
  subreddit: string
  url: string
  author_flair_text?: string
  score: number
  num_comments: number
  created_utc: number
  permalink: string
  is_self: boolean
  link_flair_text?: string
}

interface RedditChild {
  data: RedditPost
}

interface RedditListing {
  data: {
    children: RedditChild[]
    after: string | null
  }
}

export class RedditSourceSource extends BaseSource {
  name = "Reddit"
  id = "reddit"
  category = "social"
  requiresApiKey = false
  rateLimit = 30 // Reddit is strict about rate limits

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const count = Math.min(options?.count || 10, 100)
    const url = `https://www.reddit.com/search.json?q=${encodeURIComponent(query)}&limit=${count}&sort=relevance`
    const data = await this.fetchJson<RedditListing>(url, {
      "User-Agent": "Hyper Agent/1.0",
    })
    if (!data?.data?.children?.length) return []

    const leads: Lead[] = []
    const seen = new Set<string>()

    for (const child of data.data.children) {
      const post = child.data
      if (!post.author || post.author === "[deleted]" || post.author === "AutoModerator") continue
      if (seen.has(post.author)) continue
      seen.add(post.author)

      // Extract organization hints from flair
      const company = post.author_flair_text || options?.company

      leads.push(this.makeLead({
        firstName: post.author,
        lastName: "",
        company,
        title: `r/${post.subreddit} Contributor`,
        website: `https://reddit.com${post.permalink}`,
        confidence: 0.4,
        tags: [
          "social", "reddit",
          `subreddit:${post.subreddit}`,
          ...(post.link_flair_text ? [post.link_flair_text] : []),
        ],
        metadata: {
          source: "Reddit",
          username: post.author,
          subreddit: post.subreddit,
          postTitle: post.title,
          score: post.score,
          numComments: post.num_comments,
          flair: post.author_flair_text,
          createdUtc: post.created_utc,
        },
      }))
    }
    return leads
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    // Search Reddit for mentions of the company
    const url = `https://www.reddit.com/search.json?q=${encodeURIComponent(domain)}&limit=5`
    const data = await this.fetchJson<RedditListing>(url, { "User-Agent": "Hyper Agent/1.0" })
    if (!data?.data?.children?.length) return null

    const subreddits = new Set<string>()
    let totalScore = 0
    for (const child of data.data.children) {
      subreddits.add(child.data.subreddit)
      totalScore += child.data.score
    }

    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net)$/, ""),
      domain,
      website: `https://${domain}`,
      description: `Mentioned in ${subreddits.size} subreddits with ${totalScore} total upvotes`,
      industry: "Technology",
      metadata: {
        subreddits: [...subreddits],
        totalMentions: data.data.children.length,
      },
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

export default new RedditSourceSource()
