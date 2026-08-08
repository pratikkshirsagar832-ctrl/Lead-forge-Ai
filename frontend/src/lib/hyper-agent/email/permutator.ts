// Email Permutator — Generate and verify all possible email combinations
// Given firstName, lastName, domain → generate permutations and score them

interface DNSResponse {
  Status: number
  Answer?: Array<{ name: string; type: number; TTL: number; data: string }>
}

export interface PermutationResult {
  email: string
  pattern: string
  score: number // 0-1 likelihood score
}

export interface VerifiedPermutation {
  email: string
  valid: boolean
  score: number
  pattern: string
  hasMx: boolean
  emailProvider: string
}

// Common free email domains for when no domain is provided
const COMMON_DOMAINS = [
  "gmail.com",
  "outlook.com",
  "yahoo.com",
  "hotmail.com",
  "protonmail.com",
  "icloud.com",
  "aol.com",
  "mail.com",
  "zoho.com",
  "yandex.com",
  "live.com",
]

// Pattern confidence scores (how likely each pattern is used in the wild)
const PATTERN_SCORES: Record<string, number> = {
  "first.last": 0.9, // Most common business pattern
  "firstlast": 0.75,
  "f.last": 0.7,
  "flast": 0.65,
  "first_last": 0.6,
  "first-last": 0.55,
  "last.first": 0.5,
  "lastfirst": 0.45,
  "l.first": 0.4,
  "lfirst": 0.35,
  "first": 0.4,
  "last": 0.35,
  "f.l": 0.3,
  "fl": 0.25,
  "firstl": 0.5,
  "first.l": 0.45,
  "f_last": 0.35,
  "f-l": 0.3,
  "last.f": 0.35,
  "lastf": 0.3,
}

/**
 * Generate all possible email permutations for a person
 * @param firstName - First name (required)
 * @param lastName - Last name (optional, but recommended)
 * @param domain - Target domain (if not provided, tries common free email providers)
 * @returns Array of email permutations with pattern labels and scores
 */
export function generatePermutations(firstName: string, lastName: string, domain?: string): PermutationResult[] {
  const f = firstName.toLowerCase().trim().replace(/[^a-z0-9]/g, "")
  const l = lastName?.toLowerCase().trim().replace(/[^a-z0-9]/g, "") || ""

  if (!f) return []

  const domains = domain ? [domain.toLowerCase()] : COMMON_DOMAINS
  const results: PermutationResult[] = []

  for (const d of domains) {
    if (l) {
      // Full name patterns
      results.push({ email: `${f}.${l}@${d}`, pattern: "first.last", score: PATTERN_SCORES["first.last"] })
      results.push({ email: `${f}${l}@${d}`, pattern: "firstlast", score: PATTERN_SCORES["firstlast"] })
      results.push({ email: `${f[0]}.${l}@${d}`, pattern: "f.last", score: PATTERN_SCORES["f.last"] })
      results.push({ email: `${f[0]}${l}@${d}`, pattern: "flast", score: PATTERN_SCORES["flast"] })
      results.push({ email: `${f}_${l}@${d}`, pattern: "first_last", score: PATTERN_SCORES["first_last"] })
      results.push({ email: `${f}-${l}@${d}`, pattern: "first-last", score: PATTERN_SCORES["first-last"] })
      results.push({ email: `${l}.${f}@${d}`, pattern: "last.first", score: PATTERN_SCORES["last.first"] })
      results.push({ email: `${l}${f}@${d}`, pattern: "lastfirst", score: PATTERN_SCORES["lastfirst"] })
      results.push({ email: `${l[0]}.${f}@${d}`, pattern: "l.first", score: PATTERN_SCORES["l.first"] })
      results.push({ email: `${l[0]}${f}@${d}`, pattern: "lfirst", score: PATTERN_SCORES["lfirst"] })
      results.push({ email: `${f}${l[0]}@${d}`, pattern: "firstl", score: PATTERN_SCORES["firstl"] })
      results.push({ email: `${f}.${l[0]}@${d}`, pattern: "first.l", score: PATTERN_SCORES["first.l"] })
      results.push({ email: `${f[0]}_${l}@${d}`, pattern: "f_last", score: PATTERN_SCORES["f_last"] })
      results.push({ email: `${f[0]}-${l}@${d}`, pattern: "f-l", score: PATTERN_SCORES["f-l"] })
      results.push({ email: `${l}.${f[0]}@${d}`, pattern: "last.f", score: PATTERN_SCORES["last.f"] })
      results.push({ email: `${l}${f[0]}@${d}`, pattern: "lastf", score: PATTERN_SCORES["lastf"] })
    }

    // First-name-only patterns
    results.push({ email: `${f}@${d}`, pattern: "first", score: PATTERN_SCORES["first"] })

    if (l) {
      results.push({ email: `${l}@${d}`, pattern: "last", score: PATTERN_SCORES["last"] })
      results.push({ email: `${f[0]}${l[0]}@${d}`, pattern: "fl", score: PATTERN_SCORES["fl"] })
      results.push({ email: `${f[0]}.${l[0]}@${d}`, pattern: "f.l", score: PATTERN_SCORES["f.l"] })
    }
  }

  // Deduplicate by email
  const seen = new Set<string>()
  return results.filter((r) => {
    if (seen.has(r.email)) return false
    seen.add(r.email)
    return true
  })
}

