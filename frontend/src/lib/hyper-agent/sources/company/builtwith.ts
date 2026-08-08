// BuiltWith / WhatRuns — Tech Stack Detection (FREE via web scraping)
import { BaseSource } from "../base"
import type { Lead, SearchOptions, CompanyData, ContactData } from "../types"

interface TechEntry {
  name: string
  category: string // e.g. "JavaScript Frameworks", "Analytics", "Hosting", "CMS"
}

interface WhatRunsResponse {
  // WhatRuns returns HTML; we parse tech entries from it
}

export class BuiltWithSource extends BaseSource {
  name = "BuiltWith Tech Stack"
  id = "builtwith"
  category = "company"
  requiresApiKey = false
  rateLimit = 10

  async search(query: string, options?: SearchOptions): Promise<Lead[]> {
    const domain = this.extractDomain(query)
    if (!domain) return []

    const techStack = await this.detectTechStack(domain)
    if (!techStack.length) return []

    const company = options?.company || domain.split(".")[0]
    const capitalized = company.charAt(0).toUpperCase() + company.slice(1)

    return [
      this.makeLead({
        firstName: capitalized,
        lastName: "",
        company: capitalized,
        title: "Tech Stack Profile",
        website: `https://${domain}`,
        confidence: 0.6,
        tags: ["company", "tech-stack", "builtwith", ...techStack.map((t) => t.category)],
        metadata: {
          source: "BuiltWith",
          domain,
          techStack: techStack.map((t) => t.name),
          categories: [...new Set(techStack.map((t) => t.category))],
        },
      }),
    ]
  }

  async getCompany(domain: string): Promise<CompanyData | null> {
    const techStack = await this.detectTechStack(domain)
    if (!techStack.length) return null

    return this.makeCompany({
      name: domain.replace(/\.(com|io|co|org|net|dev)$/, ""),
      domain,
      website: `https://${domain}`,
      techStack: techStack.map((t) => t.name),
      description: `Uses ${techStack.length} technologies across ${[...new Set(techStack.map((t) => t.category))].length} categories`,
      metadata: {
        source: "BuiltWith",
        technologies: techStack,
      },
    })
  }

