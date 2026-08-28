"use client"

/**
 * API client — sends Supabase access_token as Bearer on every request.
 * All data operations go through backend API which stores in local PostgreSQL.
 */

import axios from "axios"
import { supabase } from "./supabase"

const isBrowser = typeof window !== "undefined"

const api = axios.create({
  baseURL: isBrowser ? "" : (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"),
})

let _refreshPromise: Promise<boolean> | null = null

api.interceptors.request.use(async (config) => {
  if (isBrowser) {
    const { data: { session } } = await supabase.auth.getSession()
    if (session?.access_token) {
      config.headers.Authorization = `Bearer ${session.access_token}`
    }
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && isBrowser && !originalRequest._retry) {
      originalRequest._retry = true

      try {
        if (!_refreshPromise) {
          _refreshPromise = (async () => {
            const { data: { session } } = await supabase.auth.getSession()
            if (!session) return false

            const { data, error: refreshError } = await supabase.auth.refreshSession()
            if (refreshError || !data?.session) return false

            originalRequest.headers.Authorization = `Bearer ${data.session.access_token}`
            return true
          })()
        }

        const refreshed = await _refreshPromise
        _refreshPromise = null

        if (refreshed) {
          return api(originalRequest)
        }
      } catch {
        _refreshPromise = null
      }

      if (isBrowser && !window.location.pathname.startsWith("/login")) {
        window.location.href = "/login"
      }
    }

    return Promise.reject(error)
  },
)

export default api
