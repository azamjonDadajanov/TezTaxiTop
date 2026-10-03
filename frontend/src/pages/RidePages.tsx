import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CalendarClock, CarFront, CircleAlert, MapPin, Plus, RefreshCw, Search, UsersRound } from 'lucide-react'
import { api, dateTime, endpointLabel, money, readableError, toArray, type ApiItem, type Order, type PassengerRequest, type RoutePointInput, type Trip, type Vehicle } from '../api'
import { useAuth } from '../authContext'
import { ContentState, EmptyState, FormNotice, PageHeading, RouteLine, StatusBadge } from '../components/ui'
import { RoutePicker, type EndpointKey } from '../components/RoutePicker'
import { useRoleMode } from './useRoleMode'

function localDateTime(value: string) {
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

/** The route endpoints, as the map picker holds them. A driver must place both
 *  pins: this is the only way to create a route, so there is no fallback to a
 *  catalogue entry that is already in the database. */
function useRoutePoints(initial?: { origin: RoutePointInput | null; destination: RoutePointInput | null }) {
  const [points, setPoints] = useState(() => ({ origin: initial?.origin ?? null, destination: initial?.destination ?? null }))
  const [active, setActive] = useState<EndpointKey>((initial?.origin ? 'destination' : 'origin'))
  const set = useCallback((key: EndpointKey, point: RoutePointInput) => setPoints((current) => ({ ...current, [key]: point })), [])
  return { points, active, setActive, set, complete: Boolean(points.origin && points.destination) }
}

/** Recovers the endpoint block of an existing record so editing starts with the
 *  pins where the driver left them instead of on Tashkent. */
function endpointToPoint(endpoint?: Trip['origin']): RoutePointInput | null {
  if (endpoint?.latitude != null && endpoint?.longitude != null) {
    return {
      latitude: endpoint.latitude,
      longitude: endpoint.longitude,
      address: endpoint.address || '',
      place_name: endpoint.name || '',
      region_name: endpoint.region_name || '',
      city_name: endpoint.city_name || '',
      district_name: endpoint.district_name || '',
    }
  }
  return null
}

function TripCreateForm({ editingTrip, onCreated, onCancel }: { editingTrip: Trip | null; onCreated: () => void; onCancel: () => void }) {
  const { points, active, setActive, set, complete } = useRoutePoints(editingTrip ? { origin: endpointToPoint(editingTrip.origin), destination: endpointToPoint(editingTrip.destination) } : undefined)
  const vehicles = useQuery({ queryKey: ['usable-vehicles'], queryFn: async () => toArray((await api.get<Vehicle[] | { results: Vehicle[] }>('/vehicles/vehicles/usable/')).data) })
  const [vehicle, setVehicle] = useState(() => editingTrip ? String(editingTrip.vehicle) : '')
  const [departure, setDeparture] = useState(() => editingTrip ? localDateTime(editingTrip.departure_time) : '')
  const [seats, setSeats] = useState(() => editingTrip?.total_seats ?? 3)
  const [price, setPrice] = useState(() => editingTrip ? String(editingTrip.price_per_seat) : '')
  const [comment, setComment] = useState(() => editingTrip?.comment || '')
  const [error, setError] = useState('')
  const payload = () => ({ vehicle: Number(vehicle), origin: points.origin, destination: points.destination, departure_time: new Date(departure).toISOString(), total_seats: seats, price_per_seat: Number(price), comment })
  const mutation = useMutation({ mutationFn: async () => editingTrip ? api.patch(`/rides/trips/${editingTrip.id}/`, payload()) : api.post('/rides/trips/', payload()), onSuccess: onCreated, onError: (cause) => setError(readableError(cause)) })
  return <form className="inline-create-form" onSubmit={(event) => { event.preventDefault(); setError(''); mutation.mutate() }}><div className="form-title-row"><div><span className="eyebrow">HAYDOVCHI AMALI</span><h2>{editingTrip ? `Yo‘lov #${editingTrip.id} ni tahrirlash` : 'Yangi yo‘lov joylash'}</h2></div><CarFront size={20} /></div>
    <RoutePicker origin={points.origin} destination={points.destination} active={active} onActiveChange={setActive} onChange={set} />
    <div className="field-row"><label>Avtomobil<select required value={vehicle} onChange={(event) => setVehicle(event.target.value)}><option value="">Avtomobilni tanlang</option>{vehicles.data?.map((item) => <option key={item.id} value={item.id}>{item.brand} {item.model} · {item.plate_number}</option>)}</select></label><label>Jo‘nash vaqti<input required type="datetime-local" value={departure} onChange={(event) => setDeparture(event.target.value)} /></label></div>
    <div className="field-row"><label>Yo‘lovchi o‘rni<input type="number" min={1} max={9} required value={seats} onChange={(event) => setSeats(Number(event.target.value))} /></label><label>Bir o‘rin narxi<input type="number" min={0} step="1000" required value={price} onChange={(event) => setPrice(event.target.value)} placeholder="Masalan, 120000" /></label></div>
    <label>Izoh <span className="optional-label">ixtiyoriy</span><input value={comment} onChange={(event) => setComment(event.target.value)} maxLength={500} placeholder="Safar bo‘yicha qo‘shimcha ma’lumot" /></label>
    {vehicles.error && <p className="inline-error"><CircleAlert size={15} />{readableError(vehicles.error)}</p>}
    {!complete && <p className="inline-error"><CircleAlert size={15} />{points.origin ? 'Endi “Qayerga” nuqtasini xaritada tanlang.' : 'Yo‘lni yaratish uchun xaritada “Qayerdan” nuqtasini tanlang.'}</p>}
    {error && <p className="inline-error"><CircleAlert size={15} />{error}</p>}
    {!vehicles.isLoading && vehicles.data?.length === 0 && <div className="notice notice-warning"><CircleAlert size={16} /><p>Yo‘lov joylash uchun faol va tasdiqlangan avtomobil kerak. Avval profil bo‘limidan ro‘yxatdan o‘ting.</p></div>}
    <div className="record-actions"><button className="button button-dark" disabled={mutation.isPending || vehicles.data?.length === 0 || !complete}><Plus size={16} />{mutation.isPending ? 'Saqlanmoqda…' : editingTrip ? 'O‘zgarishlarni saqlash' : 'Yo‘lovni yaratish'}</button>{editingTrip && <button type="button" className="button button-outline" onClick={onCancel}>Bekor qilish</button>}</div>
  </form>
}

export function TripsPage() {
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const mode = useRoleMode()
  const driver = mode === 'driver'
  const trips = useQuery({ queryKey: ['my-trips'], queryFn: async () => toArray((await api.get<Trip[] | { results: Trip[] }>('/rides/trips/my_trips/')).data) })
  const passengerOrders = useQuery({ queryKey: ['my-orders', 'passenger'], queryFn: async () => toArray((await api.get<Order[] | { results: Order[] }>('/orders/orders/my_orders/?role=passenger')).data), enabled: !driver })
  const [actionError, setActionError] = useState('')
  const [editingTrip, setEditingTrip] = useState<Trip | null>(null)
  const actionMutation = useMutation({ mutationFn: async ({ id, action }: { id: number; action: string }) => api.post(`/rides/trips/${id}/${action}/`), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['my-trips'] }); setActionError('') }, onError: (error) => setActionError(readableError(error)) })
  const heading = driver ? ['HAYDOVCHI', 'Mening yo‘lovlarim', 'Joylagan yo‘lovlaringiz, holatlari va boshqaruv amallari.'] : ['YO‘LOVCHI', 'Mening safarlarim', 'Buyurtma bergan safarlaringiz va ularning holati.']
  return <>
    <PageHeading eyebrow={heading[0]} title={heading[1]} description={heading[2]} action={!driver && <a className="button button-outline" href="/matching"><Search size={16} />Safar qidirish</a>} />
    {driver ? <><div className="notice notice-info"><CarFront size={17} /><p>{user?.driver_profile?.is_verified ? 'Haydovchi profili tasdiqlangan.' : 'Haydovchi profili hali tasdiqlanmagan.'} Yo‘lov yaratish uchun faol obuna va tasdiqlangan avtomobil talab qilinadi.</p></div><TripCreateForm key={editingTrip?.id ?? 'new'} editingTrip={editingTrip} onCancel={() => setEditingTrip(null)} onCreated={() => { setEditingTrip(null); void queryClient.invalidateQueries({ queryKey: ['my-trips'] }) }} />{actionError && <p className="inline-error"><CircleAlert size={15} />{actionError}</p>}<ContentState loading={trips.isLoading} error={trips.error ? readableError(trips.error) : undefined} empty={trips.data?.length === 0} onRetry={() => void trips.refetch()}><div className="record-list">{trips.data?.map((trip) => <article className="record-card" key={trip.id}><div className="record-top"><span className="record-id">YO‘LOV #{trip.id}</span><StatusBadge value={trip.status_display || trip.status} /></div><RouteLine from={endpointLabel(trip.origin, trip.from_location_detail)} to={endpointLabel(trip.destination, trip.to_location_detail)} /><div className="record-detail-grid"><span><CalendarClock size={15} />{dateTime(trip.departure_time)}</span><span><UsersRound size={15} />{trip.available_seats} / {trip.total_seats} o‘rin</span><strong>{money(trip.price_per_seat)}</strong></div><div className="record-actions">{!['cancelled', 'completed'].includes(trip.status) && <button className="button button-outline button-small" onClick={() => { setEditingTrip(trip); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>Tahrirlash</button>}{trip.status === 'draft' && <button className="button button-dark button-small" disabled={actionMutation.isPending} onClick={() => actionMutation.mutate({ id: trip.id, action: 'publish' })}>E’lon qilish <ArrowRight size={15} /></button>}{trip.status === 'active' && <button className="button button-outline button-small" onClick={() => actionMutation.mutate({ id: trip.id, action: 'start' })}>Yo‘lga chiqish</button>}{trip.status === 'in_progress' && <button className="button button-dark button-small" onClick={() => actionMutation.mutate({ id: trip.id, action: 'complete' })}>Yakunlash</button>}{['draft', 'active'].includes(trip.status) && <button className="text-button" onClick={() => actionMutation.mutate({ id: trip.id, action: 'cancel' })}>Bekor qilish</button>}</div></article>)}</div></ContentState></> : <ContentState loading={passengerOrders.isLoading} error={passengerOrders.error ? readableError(passengerOrders.error) : undefined} empty={passengerOrders.data?.length === 0} onRetry={() => void passengerOrders.refetch()}><div className="record-list">{passengerOrders.data?.map((order) => <article className="record-card" key={order.id}><div className="record-top"><span className="record-id">SAFAR #{order.id}</span><StatusBadge value={order.status_display || order.status} /></div><RouteLine from={order.trip_route?.split(' → ')[0]} to={order.trip_route?.split(' → ')[1]} /><div className="record-detail-grid"><span><CalendarClock size={15} />{dateTime(order.departure_time)}</span><span><UsersRound size={15} />{order.seats_booked} o‘rin · {order.driver_name}</span><strong>{money(order.total_amount)}</strong></div></article>)}</div></ContentState>}
  </>
}

export function RequestsPage() {
  const queryClient = useQueryClient()
  const [editingRequest, setEditingRequest] = useState<PassengerRequest | null>(null)
  const [route, setRoute] = useState(() => ({ origin: null as RoutePointInput | null, destination: null as RoutePointInput | null }))
  const [active, setActive] = useState<EndpointKey>('origin')
  const [passengers, setPassengers] = useState(1)
  const [maxPrice, setMaxPrice] = useState('')
  const [departureFrom, setDepartureFrom] = useState('')
  const [departureUntil, setDepartureUntil] = useState('')
  const [comment, setComment] = useState('')
  const [error, setError] = useState('')
  const requests = useQuery({ queryKey: ['my-requests'], queryFn: async () => toArray((await api.get<PassengerRequest[] | { results: PassengerRequest[] }>('/rides/requests/')).data) })
  const complete = Boolean(route.origin && route.destination)
  const setRoutePoint = useCallback((key: EndpointKey, point: RoutePointInput) => setRoute((current) => ({ ...current, [key]: point })), [])
  const requestPayload = () => ({ origin: route.origin, destination: route.destination, passenger_count: passengers, max_price_per_seat: maxPrice ? Number(maxPrice) : null, departure_from: departureFrom ? new Date(departureFrom).toISOString() : null, departure_until: departureUntil ? new Date(departureUntil).toISOString() : null, comment })
  const create = useMutation({ mutationFn: async () => editingRequest ? api.patch(`/rides/requests/${editingRequest.id}/`, requestPayload()) : api.post('/rides/requests/', requestPayload()), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['my-requests'] }); setError(editingRequest ? 'So‘rov yangilandi.' : 'So‘rov yuborildi. Mos safarlar qidirilmoqda.'); setEditingRequest(null) }, onError: (cause) => setError(readableError(cause)) })
  const cancel = useMutation({ mutationFn: async (id: number) => api.post(`/rides/requests/${id}/cancel/`), onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['my-requests'] }), onError: (cause) => setError(readableError(cause)) })
  function editRequest(request: PassengerRequest) {
    setEditingRequest(request)
    setRoute({ origin: endpointToPoint(request.origin), destination: endpointToPoint(request.destination) })
    setActive(request.origin ? 'destination' : 'origin')
    setPassengers(request.passenger_count); setMaxPrice(request.max_price_per_seat ? String(request.max_price_per_seat) : ''); setDepartureFrom(request.departure_from ? localDateTime(request.departure_from) : ''); setDepartureUntil(request.departure_until ? localDateTime(request.departure_until) : ''); setComment(String(request.comment || ''))
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  function clearEdit() {
    setEditingRequest(null); setRoute({ origin: null, destination: null }); setActive('origin'); setPassengers(1); setMaxPrice(''); setDepartureFrom(''); setDepartureUntil(''); setComment('')
  }
  return <>
    <PageHeading eyebrow="YO‘LOVCHI" title="Safar so‘rovlari" description="Yo‘nalish va vaqtni yuboring. Backend mos haydovchilarni hisoblaydi." />
    <form className="inline-create-form" onSubmit={(event) => { event.preventDefault(); setError(''); create.mutate() }}><div className="form-title-row"><div><span className="eyebrow">{editingRequest ? `SO‘ROV #${editingRequest.id}` : 'YANGI SO‘ROV'}</span><h2>{editingRequest ? 'So‘rovni tahrirlash' : 'Qayerga boramiz?'}</h2></div><MapPin size={20} /></div><RoutePicker origin={route.origin} destination={route.destination} active={active} onActiveChange={setActive} onChange={setRoutePoint} /><div className="field-row"><label>Yo‘lovchilar<input type="number" min={1} max={8} value={passengers} onChange={(event) => setPassengers(Number(event.target.value))} /></label><label>Maksimal narx / o‘rin<input type="number" min={0} value={maxPrice} onChange={(event) => setMaxPrice(event.target.value)} placeholder="Cheklov yo‘q" /></label></div><div className="field-row"><label>Eng erta vaqt<input type="datetime-local" value={departureFrom} onChange={(event) => setDepartureFrom(event.target.value)} /></label><label>Eng kech vaqt<input type="datetime-local" value={departureUntil} onChange={(event) => setDepartureUntil(event.target.value)} /></label></div><label>Izoh<input value={comment} onChange={(event) => setComment(event.target.value)} maxLength={500} placeholder="Qo‘shimcha istaklar" /></label>{error && <FormNotice message={error} />}{!complete && <p className="inline-error"><CircleAlert size={15} />{route.origin ? 'Endi “Qayerga” nuqtasini xaritada tanlang.' : 'So‘rov yuborish uchun xaritada “Qayerdan” nuqtasini tanlang.'}</p>}<div className="record-actions"><button className="button button-dark" disabled={create.isPending || !complete}><Search size={16} />{create.isPending ? 'Saqlanmoqda…' : editingRequest ? 'O‘zgarishlarni saqlash' : 'Mos safar qidirish'}</button>{editingRequest && <button type="button" className="button button-outline" onClick={clearEdit}>Bekor qilish</button>}</div></form>
    <div className="section-heading section-heading-spaced"><div><span className="eyebrow">HISTORIYA</span><h2>Yuborilgan so‘rovlar</h2></div></div><ContentState loading={requests.isLoading} error={requests.error ? readableError(requests.error) : undefined} empty={requests.data?.length === 0} onRetry={() => void requests.refetch()}><div className="record-list">{requests.data?.map((request) => <article className="record-card" key={request.id}><div className="record-top"><span className="record-id">SO‘ROV #{request.id}</span><StatusBadge value={request.status_display || request.status} /></div><RouteLine from={endpointLabel(request.origin, request.from_location_detail)} to={endpointLabel(request.destination, request.to_location_detail)} /><div className="record-detail-grid"><span><UsersRound size={15} />{request.passenger_count} yo‘lovchi</span><span><CalendarClock size={15} />{dateTime(request.departure_from || undefined)}</span><strong>{request.max_price_per_seat ? `≤ ${money(request.max_price_per_seat)}` : 'Narx erkin'}</strong></div>{request.status === 'active' && <div className="record-actions"><button className="button button-outline button-small" onClick={() => editRequest(request)}>Tahrirlash</button><button className="text-button" onClick={() => cancel.mutate(request.id)}>So‘rovni bekor qilish</button></div>}</article>)}</div></ContentState>
  </>
}

type Match = ApiItem & {
  trip_id?: number
  request_id?: number
  route?: string
  pickup_location?: string
  dropoff_location?: string
  departure_time?: string
  departure_from?: string | null
  departure_until?: string | null
  price_per_seat?: number | string
  available_seats?: number
  required_seats?: number
  driver_name?: string
  driver_rating?: string
  vehicle_name?: string
  plate_number?: string
  passenger_name?: string
  passenger_username?: string
  distance_difference_km?: number | null
  pickup_offset_km?: number | null
  dropoff_offset_km?: number | null
  route_deviation_km?: number | null
  time_difference_minutes?: number
  route_compatible?: boolean
  route_status?: string
  route_match_basis?: 'coordinates' | 'route_identity' | 'incomparable'
  score?: string
  rank?: number
  components?: Record<string, string>
  reasons?: string[]
}

/** One driver trip with the passengers that fit it, exactly as
 *  `GET /matching/trips/suitable-requests/` returns it. `results` is already
 *  ranked by the backend, so the screen renders it in place. */
type SuitableTripGroup = {
  trip_id: number
  route: string
  departure_time: string
  available_seats: number
  total_seats: number
  vehicle_name?: string
  plate_number?: string
  results: Match[]
}

/** Envelope of `GET /matching/trips/suitable-requests/`. */
type SuitablePassengersPayload = { max_score?: string; trips?: SuitableTripGroup[] }

/** The route label as the API writes it (`"A -> B"`), split for the route line. */
function routeEnds(route?: string) {
  const [from, to] = (route || '').split(/\s*->\s*/)
  return { from, to }
}

/** A distance the backend could not measure stays unknown instead of being
 *  shown as a measured zero. */
function kilometres(value?: number | null) {
  return value == null ? '—' : `${value.toFixed(1)} km`
}

/** A pair matched on the pre-geocoding catalogue / city pair has no coordinates,
 *  so there is no kilometre figure to show. `coordinates` is the only basis that
 *  measured anything, and only then may the UI quote the 25 km limit. */
function hasMeasuredRoute(match: Match) {
  return match.route_match_basis === undefined || match.route_match_basis === 'coordinates'
}

function MatchMetric({ value, label }: { value: ReactNode; label: string }) {
  return <span><b>{value}</b><small>{label}</small></span>
}

/** The measurements the backend returned for one matched passenger request.
 *  Nothing here is recomputed in the browser: every number is the value the
 *  matcher measured when it accepted or rejected the pair. */
function MatchMeasurements({ match }: { match: Match }) {
  const measured = hasMeasuredRoute(match)
  return <>
    <div className="match-metrics">
      <MatchMetric value={measured ? `${match.time_difference_minutes ?? 0} daqiqa` : '—'} label="Chuqish farqi" />
      <MatchMetric value={measured ? kilometres(match.pickup_offset_km) : '—'} label="Chiqish nuqtasi farqi" />
      <MatchMetric value={measured ? kilometres(match.dropoff_offset_km) : '—'} label="Tushish nuqtasi farqi" />
      <MatchMetric value={measured ? kilometres(match.distance_difference_km) : '—'} label="Yo‘nalish farqi (maks.)" />
      <MatchMetric value={measured ? kilometres(match.route_deviation_km) : '—'} label="Qo‘shimcha masofa" />
      <MatchMetric value={`${match.required_seats ?? 1} / ${match.available_seats ?? 0}`} label="Kerakli / bo‘sh o‘rin" />
    </div>
    {!measured && <p className="match-note">Koordinata mavjud emas: masofa o‘lcholmadi, moslik katalog yo‘li bo‘yicha tekshirildi.</p>}
  </>
}

/** One suitable passenger, as the backend ranked them (this card never sorts). */
function SuitablePassengerCard({ match }: { match: Match }) {
  return <article className="record-card match-card" data-testid="suitable-passenger">
    <div className="record-top"><span className="record-id">SO‘ROV #{match.request_id} · MOSLIK #{match.rank ?? '—'}</span><span className="score-pill">{match.score ?? '—'} ball</span></div>
    <div className="match-counterparty"><UsersRound size={15} /><span><strong>{match.passenger_name || 'Yo‘lovchi'}</strong> · {match.required_seats ?? 1} yo‘lovchi</span></div>
    <RouteLine from={match.pickup_location || undefined} to={match.dropoff_location || undefined} />
    <div className="record-detail-grid">
      <span><CalendarClock size={15} />Yo‘lovchi vaqti: {dateTime(match.departure_from || undefined)} – {dateTime(match.departure_until || undefined)}</span>
      <span><CalendarClock size={15} />Haydovchi vaqti: {dateTime(match.departure_time)}</span>
      <strong>{money(match.price_per_seat)}</strong>
    </div>
    <MatchMeasurements match={match} />
    {match.route_status ? <div className="match-reasons"><span>{match.route_status}</span></div> : null}
    {match.reasons && match.reasons.length > 0 && <div className="match-reasons">{match.reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>}
  </article>
}

/** The driver's whole "suitable passengers" screen.
 *
 *  There is no selection state and no `<select>`: one call asks the backend which
 *  passengers suit which of the driver's trips, and the answer arrives already
 *  grouped, already filtered and already ranked. A driver with three trips is not
 *  answered for the first one only - every trip that has a match is shown, and a
 *  trip without one is not shown at all.
 */
function DriverSuitablePassengers() {
  const matches = useQuery({ queryKey: ['matching', 'driver-suitable-requests'], queryFn: async () => {
    const { data } = await api.get<SuitablePassengersPayload>('/matching/trips/suitable-requests/')
    return data?.trips ?? []
  } })
  const groups = matches.data ?? []
  return <ContentState
    loading={matches.isLoading}
    loadingLabel="Mos yo‘lovchilar yuklanmoqda…"
    error={matches.error ? readableError(matches.error) : undefined}
    onRetry={() => void matches.refetch()}>
    {groups.length === 0
      ? <EmptyState icon={Search} title="Mos yo‘lovchilar topilmadi." description="Hozircha hech qanday faol yo‘lovingizga mos keladigan so‘rov yo‘q. Yangi so‘rovlar qo‘shilsa bu sahifa o‘zi yangilanadi." />
      : <div className="trip-match-groups" data-testid="suitable-passenger-groups">
          {groups.map((group) => <section className="form-section trip-match-group" data-testid="suitable-trip-group" key={group.trip_id}>
            <div className="section-heading">
              <div><span className="eyebrow">YO‘LOV #{group.trip_id}</span><h2><RouteLine from={routeEnds(group.route).from} to={routeEnds(group.route).to} /></h2></div>
              <StatusBadge value="active" />
            </div>
            <div className="record-detail-grid">
              <span><CalendarClock size={15} />{dateTime(group.departure_time)}</span>
              <span><UsersRound size={15} />{group.available_seats} / {group.total_seats} o‘rin</span>
              <span><CarFront size={15} />{group.vehicle_name || 'Avtomobil'}</span>
              <strong>{group.results.length} ta mos so‘rov</strong>
            </div>
            <div className="record-list">{group.results.map((match) => <SuitablePassengerCard key={match.request_id ?? match.id} match={match} />)}</div>
          </section>)}
        </div>}
  </ContentState>
}

/** The passenger side of the matching screen.
 *
 *  Ranking is per request, so a passenger with several requests has to say which
 *  one they mean - but nothing is chosen *for* them: no `choices[0]`, no silent
 *  fallback. A single request is unambiguous and opens on its own; several are
 *  listed and the passenger picks explicitly.
 */
function PassengerSuitableTrips() {
  const queryClient = useQueryClient()
  const requests = useQuery({ queryKey: ['my-requests'], queryFn: async () => toArray((await api.get<PassengerRequest[] | { results: PassengerRequest[] }>('/rides/requests/')).data) })
  const [chosen, setChosen] = useState('')
  const [notice, setNotice] = useState('')
  const open = useMemo(() => requests.data ?? [], [requests.data])
  // An explicit choice wins, and it survives a refetch only while it is still one
  // of the open requests. With exactly one open request there is nothing to
  // choose - that is not `choices[0]`, it is the only candidate - so it opens on
  // its own. With several, nothing is preselected.
  const explicit = open.some((item) => String(item.id) === chosen) ? chosen : ''
  const selected = explicit || (open.length === 1 ? String(open[0].id) : '')
  const active = open.find((item) => String(item.id) === selected)
  const matches = useQuery({ queryKey: ['matching', 'passenger-trips', selected], enabled: Boolean(selected), queryFn: async () => {
    const { data } = await api.get<{ results?: Match[] } | Match[]>(`/matching/requests/${selected}/trips/`)
    return Array.isArray(data) ? data : data.results ?? []
  } })
  const refresh = useMutation({ mutationFn: async () => api.post(`/matching/requests/${selected}/refresh/`), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['matching', 'passenger-trips', selected] }); setNotice('Mosliklar qayta hisoblandi.') }, onError: (cause) => setNotice(readableError(cause)) })
  const order = useMutation({ mutationFn: async (tripId: number) => api.post('/orders/orders/', { trip: tripId, seats_booked: active?.passenger_count ?? 1 }), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['my-orders'] }); setNotice('Buyurtma haydovchiga yuborildi.') }, onError: (cause) => setNotice(readableError(cause)) })
  const list = matches.data ?? []
  return <>
    <section className="form-section match-picker">
      <div className="request-picker" data-testid="passenger-request-picker">
        {open.length === 0
          ? <p className="match-note">Faol so‘rov yo‘q. Avval yo‘nalish va vaqtni ko‘rsatib so‘rov yarating.</p>
          : <div className="picker-tab-row">{open.map((item) => <button key={item.id} type="button" className={`picker-tab${String(item.id) === selected ? ' picker-tab-active' : ''}`} onClick={() => setChosen(String(item.id))} data-testid="passenger-request-option">
              <span><strong>So‘rov #{item.id}</strong><small>{endpointLabel(item.origin, item.from_location_detail) || 'Manzil'} → {endpointLabel(item.destination, item.to_location_detail) || 'Manzil'}</small></span>
            </button>)}</div>}
      </div>
      {active && <button className="button button-outline button-small" disabled={!selected || refresh.isPending} onClick={() => refresh.mutate()}><RefreshCw size={15} />Qayta qidirish</button>}
    </section>
    {notice && <FormNotice message={notice} />}
    {open.length === 0
      ? <EmptyState icon={Search} title="Faol so‘rov yo‘q" description="Mos safarlarni ko‘rish uchun avval yo‘nalishni belgilagan so‘rov yarating." />
      : !selected
        ? <EmptyState icon={Search} title="Qaysi so‘rovni ko‘ramiz?" description={open.length > 1 ? 'Yuqoridagi so‘rovlardan birini tanlang — mos safarlar shu so‘rov uchun hisoblanadi.' : 'So‘rov yuklanmoqda…'} />
        : <ContentState loading={matches.isLoading} loadingLabel="Mos safarlar yuklanmoqda…" error={matches.error ? readableError(matches.error) : undefined} onRetry={() => void matches.refetch()}>
            {list.length === 0
              ? <EmptyState icon={Search} title="Bu so‘rov uchun mos safarlar topilmadi." description="Yo‘nalish, chuqish vaqti yoki bo‘sh o‘rinlar bo‘yicha mos variant topilmadi." />
              : <div className="record-list">{list.map((match) => <article className="record-card match-card" key={match.trip_id ?? match.id}>
                  <div className="record-top"><span className="record-id">MOSLIK {match.rank ? `#${match.rank}` : ''}</span><span className="score-pill">{match.score ?? '—'} ball</span></div>
                  <RouteLine from={routeEnds(match.route).from} to={routeEnds(match.route).to} />
                  <div className="record-detail-grid">
                    <span><CalendarClock size={15} />{dateTime(match.departure_time)}</span>
                    <span><UsersRound size={15} />{match.available_seats ?? 0} ta bo‘sh o‘rin · {match.driver_name || 'Haydovchi'}</span>
                    <strong>{money(match.price_per_seat)}</strong>
                  </div>
                  <MatchMeasurements match={match} />
                  {match.reasons && match.reasons.length > 0 && <div className="match-reasons">{match.reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>}
                  <div className="record-actions"><button className="button button-dark button-small" onClick={() => order.mutate(match.trip_id!)} disabled={order.isPending || !match.available_seats}>Buyurtma yuborish <ArrowRight size={15} /></button></div>
                </article>)}</div>}
          </ContentState>}
  </>
}

export function MatchingPage() {
  const mode = useRoleMode()
  const passenger = mode === 'passenger'
  return <>
    <PageHeading
      eyebrow="MOSLASHTIRISH"
      title={passenger ? 'Sizga mos safarlar' : 'Mos yo‘lovchi so‘rovlari'}
      description={passenger
        ? 'Moslik serverda hisoblanadi: yo‘nalish (25 km), chuqish vaqti (±1 soat) va bo‘sh o‘rinlar. Reyting bo‘yicha tartiblangan.'
        : 'Har bir yo‘lovingiz uchun mos yo‘lovchilar avtomatik topiladi: yo‘nalish (25 km), yo‘nalish yo‘nalishi (bir xil yo‘na), chuqish vaqti (±1 soat) va bo‘sh o‘rinlar bo‘yicha. Tanlash yoki qidirish shart emas.'} />
    {passenger ? <PassengerSuitableTrips /> : <DriverSuitablePassengers />}
  </>
}