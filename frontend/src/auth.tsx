import { useEffect, useState, type ReactNode } from 'react'
import { api, setAuthToken, type User } from './api'
import { AuthContext } from './authContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(() => Boolean(localStorage.getItem('teztaxitop_token')))

  useEffect(() => {
    const token = localStorage.getItem('teztaxitop_token')
    if (!token) return
    setAuthToken(token)
    api.get<User>('/auth/me/').then(({ data }) => setUser(data)).catch(() => {
      localStorage.removeItem('teztaxitop_token')
      setAuthToken(null)
    }).finally(() => setChecking(false))
  }, [])

  async function authenticate(token: string) {
    const cleanToken = token.trim()
    setAuthToken(cleanToken)
    const { data } = await api.get<User>('/auth/me/')
    localStorage.setItem('teztaxitop_token', cleanToken)
    setUser(data)
    return data
  }

  function signOut() {
    localStorage.removeItem('teztaxitop_token')
    setAuthToken(null)
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, setUser, checking, authenticate, signOut }}>{children}</AuthContext.Provider>
}