  async getContact(email: string): Promise<ContactData | null> {
    const domain = email.split("@")[1]
    if (!domain) return null

    const techStack = await this.detectTechStack(domain)
    const [local] = email.split("@")
    const parts = local.split(/[._-]/)

    return {
      name: parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" "),
      email,
      company: domain.replace(/\.(com|io|co|org|net)$/, ""),
      confidence: techStack.length > 0 ? 0.6 : 0.3,
      source: this.name,
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
      // Try as company name — not ideal but fallback
      return null
    }
  }

  private async detectTechStack(domain: string): Promise<TechEntry[]> {
    const technologies: TechEntry[] = []

    // Method 1: Try BuiltWith direct page (scrape metadata)
    const builtWithEntries = await this.scrapeBuiltWith(domain)
    technologies.push(...builtWithEntries)

    // Method 2: Analyze HTTP headers and HTML from the site itself
    const siteEntries = await this.analyzeSite(domain)
    technologies.push(...siteEntries)

    // Deduplicate by name
    const seen = new Set<string>()
    return technologies.filter((t) => {
      const key = t.name.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }

  private async scrapeBuiltWith(domain: string): Promise<TechEntry[]> {
    const entries: TechEntry[] = []

    try {
      // BuiltWith free lookup page
      const res = await fetch(`https://builtwith.com/${domain}`, {
        headers: {
          "User-Agent": "Mozilla/5.0 (compatible; Hyper Agent/1.0)",
          Accept: "text/html",
        },
        signal: AbortSignal.timeout(10000),
      })

      if (!res.ok) return entries

      const html = await res.text()

      // Parse technology names from the HTML
      // BuiltWith uses various patterns; we look for common tech indicators
      const techPatterns: Array<{ regex: RegExp; category: string }> = [
        // JavaScript Frameworks
        { regex: /React(?:\.js)?/gi, category: "JavaScript Frameworks" },
        { regex: /Vue(?:\.js)?/gi, category: "JavaScript Frameworks" },
        { regex: /Angular/gi, category: "JavaScript Frameworks" },
        { regex: /Next(?:\.?js)?/gi, category: "JavaScript Frameworks" },
        { regex: /Nuxt/gi, category: "JavaScript Frameworks" },
        { regex: /Svelte/gi, category: "JavaScript Frameworks" },
        { regex: /jQuery/gi, category: "JavaScript Libraries" },
        // Analytics
        { regex: /Google Analytics/gi, category: "Analytics" },
        { regex: /Hotjar/gi, category: "Analytics" },
        { regex: /Mixpanel/gi, category: "Analytics" },
        { regex: /Segment/gi, category: "Analytics" },
        { regex: /Amplitude/gi, category: "Analytics" },
        { regex: /Plausible/gi, category: "Analytics" },
        { regex: /Matomo/gi, category: "Analytics" },
        // CMS
        { regex: /WordPress/gi, category: "CMS" },
        { regex: /Drupal/gi, category: "CMS" },
        { regex: /Joomla/gi, category: "CMS" },
        { regex: /Shopify/gi, category: "E-Commerce" },
        { regex: /Magento/gi, category: "E-Commerce" },
        { regex: /WooCommerce/gi, category: "E-Commerce" },
        { regex: /Squarespace/gi, category: "Website Builder" },
        { regex: /Wix(?:\.com)?/gi, category: "Website Builder" },
        { regex: /Webflow/gi, category: "Website Builder" },
        // Hosting / CDN
        { regex: /Cloudflare/gi, category: "CDN" },
        { regex: /AWS|Amazon Web Services/gi, category: "Hosting" },
        { regex: /Vercel/gi, category: "Hosting" },
        { regex: /Netlify/gi, category: "Hosting" },
        { regex: /Heroku/gi, category: "Hosting" },
        { regex: /DigitalOcean/gi, category: "Hosting" },
        { regex: /Google Cloud/gi, category: "Hosting" },
        { regex: /Azure/gi, category: "Hosting" },
        { regex: /nginx/gi, category: "Web Server" },
        { regex: /Apache/gi, category: "Web Server" },
        // Marketing
        { regex: /HubSpot/gi, category: "Marketing" },
        { regex: /Mailchimp/gi, category: "Email Marketing" },
        { regex: /SendGrid/gi, category: "Email Marketing" },
        { regex: /Intercom/gi, category: "Customer Support" },
        { regex: /Zendesk/gi, category: "Customer Support" },
        { regex: /Drift/gi, category: "Customer Support" },
        { regex: /Crisp/gi, category: "Customer Support" },
        { regex: /Tawk\.to/gi, category: "Customer Support" },
        // Payment
        { regex: /Stripe/gi, category: "Payment" },
        { regex: /PayPal/gi, category: "Payment" },
        { regex: /Square/gi, category: "Payment" },
        // Frameworks / Languages
        { regex: /Django/gi, category: "Backend Framework" },
        { regex: /Rails|Ruby on Rails/gi, category: "Backend Framework" },
        { regex: /Laravel/gi, category: "Backend Framework" },
        { regex: /Express(?:\.?js)?/gi, category: "Backend Framework" },
        { regex: /Spring Boot/gi, category: "Backend Framework" },
        { regex: /Flask/gi, category: "Backend Framework" },
        { regex: /FastAPI/gi, category: "Backend Framework" },
        { regex: /Python/gi, category: "Programming Language" },
        { regex: /Ruby/gi, category: "Programming Language" },
        { regex: /PHP/gi, category: "Programming Language" },
        { regex: /Java(?!\s*Script)/gi, category: "Programming Language" },
        { regex: /TypeScript/gi, category: "Programming Language" },
      ]

      for (const { regex, category } of techPatterns) {
        const matches = html.match(regex)
        if (matches) {
          const name = matches[0].trim()
          if (!entries.find((e) => e.name.toLowerCase() === name.toLowerCase())) {
            entries.push({ name, category })
          }
        }
      }
    } catch {
      // BuiltWith blocked or timed out — fall through to site analysis
    }

    return entries
  }

  private async analyzeSite(domain: string): Promise<TechEntry[]> {
    const entries: TechEntry[] = []

    try {
      const res = await fetch(`https://${domain}`, {
        headers: {
          "User-Agent": "Mozilla/5.0 (compatible; Hyper Agent/1.0)",
          Accept: "text/html",
        },
        signal: AbortSignal.timeout(8000),
        redirect: "follow",
      })

      if (!res.ok) return entries

      // Analyze HTTP headers
      const server = res.headers.get("server") || ""
      const poweredBy = res.headers.get("x-powered-by") || ""
      const via = res.headers.get("via") || ""

      if (server) entries.push({ name: server, category: "Web Server" })
      if (poweredBy) entries.push({ name: poweredBy, category: "Backend Framework" })
      if (via) entries.push({ name: `Via: ${via}`, category: "CDN" })

      // Check for common CDN/hosting headers
      const cfRay = res.headers.get("cf-ray")
      if (cfRay) entries.push({ name: "Cloudflare", category: "CDN" })

      const xAmzCfId = res.headers.get("x-amz-cf-id")
      if (xAmzCfId) entries.push({ name: "AWS CloudFront", category: "CDN" })

      const xVercelId = res.headers.get("x-vercel-id")
      if (xVercelId) entries.push({ name: "Vercel", category: "Hosting" })

      const xNetlify = res.headers.get("x-nf-request-id")
      if (xNetlify) entries.push({ name: "Netlify", category: "Hosting" })

      // Analyze HTML for meta/script clues
      const html = await res.text()

      // Meta generator tag
      const generatorMatch = html.match(/<meta[^>]*name=["']generator["'][^>]*content=["']([^"']+)["']/i)
      if (generatorMatch) entries.push({ name: generatorMatch[1], category: "CMS" })

      // Script sources
      const scriptSrcRegex = /<script[^>]*src=["']([^"']+)["']/gi
      let scriptMatch: RegExpExecArray | null
      while ((scriptMatch = scriptSrcRegex.exec(html)) !== null) {
        const src = scriptMatch[1]
        if (src.includes("gtag") || src.includes("analytics")) entries.push({ name: "Google Analytics", category: "Analytics" })
        if (src.includes("googletagmanager")) entries.push({ name: "Google Tag Manager", category: "Tag Manager" })
        if (src.includes("hotjar")) entries.push({ name: "Hotjar", category: "Analytics" })
        if (src.includes("segment.com") || src.includes("segment.io")) entries.push({ name: "Segment", category: "Analytics" })
        if (src.includes("mixpanel")) entries.push({ name: "Mixpanel", category: "Analytics" })
        if (src.includes("amplitude")) entries.push({ name: "Amplitude", category: "Analytics" })
        if (src.includes("intercom")) entries.push({ name: "Intercom", category: "Customer Support" })
        if (src.includes("zendesk") || src.includes("zdassets")) entries.push({ name: "Zendesk", category: "Customer Support" })
        if (src.includes("drift")) entries.push({ name: "Drift", category: "Customer Support" })
        if (src.includes("crisp")) entries.push({ name: "Crisp", category: "Customer Support" })
        if (src.includes("tawk.to")) entries.push({ name: "Tawk.to", category: "Customer Support" })
        if (src.includes("hubspot")) entries.push({ name: "HubSpot", category: "Marketing" })
        if (src.includes("mailchimp")) entries.push({ name: "Mailchimp", category: "Email Marketing" })
        if (src.includes("stripe")) entries.push({ name: "Stripe", category: "Payment" })
        if (src.includes("paypal")) entries.push({ name: "PayPal", category: "Payment" })
        if (src.includes("sentry")) entries.push({ name: "Sentry", category: "Error Tracking" })
        if (src.includes("newrelic") || src.includes("nr-data")) entries.push({ name: "New Relic", category: "Performance Monitoring" })
        if (src.includes("datadog")) entries.push({ name: "Datadog", category: "Performance Monitoring" })
      }

      // Meta viewport (indicates responsive/mobile-first)
      if (html.includes('name="viewport"')) {
        entries.push({ name: "Responsive Design", category: "Design" })
      }

      // Check for specific frameworks in HTML
      if (html.includes("__NEXT_DATA__")) entries.push({ name: "Next.js", category: "JavaScript Frameworks" })
      if (html.includes("__NUXT__") || html.includes("nuxt")) entries.push({ name: "Nuxt.js", category: "JavaScript Frameworks" })
      if (html.includes('id="__vite_ssr"') || html.includes("vite")) entries.push({ name: "Vite", category: "Build Tool" })
      if (html.includes("wp-content") || html.includes("wp-includes")) entries.push({ name: "WordPress", category: "CMS" })
      if (html.includes("Shopify")) entries.push({ name: "Shopify", category: "E-Commerce" })
      if (html.includes("react-root") || html.includes("__react")) entries.push({ name: "React", category: "JavaScript Frameworks" })
      if (html.includes("ng-version") || html.includes("ng-app")) entries.push({ name: "Angular", category: "JavaScript Frameworks" })
      if (html.includes("data-v-") || html.includes("vue")) entries.push({ name: "Vue.js", category: "JavaScript Frameworks" })
      if (html.includes("svelte")) entries.push({ name: "Svelte", category: "JavaScript Frameworks" })
      if (html.includes("tailwindcss") || html.includes("tailwind")) entries.push({ name: "Tailwind CSS", category: "CSS Framework" })
      if (html.includes("bootstrap")) entries.push({ name: "Bootstrap", category: "CSS Framework" })

      // Check for SSL/HTTPS
      if (res.url.startsWith("https")) {
        entries.push({ name: "HTTPS", category: "Security" })
      }
    } catch {
      // Site unreachable — no analysis possible
    }

    return entries
  }
}

export default new BuiltWithSource()
