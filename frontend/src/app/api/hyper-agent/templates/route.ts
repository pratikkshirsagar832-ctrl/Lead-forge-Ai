import { NextResponse } from "next/server"
import { EMAIL_TEMPLATES } from "@/lib/hyper-agent/templates/email-templates"
import { SEARCH_TEMPLATES } from "@/lib/hyper-agent/templates/search-templates"
import { EXPORT_TEMPLATES } from "@/lib/hyper-agent/templates/export-templates"

export async function GET() {
  try {
    return NextResponse.json({
      email: EMAIL_TEMPLATES,
      search: SEARCH_TEMPLATES,
      export: EXPORT_TEMPLATES,
      totals: {
        email: EMAIL_TEMPLATES.length,
        search: SEARCH_TEMPLATES.length,
        export: EXPORT_TEMPLATES.length,
      },
    })
  } catch (error) {
    console.error("Error in GET:", error)
    return NextResponse.json({ error: "Internal server error" }, { status: 500 })
  }
}
