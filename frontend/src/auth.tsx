import { useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, readableError, setAuthToken, type User } from './api'
import { AuthContext } from './authContext'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [userOverride, setUserOverride] = useState<User | null>(null)
  const [signedOut, setSignedOut] = useState(false)
  const initData = window.Telegram?.WebApp?.initData ?? ''
  const authQuery = useQuery({
    queryKey: ['telegram-mini-app-auth', initData],
    enabled: Boolean(initData),
    retry: false,
    queryFn: async () => {
      const { data } = await api.post<{ token: string; user: User }>(
        '/auth/telegram-mini-app/',
        { init_data: initData },
      )
      setAuthToken(data.token)
      localStorage.setItem('teztaxitop_token', data.token)
      return data
    },
  })
  const user = signedOut ? null : userOverride ?? authQuery.data?.user ?? null
  const checking = Boolean(initData) && authQuery.isPending
  const authError = !initData
    ? 'Telegram sessiya ma’lumoti topilmadi. Mini App’ni TezTaxiTop botidan oching.'
    : authQuery.error
      ? readableError(authQuery.error)
      : ''

  useEffect(() => {
    const webApp = window.Telegram?.WebApp
    webApp?.ready()
    webApp?.expand()
  }, [])

  async function signInWithTelegram() {
    setSignedOut(false)
    await authQuery.refetch()
  }

  function signOut() {
    setSignedOut(true)
    setUserOverride(null)
    localStorage.removeItem('teztaxitop_token')
    setAuthToken(null)
  }

  return <AuthContext.Provider value={{ user, setUser: setUserOverride, checking, authError, signInWithTelegram, signOut }}>{children}</AuthContext.Provider>
}