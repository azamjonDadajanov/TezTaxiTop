import { useEffect, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, readableError, setAuthToken, type User } from './api'
import { AuthContext } from './authContext'

const SDK_POLL_INTERVAL_MS = 250
const SDK_POLL_ATTEMPTS = 20

type SdkState = { initData: string; sdkMissing: boolean; probing: boolean }

function readInitData() {
  return window.Telegram?.WebApp?.initData ?? ''
}

function readSdk(): SdkState {
  const initData = readInitData()
  if (initData) return { initData, sdkMissing: false, probing: false }
  return { initData: '', sdkMissing: !window.Telegram?.WebApp, probing: true }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [userOverride, setUserOverride] = useState<User | null>(null)
  const [signedOut, setSignedOut] = useState(false)
  // window.Telegram only exists once telegram-web-app.js has executed. Reading
  // it straight into the render would freeze an empty value when the SDK is
  // slow or blocked, leaving `enabled` false forever and no request ever sent.
  const [sdk, setSdk] = useState(readSdk)
  const { initData, sdkMissing, probing } = sdk

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
  const checking = probing || (Boolean(initData) && authQuery.isPending)
  const authError = sdkMissing
    ? 'Telegram SDK yuklanmadi. Internet aloqasini tekshiring va sahifani yangilang.'
    : !initData
      ? 'Telegram sessiya ma’lumoti topilmadi. Bu Mini App faqat TezTaxiTop botidan ochilganda ishlaydi.'
      : authQuery.error
        ? readableError(authQuery.error)
        : ''

  useEffect(() => {
    const webApp = window.Telegram?.WebApp
    webApp?.ready()
    webApp?.expand()

    if (readInitData()) return

    let attempts = 0
    const timer = window.setInterval(() => {
      attempts += 1
      const data = readInitData()
      if (data) {
        setSdk({ initData: data, sdkMissing: false, probing: false })
        window.clearInterval(timer)
        return
      }
      if (attempts >= SDK_POLL_ATTEMPTS) {
        setSdk({ initData: '', sdkMissing: !window.Telegram?.WebApp, probing: false })
        window.clearInterval(timer)
      }
    }, SDK_POLL_INTERVAL_MS)

    return () => window.clearInterval(timer)
  }, [])

  async function signInWithTelegram() {
    setSignedOut(false)
    const current = readInitData()
    if (current && current !== initData) setSdk({ initData: current, sdkMissing: false, probing: false })
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
