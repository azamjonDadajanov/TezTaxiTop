import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import {
  Bell, CarFront, CarTaxiFront, ChevronDown, CircleHelp, CreditCard, LayoutDashboard, LogOut,
  Menu, MapPinned, MessageCircle, MoreHorizontal, NotebookTabs, Repeat2, Settings, ShieldCheck, Sparkles,
  Star, UserRound, UsersRound, WalletCards, X,
} from 'lucide-react'
import { useAuth } from '../authContext'

const allNavigation = [
  { to: '/', label: 'Bosh sahifa', icon: LayoutDashboard, group: 'Asosiy' },
  { to: '/onboarding', label: 'Ro‘yxatdan o‘tish', icon: Sparkles, group: 'Asosiy' },
  { to: '/trips', label: 'Safarlar', icon: CarFront, group: 'Safar' },
  { to: '/map', label: 'Xarita', icon: MapPinned, group: 'Safar' },
  { to: '/taxi-map', label: 'Taksi xaritasi', icon: CarTaxiFront, group: 'Safar' },
  { to: '/vehicles', label: 'Avtomobillar', icon: CarFront, group: 'Safar' },
  { to: '/requests', label: 'So‘rovlar', icon: NotebookTabs, group: 'Safar' },
  { to: '/matching', label: 'Mos safarlar', icon: Repeat2, group: 'Safar' },
  { to: '/orders', label: 'Buyurtmalar', icon: WalletCards, group: 'Safar' },
  { to: '/subscription', label: 'Obuna', icon: ShieldCheck, group: 'Hisob' },
  { to: '/payments', label: 'To‘lovlar', icon: CreditCard, group: 'Hisob' },
  { to: '/notifications', label: 'Bildirishnomalar', icon: Bell, group: 'Aloqa' },
  { to: '/chat', label: 'Chat', icon: MessageCircle, group: 'Aloqa' },
  { to: '/reviews', label: 'Baholar', icon: Star, group: 'Aloqa' },
  { to: '/support', label: 'Yordam', icon: CircleHelp, group: 'Aloqa' },
  { to: '/profile', label: 'Profil', icon: UserRound, group: 'Sozlamalar' },
  { to: '/settings', label: 'Sozlamalar', icon: Settings, group: 'Sozlamalar' },
]

