"use client"

/**
 * API client with local JWT Bearer token injection.
 * Token is stored in localStorage as 'leadforge_token'.
 */

import axios from "axios"

const isBrowser = typeof window !== "undefined"

const api = axios.create({
  baseURL: isBrowser ? "" : (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"),
})

function getLocalToken(): string | null {
  if (!isBrowser) return null
  return localStorage.getItem("leadforge_token")
}

function setLocalToken(token: string) {
  if (isBrowser) localStorage.setItem("leadforge_token", token)
}

function clearLocalToken() {
  if (isBrowser) localStorage.removeItem("leadforge_token")
}

function redirectToLogin() {
  if (isBrowser && !window.location.pathname.startsWith("/login")) {
    window.location.href = "/login"
  }
}

// Request interceptor — attach Bearer token
api.interceptors.request.use(async (config) => {
  const token = getLocalToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor — on 401, try to refresh token once
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    if (error.response?.status === 401 && isBrowser && !originalRequest._retry) {
      originalRequest._retry = true

      const token = getLocalToken()
      if (!token) {
        redirectToLogin()
        return Promise.reject(error)
      }

      // Token is invalid/expired — clear and redirect to login
      clearLocalToken()
      redirectToLogin()
    }

    return Promise.reject(error)
  },
)

export { getLocalToken, setLocalToken, clearLocalToken }
export default api
