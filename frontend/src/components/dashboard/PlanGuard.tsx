"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Zap, Crown, ArrowRight, Lock } from "lucide-react"
import Link from "next/link"
import api from "@/lib/api"

const PRO_OR_AGENCY = ["pro", "agency"]

export default function PlanGuard({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    api
      .get("/api/subscriptions/current")
      .then((r) => {
        const plan = (r.data?.plan_name || "").toLowerCase()
        if (!PRO_OR_AGENCY.includes(plan)) {
          setOpen(true)
        }
      })
      .catch(() => {
        setOpen(true)
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96 text-steel">
        <div className="animate-spin rounded-full h-8 w-8 border-t-2 border-violet mb-3" />
      </div>
    )
  }

  if (open) {
    return (
      <Dialog open={open} onOpenChange={() => {}}>
        <DialogContent className="bg-ocean border-violet/30 max-w-md" onPointerDownOutside={(e) => e.preventDefault()} onEscapeKeyDown={(e) => e.preventDefault()}>
          <DialogHeader>
            <div className="mx-auto mb-3 h-14 w-14 rounded-full bg-violet/20 flex items-center justify-center">
              <Lock className="h-7 w-7 text-violet" />
            </div>
            <DialogTitle className="text-center text-xl text-offwhite">
              Pro or Agency Plan Required
            </DialogTitle>
            <DialogDescription className="text-center text-steel mt-2">
              AI-powered LinkedIn lead generation is exclusively available on <span className="text-cyan font-semibold">Pro</span> and <span className="text-emerald font-semibold">Agency</span> plans.
              Upgrade now to unlock AI-powered lead generation.
            </DialogDescription>
          </DialogHeader>

          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-3 bg-navy/60 rounded-lg p-3 border border-steel/10">
              <Crown className="h-5 w-5 text-cyan shrink-0" />
              <div>
                <p className="text-sm text-offwhite font-medium">Pro Plan</p>
                <p className="text-xs text-steel">120 HQ LinkedIn + 1500 GMB leads/mo</p>
              </div>
            </div>
            <div className="flex items-center gap-3 bg-navy/60 rounded-lg p-3 border border-steel/10">
              <Zap className="h-5 w-5 text-emerald shrink-0" />
              <div>
                <p className="text-sm text-offwhite font-medium">Agency Plan</p>
                <p className="text-xs text-steel">400 HQ LinkedIn + 6000 GMB leads/mo + priority</p>
              </div>
            </div>
          </div>

          <div className="mt-5">
            <Link href="/dashboard/billing" className="block">
              <Button variant="default" className="w-full gap-2 py-3 text-base font-bold">
                <ArrowRight className="h-5 w-5" /> Buy Pro or Agency Plan
              </Button>
            </Link>
          </div>
        </DialogContent>
      </Dialog>
    )
  }

  return <>{children}</>
}
