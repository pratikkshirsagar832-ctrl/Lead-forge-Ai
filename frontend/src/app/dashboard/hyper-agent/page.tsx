"use client"

import { useState } from "react"
import { Card } from "@/components/ui/card"
import { Zap, Loader2, RefreshCw } from "lucide-react"

const HYPERAGENT_URL = "/canvas/"

export default function HyperAgentPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(false)

  const handleLoad = () => {
    setLoading(false)
    setError(false)
  }

  const handleError = () => {
    setLoading(false)
    setError(true)
  }

  const handleRetry = () => {
    setLoading(true)
    setError(false)
    const iframe = document.getElementById("hyperagent-iframe") as HTMLIFrameElement
    if (iframe) {
      iframe.src = HYPERAGENT_URL
    }
  }

  return (
    <div className="h-[calc(100vh-2rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="bg-violet/20 rounded-lg p-2">
            <Zap className="w-5 h-5 text-violet" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-offwhite">Hyper Agent</h1>
            <p className="text-xs text-ice/50">AI-powered coding assistant</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRetry}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-ice/60 hover:text-offwhite hover:bg-ocean/30 border border-steel/20 transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
        </div>
      </div>

      {/* Iframe */}
      <Card className="flex-1 bg-ocean border-ocean/20 overflow-hidden relative">
        {loading && !error && (
          <div className="absolute inset-0 flex items-center justify-center bg-navy/80 z-10">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-8 h-8 text-violet animate-spin" />
              <p className="text-sm text-ice/60">Loading HyperAgent...</p>
            </div>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center bg-navy/80 z-10">
            <div className="flex flex-col items-center gap-4 text-center max-w-md">
              <div className="bg-violet/10 rounded-full p-4">
                <Zap className="w-10 h-10 text-violet/50" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-offwhite mb-1">HyperAgent not running</h3>
                <p className="text-sm text-ice/50">
                  The HyperAgent service is not available. Make sure it&apos;s running on{" "}
                  <code className="text-violet bg-violet/10 px-1.5 py-0.5 rounded text-xs">{HYPERAGENT_URL}</code>
                </p>
              </div>
              <button
                onClick={handleRetry}
                className="px-4 py-2 bg-violet/20 hover:bg-violet/30 text-violet rounded-lg text-sm font-medium transition-colors border border-violet/30"
              >
                <RefreshCw className="w-4 h-4 mr-1.5 inline" />
                Try Again
              </button>
            </div>
          </div>
        )}
        <iframe
          id="hyperagent-iframe"
          src={HYPERAGENT_URL}
          onLoad={handleLoad}
          onError={handleError}
          className="w-full h-full border-0"
          title="HyperAgent"
          allow="clipboard-read; clipboard-write; microphone"
        />
      </Card>
    </div>
  )
}
