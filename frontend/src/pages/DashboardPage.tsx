import { useQuery } from '@tanstack/react-query'
import { ArrowDownRight, ArrowRight, ArrowUpRight, Bell, CarFront, Clock3, MapPin, Plus, ShieldCheck, Sparkles, UsersRound } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, currentDateLabel, dateTime, endpointLabel, readableError, toArray, type Order, type PassengerRequest, type Trip } from '../api'
import { useAuth } from '../authContext'
import { ContentState, PageHeading, RouteLine, StatusBadge } from '../components/ui'
import { useRoleMode } from './useRoleMode'

export function DashboardPage() {
  const { user } = useAuth()
  const mode = useRoleMode()
  const isDriver = mode === 'driver'
  const trips = useQuery({ queryKey: ['dashboard-trips', isDriver], queryFn: async () => toArray((await api.get<Trip[] | { results: Trip[] }>(isDriver ? '/rides/trips/my_trips/' : '/rides/requests/')).data) })
  const orders = useQuery({ queryKey: ['dashboard-orders', mode], queryFn: async () => toArray((await api.get<Order[] | { results: Order[] }>(`/orders/orders/my_orders/?role=${mode}`)).data) })
  const unread = useQuery({ queryKey: ['notifications-unread'], queryFn: async () => (await api.get<{ unread: number }>('/notifications/notifications/unread_count/')).data })
  const activeTrips = trips.data?.filter((item) => ['active', 'matched', 'in_progress'].includes(String(item.status))).length ?? 0
  const activeOrders = orders.data?.filter((item) => !['completed', 'rejected', 'cancelled_by_passenger', 'cancelled_by_driver'].includes(item.status)).length ?? 0
  const date = currentDateLabel()

  return <>
    <PageHeading eyebrow={date} title={`Assalomu alaykum, ${(user?.first_name || user?.full_name || 'do‘st').split(' ')[0]}`} description={isDriver ? 'Bugungi yo‘lovlaringiz va buyurtmalaringiz shu yerda.' : 'Bugun qayerga yo‘l olamiz?'} action={<Link className="button button-dark" to={isDriver ? '/trips' : '/requests'}><Plus size={17} />{isDriver ? 'Yo‘lov joylash' : 'Safar so‘rash'}</Link>} />
    <div className="dashboard-hero">
      <div className="dashboard-hero-copy"><span className="hero-tag"><Sparkles size={14} /> TEZ, QULAY, ISHONCHLI</span><h2>{isDriver ? 'Yo‘lingizni foydali safarga aylantiring.' : 'Safaringiz uchun eng mos haydovchi topiladi.'}</h2><p>{isDriver ? 'Yangi yo‘lov qo‘shing va yo‘nalishingiz bo‘yicha mos so‘rovlarni ko‘ring.' : 'Manzil va vaqtni belgilang, mos takliflar orasidan tanlang.'}</p><Link className="hero-link" to={isDriver ? '/matching' : '/matching'}>{isDriver ? 'Mos so‘rovlarni ko‘rish' : 'Mos safarlarni qidirish'} <ArrowRight size={16} /></Link></div>
      <div className="hero-map" aria-hidden="true"><div className="map-grid" /><div className="map-route"><span className="map-stop map-stop-a" /><span className="map-path" /><span className="map-stop map-stop-b" /><span className="map-car"><CarFront size={19} /></span></div><span className="map-label map-label-a">TOSHKENT</span><span className="map-label map-label-b">MANZIL</span><span className="map-ring map-ring-one" /><span className="map-ring map-ring-two" /></div>
    </div>
    <div className="metric-grid">
      <div className="metric-block"><div className="metric-icon metric-lime"><CarFront size={18} /></div><span>{isDriver ? 'Faol yo‘lovlar' : 'Faol so‘rovlar'}</span><strong>{trips.data?.length ?? '—'}</strong><small><ArrowUpRight size={13} /> {activeTrips} ta hozir faol</small></div>
      <div className="metric-block"><div className="metric-icon metric-coral"><UsersRound size={18} /></div><span>Buyurtmalar</span><strong>{orders.data?.length ?? '—'}</strong><small><ArrowDownRight size={13} /> {activeOrders} ta ochiq</small></div>
      <div className="metric-block"><div className="metric-icon metric-teal"><Bell size={18} /></div><span>Bildirishnomalar</span><strong>{unread.data?.unread ?? '—'}</strong><small>O‘qilmagan xabarlar</small></div>
      <div className="metric-block"><div className="metric-icon metric-dark"><ShieldCheck size={18} /></div><span>{isDriver ? 'Haydovchi holati' : 'Telefon holati'}</span><strong className="metric-status">{isDriver ? user?.driver_profile?.is_verified ? 'Tasdiqlangan' : 'Tekshiruvda' : user?.phone_number ? 'Tasdiqlangan' : 'Bot orqali'}</strong><small>{isDriver ? user?.driver_profile?.has_active_subscription ? 'Obuna faol' : 'Obuna kerak' : 'Faqat Telegram botda'}</small></div>
    </div>
    <div className="dashboard-lower">
      <section className="section-block"><div className="section-heading"><div><span className="eyebrow">YANGI FAOLLIK</span><h2>{isDriver ? 'Mening yo‘lovlarim' : 'Mening so‘rovlarim'}</h2></div><Link className="section-link" to={isDriver ? '/trips' : '/requests'}>Barchasi <ArrowRight size={15} /></Link></div>
        <ContentState loading={trips.isLoading} error={trips.error ? readableError(trips.error) : undefined} empty={trips.data?.length === 0} onRetry={() => void trips.refetch()}>
          <div className="compact-list">{trips.data?.slice(0, 3).map((item) => {
            const request = item as unknown as PassengerRequest
            const trip = item as Trip
            return <article className="compact-item" key={item.id}><RouteLine from={endpointLabel(trip.origin, trip.from_location_detail) || endpointLabel(request.origin, request.from_location_detail)} to={endpointLabel(trip.destination, trip.to_location_detail) || endpointLabel(request.destination, request.to_location_detail)} /><div className="compact-meta"><span><Clock3 size={14} />{dateTime(trip.departure_time || request.departure_from || undefined)}</span><StatusBadge value={item.status_display || item.status} /></div></article>
          })}</div>
        </ContentState>
      </section>
      <aside className="dashboard-aside"><div className="aside-heading"><span className="eyebrow">TEZKOR HAVOLALAR</span><h2>Bir qadamda</h2></div><Link className="quick-link" to="/matching"><span className="quick-icon quick-match"><MapPin size={18} /></span><span><strong>Safarlarni qidirish</strong><small>Yo‘nalish bo‘yicha mosliklar</small></span><ArrowRight size={16} /></Link><Link className="quick-link" to="/orders"><span className="quick-icon quick-book"><UsersRound size={18} /></span><span><strong>Buyurtmalar</strong><small>{activeOrders} ta ochiq buyurtma</small></span><ArrowRight size={16} /></Link><Link className="quick-link" to="/notifications"><span className="quick-icon quick-alert"><Bell size={18} /></span><span><strong>Xabarlar</strong><small>{unread.data?.unread ?? 0} ta yangi bildirishnoma</small></span><ArrowRight size={16} /></Link></aside>
    </div>
  </>
}