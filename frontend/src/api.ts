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

api.interceptors.response.use((response) => response, (error: unknown) => {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data as Record<string, unknown> | undefined
    const message = typeof data?.detail === 'string'
      ? data.detail
      : typeof data?.error === 'string'
        ? data.error
        : error.response?.status === 401
          ? 'Sessiya yaroqsiz yoki muddati tugagan.'
          : error.message || 'Server bilan bog‘lanib bo‘lmadi.'
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
export type Location = { id: number; name: string; full_name?: string; district_name?: string; region_name?: string }
export type Vehicle = { id: number; brand: string; model: string; plate_number: string; seats_for_passengers?: number; is_usable_for_trip?: boolean }
export type Trip = ApiItem & {
  vehicle: number
  from_location: number
  to_location: number
  from_location_detail?: { name: string; region: string }
  to_location_detail?: { name: string; region: string }
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
  from_location: number
  to_location: number
  from_location_detail?: { name: string; region: string }
  to_location_detail?: { name: string; region: string }
  passenger_count: number
  departure_from?: string | null
  departure_until?: string | null
  max_price_per_seat?: number | string | null
  status: string
  status_display?: string
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
  interface Window { Telegram?: { WebApp?: { ready: () => void; expand: () => void; initDataUnsafe?: { user?: { id: number; first_name: string; last_name?: string; username?: string } } } } }
}