/**
 * Verify a list of email permutations using DNS MX checks
 * @param emails - Array of email addresses to verify
 * @returns Array of verified permutations with validity status and scores
 */
export async function verifyPermutations(emails: string[]): Promise<VerifiedPermutation[]> {
  if (!emails.length) return []

  // Group by domain to minimize DNS lookups
  const domainGroups = new Map<string, string[]>()
  for (const email of emails) {
    const domain = email.split("@")[1]
    if (!domain) continue
    if (!domainGroups.has(domain)) domainGroups.set(domain, [])
    domainGroups.get(domain)!.push(email)
  }

  // Check MX records for each unique domain
  const domainCache = new Map<string, { hasMx: boolean; provider: string }>()

  for (const domain of domainGroups.keys()) {
    const mxResult = await checkMxRecords(domain)
    domainCache.set(domain, mxResult)
  }

  // Build results
  const results: VerifiedPermutation[] = []

  for (const email of emails) {
    const domain = email.split("@")[1]
    const mxInfo = domainCache.get(domain) || { hasMx: false, provider: "unknown" }

    // Find the pattern for this email
    const local = email.split("@")[0]
    let pattern = "unknown"

    // Detect pattern
    if (local.includes(".")) {
      const parts = local.split(".")
      if (parts[0].length === 1 && parts[1].length === 1) pattern = "f.l"
      else if (parts[0].length === 1) pattern = "f.last"
      else if (parts[1].length === 1) pattern = "first.l"
      else pattern = "first.last"
    } else if (local.includes("_")) {
      const parts = local.split("_")
      pattern = parts[0].length === 1 ? "f_last" : "first_last"
    } else if (local.includes("-")) {
      const parts = local.split("-")
      pattern = parts[0].length === 1 ? "f-l" : "first-last"
    } else if (local.length <= 2) {
      pattern = local.length === 1 ? "first" : "fl"
    }

    const baseScore = PATTERN_SCORES[pattern] || 0.3
    const finalScore = mxInfo.hasMx ? baseScore : baseScore * 0.2

    results.push({
      email,
      valid: mxInfo.hasMx,
      score: Math.round(finalScore * 100) / 100,
      pattern,
      hasMx: mxInfo.hasMx,
      emailProvider: mxInfo.provider,
    })
  }

  return results.sort((a, b) => b.score - a.score)
}

/**
 * All-in-one: generate permutations and verify them
 */
export async function findLikelyEmails(
  firstName: string,
  lastName: string,
  domain?: string
): Promise<VerifiedPermutation[]> {
  const permutations = generatePermutations(firstName, lastName, domain)
  const emails = permutations.map((p) => p.email)
  return verifyPermutations(emails)
}

/**
 * Check if a domain has valid MX records
 */
async function checkMxRecords(domain: string): Promise<{ hasMx: boolean; provider: string }> {
  try {
    const res = await fetch(`https://dns.google/resolve?name=${encodeURIComponent(domain)}&type=MX`, {
      signal: AbortSignal.timeout(5000),
    })
    const data = (await res.json()) as DNSResponse

    if (data.Status !== 0 || !data.Answer?.length) {
      return { hasMx: false, provider: "none" }
    }

    const records = data.Answer.map((a) => a.data).join(" ").toLowerCase()
    let provider = "Custom"
    if (records.includes("google") || records.includes("gmail")) provider = "Google Workspace"
    else if (records.includes("outlook") || records.includes("microsoft")) provider = "Microsoft 365"
    else if (records.includes("proton")) provider = "ProtonMail"
    else if (records.includes("zoho")) provider = "Zoho"
    else if (records.includes("amazon") || records.includes("ses")) provider = "Amazon SES"
    else if (records.includes("yahoo")) provider = "Yahoo"
    else if (records.includes("icloud") || records.includes("apple")) provider = "iCloud"

    return { hasMx: true, provider }
  } catch {
    return { hasMx: false, provider: "unknown" }
  }
}
