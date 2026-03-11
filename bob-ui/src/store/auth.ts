import { createContext, useContext, useState, useEffect, ReactNode, createElement, useCallback } from 'react'
import { setOnAuthError, setOnTokenRefresh } from '../api/client'

const STORAGE_KEY = 'bob_auth'

export interface AuthUser {
  id: string
  email: string
  name: string
  tenant_id: string
}

export interface AuthState {
  token: string | null
  tenantSlug: string | null
  user: AuthUser | null
}

interface AuthCtx {
  auth: AuthState
  isAuthenticated: boolean
  login: (token: string, tenantSlug: string) => Promise<void>
  logout: () => void
}

const defaults: AuthState = { token: null, tenantSlug: null, user: null }

function load(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? { ...defaults, ...JSON.parse(raw) } : defaults
  } catch {
    return defaults
  }
}

const Ctx = createContext<AuthCtx>({
  auth: defaults,
  isAuthenticated: false,
  login: async () => {},
  logout: () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuth] = useState<AuthState>(load)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(auth))
  }, [auth])

  const login = useCallback(async (token: string, tenantSlug: string) => {
    // Fetch user profile
    const res = await fetch('/api/v1/auth/me', {
      headers: {
        Authorization: `Bearer ${token}`,
        'X-Tenant-ID': tenantSlug,
      },
    })
    if (!res.ok) throw new Error('Failed to load profile')
    const user = await res.json()
    setAuth({ token, tenantSlug, user })
  }, [])

  const logout = useCallback(() => {
    setAuth(defaults)
    localStorage.removeItem(STORAGE_KEY)
  }, [])

  // Silently update JWT when the backend sends a refreshed token
  const updateToken = useCallback((newToken: string) => {
    setAuth(prev => prev.token ? { ...prev, token: newToken } : prev)
  }, [])

  // Register auto-logout on 401 and auto-refresh on X-New-Token
  useEffect(() => {
    setOnAuthError(logout)
    setOnTokenRefresh(updateToken)
    return () => {
      setOnAuthError(null)
      setOnTokenRefresh(null)
    }
  }, [logout, updateToken])

  const isAuthenticated = !!auth.token && !!auth.user

  return createElement(Ctx.Provider, { value: { auth, isAuthenticated, login, logout } }, children)
}

export function useAuth() {
  return useContext(Ctx)
}
