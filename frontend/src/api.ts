import axios from 'axios'

export const api = axios.create({
  baseURL: (import.meta.env.VITE_API_BASE_URL as string | undefined) || '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 20_000,
})

export function setAuthToken(token: string | null) {
  if (token) api.defaults.headers.common.Authorization = `Token ${token}`
  else delete api.defaults.headers.common.Authorization
}

function messageForStatus(status: number | undefined) {
  switch (status) {
    case 400:
      return 'So‘rov ma’lumotlari noto‘g‘ri.'
    case 401:
      return 'Sessiya yaroqsiz yoki muddati tugagan.'
    case 403:
      return 'Bu amalga shoshhish uchun ruxsat yo‘q.'
    case 404:
      return 'API manzili topilmadi. VITE_API_BASE_URL yoki netlify.toml redirect to‘g‘ri sozlanganmi tekshiring.'
    case 405:
      return 'API manzilida bunday so‘rov usuli mavjud emas.'
    case 429:
      return 'Juda ko‘p so‘rov yuborildi. Biroz kutib turing.'
    case 502:
    case 503:
    case 504:
      return 'Server vaqtincha javob bermayapti. Qayta urinib ko‘ring.'
    default:
      return undefined
  }
}

// Set on the shared instance so it applies to every request the SPA makes.
// Skips the ngrok free-tier browser warning interstitial. Only needed while
// VITE_API_BASE_URL points at an ngrok URL; harmless otherwise. Requires
// CORS_ALLOW_HEADERS on the Django side to include this header.
api.defaults.headers.common['ngrok-skip-browser-warning'] = '1'

api.interceptors.response.use((response) => response, (error: unknown) => {
  if (axios.isAxiosError(error)) {
    // A proxy or SPA host answers 404 with HTML, so `data` is a string and has
    // no `detail`/`error` key. Fall back to a status-specific hint instead of
    // surfacing the raw axios text.
    const status = error.response?.status
    const payload = error.response?.data
    const body = payload && typeof payload === 'object' ? payload as Record<string, unknown> : undefined
    // A business error arrives as `{error: {code, message}}`, so `error` is an
    // object - reading it as a string never matched and every server message was
    // replaced by the generic status hint below.
    const envelope = body?.error && typeof body.error === 'object'
      ? body.error as Record<string, unknown>
      : undefined
    const detail = typeof body?.detail === 'string'
      ? body.detail
      : typeof body?.error === 'string'
        ? body.error
        : typeof envelope?.message === 'string'
          ? envelope.message
          : ''
    const message = detail || messageForStatus(status) || error.message || 'Server bilan bog‘lanib bo‘lmadi.'
    return Promise.reject(new Error(message))
  }
  return Promise.reject(error)
})

export type User = {
  id: number
  telegram_id: number | null
  username: string
  first_name: string
  last_name: string
  full_name: string
  phone_number: string
  role: 'passenger' | 'driver' | 'both'
  role_display: string
  is_active: boolean
  is_blocked: boolean
  language_code: string
  driver_profile?: DriverProfile | null
}

export type DriverProfile = {
  id: number
  is_verified: boolean
  rating: string
  rating_count: number
  total_trips: number
  completed_trips: number
  bio: string
  has_active_subscription: boolean
  subscription_expires_at: string | null
}

export type ApiItem = Record<string, unknown> & { id: number }
export type Vehicle = { id: number; brand: string; model: string; plate_number: string; seats_for_passengers?: number; is_usable_for_trip?: boolean }

/** One route endpoint as the API returns it. `id` is null for a point that was
 *  picked on the map, which is why every read goes through this block instead of
 *  the catalogue FK pair. */
export type RouteEndpoint = {
  id: number | null
  display: string
  name: string
  address: string
  latitude: number | null
  longitude: number | null
  region_name: string
  city_name: string
  district_name: string
  is_catalogue_place: boolean
}

/** One endpoint as the map picker produces it, ready to POST as `origin` /
 *  `destination`. The backend accepts coordinates alone; the text fields only
 *  save it a reverse-geocode round trip. */
export type RoutePointInput = {
  latitude: number
  longitude: number
  address?: string
  place_name?: string
  region_name?: string
  city_name?: string
  district_name?: string
}

/** One 2GIS result proxied by `GET /locations/geo/`. Field names mirror the trip
 *  snapshot columns so the block can be forwarded into the write payload. */
export type ResolvedPlace = {
  place_id: string
  display_name: string
  short_name: string
  full_address: string
  address: string
  latitude: number
  longitude: number
  region_name: string
  city_name: string
  district_name: string
  district_area_name?: string
  living_area_name?: string
}