export function AppLayout({ children, onSignOut }: { children: React.ReactNode; onSignOut: () => void }) {
  const { user } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [mode, setMode] = useState<'passenger' | 'driver'>(() => user?.role === 'driver' ? 'driver' : user?.role === 'passenger' ? 'passenger' : localStorage.getItem('teztaxitop_mode') === 'driver' ? 'driver' : 'passenger')
  const isMapPage = location.pathname === '/map' || location.pathname === '/taxi-map'
  useEffect(() => {
    const syncMode = () => setMode(localStorage.getItem('teztaxitop_mode') === 'driver' ? 'driver' : 'passenger')
    window.addEventListener('teztaxitop-mode-change', syncMode)
    return () => window.removeEventListener('teztaxitop-mode-change', syncMode)
  }, [])
  const canPassenger = user?.role === 'passenger' || user?.role === 'both'
  const canDriver = user?.role === 'driver' || user?.role === 'both'
  const navigation = allNavigation.filter((item) => {
    if (item.to === '/trips' || item.to === '/vehicles' || item.to === '/subscription' || item.to === '/map') return canDriver && mode === 'driver'
    if (item.to === '/requests' || item.to === '/taxi-map') return canPassenger && mode === 'passenger'
    if (item.to === '/matching') return mode === 'passenger' ? canPassenger : canDriver
    return true
  })
  const title = allNavigation.find((item) => item.to === location.pathname)?.label || 'TezTaxiTop'
  const displayName = user?.full_name || user?.username || 'Foydalanuvchi'
  const bottomPaths = mode === 'driver'
    ? ['/', '/trips', '/map', '/matching']
    : ['/', '/taxi-map', '/requests', '/matching']
  const bottom = bottomPaths.map((to) => allNavigation.find((item) => item.to === to)).filter((item) => item !== undefined)

  function changeMode(next: 'passenger' | 'driver') {
    setMode(next)
    localStorage.setItem('teztaxitop_mode', next)
    window.dispatchEvent(new Event('teztaxitop-mode-change'))
    const driverOnly = ['/trips', '/map']
    const passengerOnly = ['/requests', '/taxi-map']
    const stranded = next === 'driver' ? passengerOnly.includes(location.pathname) : driverOnly.includes(location.pathname)
    if (stranded) {
      navigate(next === 'driver' ? '/trips' : '/requests')
    }
  }

  return (
    <div className="app-shell">
      {!isMapPage && <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-top">
          <NavLink className="brand-lockup" to="/" onClick={() => setMobileOpen(false)}><span className="brand-mark"><CarFront size={21} /></span><span>tez<span className="brand-top">taxi</span>top</span></NavLink>
          <button className="icon-button sidebar-close" onClick={() => setMobileOpen(false)} aria-label="Menyuni yopish"><X size={19} /></button>
        </div>
        <div className="mode-switch" aria-label="Ish rejimi">
          <button className={mode === 'passenger' ? 'mode-active' : ''} onClick={() => changeMode('passenger')} disabled={!canPassenger}><UsersRound size={16} /><span>Yo‘lovchi</span></button>
          <button className={mode === 'driver' ? 'mode-active' : ''} onClick={() => changeMode('driver')} disabled={!canDriver}><CarFront size={16} /><span>Haydovchi</span></button>
        </div>
        <div className="nav-scroll">
          {['Asosiy', 'Safar', 'Hisob', 'Aloqa', 'Sozlamalar'].map((group) => {
            const items = navigation.filter((item) => item.group === group)
            if (!items.length) return null
            return <div className="nav-group" key={group}><span className="nav-caption">{group}</span>{items.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} onClick={() => setMobileOpen(false)} className={({ isActive }) => `nav-link ${isActive ? 'nav-current' : ''}`} end={to === '/'}><Icon size={18} strokeWidth={1.8} /><span>{label}</span></NavLink>)}</div>
          })}
        </div>
        <div className="sidebar-profile">
          <div className="avatar-small">{displayName.charAt(0).toUpperCase()}</div>
          <div className="sidebar-person"><strong>{displayName}</strong><span>{user?.role_display || user?.role}</span></div>
          <button className="icon-button logout-button" onClick={onSignOut} title="Chiqish" aria-label="Hisobdan chiqish"><LogOut size={17} /></button>
        </div>
      </aside>}
      {mobileOpen && <button className="mobile-scrim" onClick={() => setMobileOpen(false)} aria-label="Menyuni yopish" />}
      <div className={`main-column ${isMapPage ? 'main-column-map' : ''}`}>
        <header className="topbar">
          <button className="icon-button menu-trigger" onClick={() => setMobileOpen(true)} aria-label="Menyuni ochish"><Menu size={20} /></button>
          <div className="crumb"><span>TEZTAXITOP</span><i>/</i><strong>{title}</strong></div>
          <div className="topbar-actions">
            {user?.role === 'both' && <div className="compact-mode"><button onClick={() => changeMode(mode === 'passenger' ? 'driver' : 'passenger')}><Repeat2 size={15} />{mode === 'passenger' ? 'Yo‘lovchi' : 'Haydovchi'}<ChevronDown size={14} /></button></div>}
            <NavLink className="topbar-alert" to="/notifications" aria-label="Bildirishnomalar"><Bell size={18} /><span /></NavLink>
            <NavLink className="avatar-top" to="/profile" aria-label="Profil">{displayName.charAt(0).toUpperCase()}</NavLink>
          </div>
        </header>
        <main className="page-content">{children}</main>
      </div>
      <nav className="mobile-nav" aria-label="Asosiy navigatsiya">
        {bottom.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} className={({ isActive }) => `mobile-nav-link ${isActive ? 'mobile-current' : ''}`}><Icon size={19} /><span>{label === 'So‘rovlar' ? 'So‘rov' : label === 'Buyurtmalar' ? 'Buyurtma' : label === 'Mos safarlar' ? 'Moslik' : label}</span></NavLink>)}
        <button className="mobile-nav-link mobile-more" onClick={() => setMobileOpen(true)}><MoreHorizontal size={19} /><span>Ko‘proq</span></button>
      </nav>
    </div>
  )
}