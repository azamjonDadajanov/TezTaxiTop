import { useEffect } from 'react'
import { BrowserRouter, Navigate, Outlet, Route, Routes, useNavigate } from 'react-router-dom'
import { ArrowRight, CarFront, CircleAlert, ShieldCheck } from 'lucide-react'
import { AuthProvider } from './auth'
import { useAuth } from './authContext'
import { AppLayout } from './components/AppLayout'
import { DashboardPage } from './pages/DashboardPage'
import { AccountPage } from './pages/AccountPage'
import { TripsPage, RequestsPage, MatchingPage } from './pages/RidePages'
import { OrdersPage, SubscriptionPage, PaymentsPage } from './pages/CommercePages'
import { VehiclesPage } from './pages/VehiclesPage'
import { NotificationsPage, ChatPage, ReviewsPage, SupportPage } from './pages/CommunicationPages'
import { DriverMapPage, PassengerMapPage } from './pages/MapPages'

function AuthGate() {
  const { user, checking, authError, signInWithTelegram } = useAuth()
  const telegramUser = window.Telegram?.WebApp?.initDataUnsafe?.user
  const botUsername = import.meta.env.VITE_TELEGRAM_BOT_USERNAME as string | undefined

  if (checking) return <div className="boot-screen"><div className="brand-mark"><CarFront size={23} /></div><span>Hisob tekshirilmoqda</span></div>
  if (user) return <Outlet />

  return (
    <main className="auth-screen">
      <div className="auth-orbit auth-orbit-one" />
      <div className="auth-orbit auth-orbit-two" />
      <section className="auth-panel">
        <div className="brand-lockup"><span className="brand-mark"><CarFront size={23} /></span><span>tez<span className="brand-top">taxi</span>top</span></div>
        <div className="auth-kicker"><span className="live-dot" /> TELEGRAM MINI APP</div>
        <h1>Shahar sizga yaqinroq.</h1>
        <p className="auth-copy">Yo‘lov toping, buyurtmani boshqaring va safaringizni bir joyda kuzating.</p>
        <div className="auth-route" aria-hidden="true"><span className="route-pin route-start" /><span className="route-line" /><span className="route-pin route-end" /><span className="route-label route-from">Toshkent</span><span className="route-label route-to">Samarqand</span></div>
        <div className="auth-divider"><span>TELEGRAM ORQALI KIRISH</span></div>
        {telegramUser && <p className="telegram-identity">Telegram: <strong>{telegramUser.first_name} {telegramUser.last_name ?? ''}</strong><br /><small>Hisob Telegram imzolagan sessiya orqali tasdiqlanadi.</small></p>}
        {authError && <p className="inline-error auth-error"><CircleAlert size={15} />{authError}</p>}
        {window.Telegram?.WebApp?.initData ? <button className="button button-dark button-wide" onClick={() => void signInWithTelegram()}><ShieldCheck size={16} />Telegram bilan qayta kirish <ArrowRight size={17} /></button> : <div className="telegram-required"><ShieldCheck size={18} /><p><strong>Telegram Mini App’ni bot ichidan oching</strong><span>Tasdiqlangan Telegram sessiyasi avtomatik olinadi. Brauzer orqali qo‘lda kirish qo‘llanmaydi.</span></p></div>}
        <div className="bot-verification">
          <span className="bot-icon"><ShieldCheck size={19} /></span>
          <p><strong>Telefon raqami Telegram botda tasdiqlanadi</strong><span>Ilovada telefon raqamini qo‘lda kiritish yoki tasdiqlash mavjud emas.</span></p>
          {botUsername && <a href={`https://t.me/${botUsername}`} target="_blank" rel="noreferrer" aria-label="Telegram botni ochish"><ArrowRight size={17} /></a>}
        </div>
      </section>
      <p className="auth-footnote">TEZTAXITOP <span>·</span> TOSHKENT, O‘ZBEKISTON</p>
    </main>
  )
}

function RoleAccess({ role }: { role: 'passenger' | 'driver' }) {
  const { user } = useAuth()
  const canAccess = role === 'passenger'
    ? user?.role === 'passenger' || user?.role === 'both'
    : (user?.role === 'driver' || user?.role === 'both') && Boolean(user.driver_profile)
  return canAccess ? <Outlet /> : <section className="page-content"><div className="notice notice-warning"><CircleAlert size={18} /><div><strong>Bu bo‘lim uchun ruxsat yo‘q</strong><p>Hisobingizning roli bu amalni bajarishga ruxsat bermaydi. Profil bo‘limidan rolni tanlang.</p></div></div></section>
}

function ApplicationRoutes() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  if (!user) return <AuthGate />

  return (
    <AppLayout onSignOut={() => { signOut(); navigate('/') }}>
      <Routes>
        <Route index element={<DashboardPage />} />
        <Route path="profile" element={<AccountPage section="profile" />} />
        <Route path="onboarding" element={<AccountPage section="onboarding" />} />
        <Route path="settings" element={<AccountPage section="settings" />} />
        <Route element={<RoleAccess role="driver" />}>
          <Route path="trips" element={<TripsPage />} />
          <Route path="map" element={<DriverMapPage />} />
          <Route path="vehicles" element={<VehiclesPage />} />
          <Route path="subscription" element={<SubscriptionPage />} />
        </Route>
        <Route element={<RoleAccess role="passenger" />}>
          <Route path="requests" element={<RequestsPage />} />
          <Route path="taxi-map" element={<PassengerMapPage />} />
        </Route>
        <Route element={<RoleAccess role={user.role === 'driver' ? 'driver' : 'passenger'} />}>
          <Route path="matching" element={<MatchingPage />} />
        </Route>
        <Route path="orders" element={<OrdersPage />} />
        <Route path="payments" element={<PaymentsPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="chat" element={<ChatPage />} />
        <Route path="reviews" element={<ReviewsPage />} />
        <Route path="support" element={<SupportPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  )
}

export default function App() {
  useEffect(() => {
    const webApp = window.Telegram?.WebApp
    webApp?.ready()
    webApp?.expand()
  }, [])

  return <BrowserRouter><AuthProvider><ApplicationRoutes /></AuthProvider></BrowserRouter>
}