export type Trip = ApiItem & {
  vehicle: number
  from_location: number | null
  to_location: number | null
  origin?: RouteEndpoint
  destination?: RouteEndpoint
  origin_display?: string
  destination_display?: string
  from_location_detail?: { name: string; region: string } | null
  to_location_detail?: { name: string; region: string } | null
  departure_time: string
  total_seats: number
  comment?: string
  available_seats: number
  price_per_seat: number | string
  status: string
  status_display?: string
  driver_name?: string
  vehicle_brand?: string
  vehicle_model?: string
  vehicle_plate_number?: string
}
export type PassengerRequest = ApiItem & {
  from_location: number | null
  to_location: number | null
  origin?: RouteEndpoint
  destination?: RouteEndpoint
  origin_display?: string
  destination_display?: string
  from_location_detail?: { name: string; region: string } | null
  to_location_detail?: { name: string; region: string } | null
  passenger_count: number
  passenger_name?: string
  comment?: string | null
  created_at?: string
  updated_at?: string
  departure_from?: string | null
  departure_until?: string | null
  max_price_per_seat?: number | string | null
  status: string
  status_display?: string
}

/** One passenger request as the driver map sees it. Same record as
 *  {@link PassengerRequest}, plus the two distances the map draws: `distance_km`
 *  from the driver to the pickup point (it colours the marker) and `trip_km`
 *  from the pickup point to the drop-off (it spans the arrow). `passenger_phone`
 *  is deliberately absent - the map is a broadcast of other people's requests. */
export type NearbyRequest = PassengerRequest & {
  passenger_username?: string
  distance_km: number
  trip_km: number | null
}

/** Envelope of `GET /rides/requests/nearby/`. */
export type NearbyRequests = {
  center: { latitude: number; longitude: number }
  radius_km: number
  count: number
  results: NearbyRequest[]
}
export type Order = ApiItem & {
  trip: number
  trip_route?: string
  departure_time?: string
  passenger_name?: string
  driver_name?: string
  seats_booked: number
  total_amount: number | string
  status: string
  status_display?: string
  can_cancel?: boolean
  is_reviewable?: boolean
}

export function toArray<T>(payload: T[] | { results?: T[] } | undefined): T[] {
  if (Array.isArray(payload)) return payload
  return payload?.results ?? []
}

/** Label for one route endpoint. Reads the unified block first so a map-picked
 *  trip - which has no catalogue FK - still renders a real address instead of
 *  falling back to "Manzil aniqlanmagan". */
export function endpointLabel(endpoint?: RouteEndpoint | null, legacy?: { name?: string } | null) {
  return endpoint?.display || endpoint?.name || endpoint?.address || legacy?.name || undefined
}

/** Turns a 2GIS result into the `origin` / `destination` write block. */
export function placeToRoutePoint(place: ResolvedPlace): RoutePointInput {
  return {
    latitude: place.latitude,
    longitude: place.longitude,
    address: place.address || place.full_address || '',
    place_name: place.short_name || place.display_name || '',
    region_name: place.region_name || '',
    city_name: place.city_name || '',
    district_name: place.district_name || '',
  }
}

export function readableError(error: unknown) {
  return error instanceof Error ? error.message : 'So‘rov bajarilmadi. Qayta urinib ko‘ring.'
}

export function money(value: string | number | undefined) {
  return `${new Intl.NumberFormat('uz-UZ').format(Number(value ?? 0))} so‘m`
}

const uzbekMonths = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr']
const uzbekWeekdays = ['yakshanba', 'dushanba', 'seshanba', 'chorshanba', 'payshanba', 'juma', 'shanba']

function tashkentDateParts(value: Date) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Tashkent',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(value)
  return Object.fromEntries(parts.map(({ type, value: partValue }) => [type, partValue]))
}

export function dateTime(value: string | undefined) {
  if (!value) return 'Vaqt belgilanmagan'
  const parts = tashkentDateParts(new Date(value))
  return `${parts.day}-${uzbekMonths[Number(parts.month) - 1]} ${parts.year} · ${parts.hour}:${parts.minute}`
}

export function currentDateLabel(value = new Date()) {
  const parts = tashkentDateParts(value)
  const weekday = new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Tashkent', weekday: 'short' }).format(value)
  const weekdayIndex = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].indexOf(weekday)
  return `${uzbekWeekdays[weekdayIndex]}, ${parts.day}-${uzbekMonths[Number(parts.month) - 1]}`
}

declare global {
  interface Window { Telegram?: { WebApp?: { initData: string; ready: () => void; expand: () => void; initDataUnsafe?: { user?: { id: number; first_name: string; last_name?: string; username?: string } } } } }
}