import { useEffect, useState } from 'react'
import { useAuth } from '../authContext'

export function useRoleMode() {
  const { user } = useAuth()
  const [mode, setMode] = useState<'passenger' | 'driver'>(() => {
    const saved = localStorage.getItem('teztaxitop_mode')
    return user?.role === 'driver' ? 'driver' : user?.role === 'passenger' ? 'passenger' : saved === 'driver' ? 'driver' : 'passenger'
  })
  useEffect(() => {
    const update = () => setMode(user?.role === 'driver' ? 'driver' : user?.role === 'passenger' ? 'passenger' : localStorage.getItem('teztaxitop_mode') === 'driver' ? 'driver' : 'passenger')
    window.addEventListener('teztaxitop-mode-change', update)
    return () => window.removeEventListener('teztaxitop-mode-change', update)
  }, [user?.role])
  return mode
}