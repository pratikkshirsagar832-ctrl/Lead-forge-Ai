'use client'

import { useEffect, useState, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { supabase } from '@/lib/supabase'
import api, { setLocalToken } from '@/lib/api'
import { Loader2 } from 'lucide-react'

function CallbackContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [error, setError] = useState('')

  useEffect(() => {
    const handleCallback = async () => {
      try {
        const code = searchParams.get('code')
        if (code) {
          const { data, error: exchangeError } = await supabase.auth.exchangeCodeForSession(code)
          if (exchangeError) throw exchangeError

          if (data?.session?.access_token) {
            const res = await api.post('/api/auth/google', {
              access_token: data.session.access_token,
            })
            if (res.data?.token) {
              setLocalToken(res.data.token)
              router.replace('/dashboard')
              return
            }
          }
        }

        const hashParams = new URLSearchParams(window.location.hash.substring(1))
        const accessToken = hashParams.get('access_token')
        const refreshToken = hashParams.get('refresh_token')

        if (accessToken && refreshToken) {
          const { error: sessionError } = await supabase.auth.setSession({
            access_token: accessToken,
            refresh_token: refreshToken,
          })
          if (sessionError) throw sessionError

          const res = await api.post('/api/auth/google', { access_token: accessToken })
          if (res.data?.token) {
            setLocalToken(res.data.token)
            router.replace('/dashboard')
            return
          }
        }

        const { data: { session } } = await supabase.auth.getSession()
        if (session?.access_token) {
          const res = await api.post('/api/auth/google', {
            access_token: session.access_token,
          })
          if (res.data?.token) {
            setLocalToken(res.data.token)
            router.replace('/dashboard')
            return
          }
        }

        throw new Error('No authentication data found')
      } catch (err: any) {
        console.error('Auth callback error:', err)
        setError(err.message || 'Authentication failed')
        setTimeout(() => {
          router.replace('/login?error=auth_config')
        }, 2000)
      }
    }

    handleCallback()
  }, [searchParams, router])

  return (
    <div className="min-h-screen flex items-center justify-center bg-navy font-sans">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="w-6 h-6 text-steel animate-spin" />
        <p className="text-ice/60">Completing sign in...</p>
        {error && <p className="text-rose-400 text-sm">{error}</p>}
      </div>
    </div>
  )
}

export default function AuthCallback() {
  return (
    <Suspense fallback={
      <div className="min-h-screen flex items-center justify-center bg-navy font-sans">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 text-steel animate-spin" />
          <p className="text-ice/60">Loading...</p>
        </div>
      </div>
    }>
      <CallbackContent />
    </Suspense>
  )
}
