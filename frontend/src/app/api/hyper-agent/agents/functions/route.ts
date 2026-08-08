import { NextRequest, NextResponse } from "next/server"

/**
 * OpenAI-compatible Function Calling API
 * 
 * POST /api/agents/functions
 * 
 * Allows AI agents to call Hyper Agent functions using the standard
 * OpenAI function calling format. Works with any LLM that supports
 * function calling (OpenAI, Anthropic, OpenRouter, etc.)
 */

const FUNCTIONS = [
  {
    name: "Hyper Agent_search_leads",
    description: "Search for business leads using natural language queries. Supports filtering by name, company, title, location, industry.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string", description: "Natural language search query" },
        count: { type: "number", description: "Max results (default 25)" },
        location: { type: "string", description: "Filter by location" },
        industry: { type: "string", description: "Filter by industry" },
      },
      required: ["query"],
    },
  },
  {
    name: "Hyper Agent_verify_email",
    description: "Verify email addresses with 10-layer verification. Returns score 0-100.",
    parameters: {
      type: "object",
      properties: {
        email: { type: "string", description: "Email to verify" },
      },
      required: ["email"],
    },
  },
  {
    name: "Hyper Agent_research_company",
    description: "Deep company research: overview, tech stack, people, funding, competitors.",
    parameters: {
      type: "object",
      properties: {
        company: { type: "string", description: "Company name or domain" },
      },
      required: ["company"],
    },
  },
  {
    name: "Hyper Agent_find_contact",
    description: "Find contact information for a person by name, company, title, or location.",
    parameters: {
      type: "object",
      properties: {
        name: { type: "string", description: "Person's name" },
        company: { type: "string", description: "Company name" },
        title: { type: "string", description: "Job title" },
        location: { type: "string", description: "Location" },
      },
    },
  },
  {
    name: "Hyper Agent_enrich_lead",
    description: "Enrich a lead with additional data from multiple sources.",
    parameters: {
      type: "object",
      properties: {
        email: { type: "string" },
        company: { type: "string" },
        domain: { type: "string" },
      },
    },
  },
  {
    name: "Hyper Agent_get_signals",
    description: "Get intent signals: job changes, hiring, funding, news, social mentions.",
    parameters: {
      type: "object",
      properties: {
        company: { type: "string", description: "Company name" },
        type: { type: "string", enum: ["job_change", "hiring", "funding", "news", "social", "product"] },
      },
      required: ["company"],
    },
  },
  {
    name: "Hyper Agent_score_lead",
    description: "AI lead scoring (0-100) based on ICP fit and intent signals.",
    parameters: {
      type: "object",
      properties: {
        title: { type: "string" },
        company: { type: "string" },
        industry: { type: "string" },
        location: { type: "string" },
      },
    },
  },
  {
    name: "Hyper Agent_export_leads",
    description: "Export leads to CSV, JSON, Excel, vCard, or PDF.",
    parameters: {
      type: "object",
      properties: {
        format: { type: "string", enum: ["csv", "json", "xlsx", "vcard", "pdf"] },
        status: { type: "string", description: "Filter by status" },
      },
      required: ["format"],
    },
  },
]

// List available functions
export async function GET() {
  try {
    return NextResponse.json({
      functions: FUNCTIONS,
      usage: {
        description: "Use these functions with any LLM that supports function calling",
        example: {
          model: "gpt-4o",
          messages: [{ role: "user", content: "Find SaaS founders in SF" }],
          tools: FUNCTIONS.map((f) => ({ type: "function", function: f })),
        },
      },
    })
  } catch (error) {
    console.error("Error in GET:", error)
    return NextResponse.json({ error: "Internal server error" }, { status: 500 })
  }
}

// Execute a function
export async function POST(request: NextRequest) {
  try {
    const { name, arguments: args } = await request.json()

    const API_URL = process.env.HYPER_AGENT_API_URL || process.env.NEXT_PUBLIC_BASE_URL || "http://localhost:3000"

    let result: unknown

    switch (name) {
      case "Hyper Agent_search_leads": {
        const resp1 = await fetch(`${API_URL}/api/leads`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(args),
          signal: AbortSignal.timeout(10000),
        })
        if (!resp1.ok) throw new Error(`HTTP ${resp1.status}`)
        result = await resp1.json()
        break
      }

      case "Hyper Agent_verify_email": {
        const resp2 = await fetch(`${API_URL}/api/verify`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ emails: [args.email] }),
          signal: AbortSignal.timeout(10000),
        })
        if (!resp2.ok) throw new Error(`HTTP ${resp2.status}`)
        result = await resp2.json()
        break
      }

      case "Hyper Agent_research_company": {
        const resp3 = await fetch(`${API_URL}/api/research`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: args.company }),
          signal: AbortSignal.timeout(10000),
        })
        if (!resp3.ok) throw new Error(`HTTP ${resp3.status}`)
        result = await resp3.json()
        break
      }

      case "Hyper Agent_find_contact": {
        const query = `Find ${args.name || "contact"} ${args.company ? `at ${args.company}` : ""} ${args.title || ""} ${args.location ? `in ${args.location}` : ""}`
        const resp4 = await fetch(`${API_URL}/api/leads`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query, count: 10 }),
          signal: AbortSignal.timeout(10000),
        })
        if (!resp4.ok) throw new Error(`HTTP ${resp4.status}`)
        result = await resp4.json()
        break
      }

      default:
        return NextResponse.json({ error: `Unknown function: ${name}` }, { status: 400 })
    }

    return NextResponse.json({ name, result })
  } catch (error) {
    return NextResponse.json({ error: "Function execution failed" }, { status: 500 })
  }
}
