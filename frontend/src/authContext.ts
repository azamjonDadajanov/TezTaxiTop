import { createContext, useContext } from 'react'
import type { User } from './api'

export type AuthContextValue = {
  user: User | null
  setUser: (user: User | null) => void
  checking: boolean
  authenticate: (token: string) => Promise<User>
  signOut: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be rendered inside AuthContext')
  return value
}