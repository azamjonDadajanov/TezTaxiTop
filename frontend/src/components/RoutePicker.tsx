import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { CircleAlert, LoaderCircle, MapPin, Search } from 'lucide-react'
import { api, placeToRoutePoint, readableError, toArray, type ResolvedPlace, type RoutePointInput } from '../api'

export type EndpointKey = 'origin' | 'destination'

const TASHKENT: L.LatLngExpression = [41.311081, 69.240562]

const ENDPOINTS: EndpointKey[] = ['origin', 'destination']

const LABELS: Record<EndpointKey, string> = { origin: 'Qayerdan', destination: 'Qayerga' }

/** Leaflet's bundled marker images 404 under a bundler, and the existing
 *  `.route-pin` rule is absolutely positioned for the auth decoration. A divIcon
 *  keeps the pin self-contained and inherits the palette below. */
function pinIcon(kind: EndpointKey, active: boolean) {
  return L.divIcon({
    className: 'picker-pin-host',
    html: `<span class="picker-pin picker-pin-${kind}${active ? ' picker-pin-active' : ''}"></span>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  })
}

/** Human label for a picked point, for the read-only chip on each tab. */
function describePoint(point: RoutePointInput | null) {
  if (!point) return null
  const parts = [point.address, point.place_name, point.city_name].filter((part): part is string => Boolean(part))
  return parts.length ? [...new Set(parts)].join(', ') : `${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}`
}

export function RoutePicker({ origin, destination, active, onActiveChange, onChange }: {
  origin: RoutePointInput | null
  destination: RoutePointInput | null
  active: EndpointKey
  onActiveChange: (key: EndpointKey) => void
  onChange: (key: EndpointKey, point: RoutePointInput) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const markers = useRef<Partial<Record<EndpointKey, L.Marker>>>({})
  const activeRef = useRef(active)
  const [query, setQuery] = useState('')
  const [notice, setNotice] = useState('')
  const [resolving, setResolving] = useState(false)
  const [ready, setReady] = useState(false)
  const [center, setCenter] = useState<[number, number]>([41.311081, 69.240562])

  useEffect(() => { activeRef.current = active }, [active])

  useEffect(() => {
    if (!container.current || map.current) return
    const instance = L.map(container.current, { center: TASHKENT, zoom: 12 })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap' }).addTo(instance)
    instance.on('moveend', () => {
      const c = instance.getCenter()
      setCenter([c.lat, c.lng])
    })
    map.current = instance
    setReady(true)
    return () => {
      setReady(false)
      instance.remove()
      map.current = null
      markers.current = {}
    }
  }, [])

  const pick = useCallback(async (key: EndpointKey, point: RoutePointInput) => {
    // Drop the pin first so the map always responds, then let 2GIS name it. A
    // failed lookup must not discard the point the driver just chose.
    onChange(key, point)
    setNotice('')
    setResolving(true)
    try {
      const { data } = await api.get<ResolvedPlace>('/locations/geo/reverse/', { params: { lat: point.latitude, lon: point.longitude } })
      if (activeRef.current !== key) return
      onChange(key, placeToRoutePoint(data))
    } catch {
      // Coordinates alone satisfy the backend constraint, so the trip can still
      // be created - it just will not carry a resolved address.
      setNotice('Manzil nomi topilmadi. Nuqta saqlandi, lekin uni aniqlashtirish uchun qayta urinib ko‘ring.')
    } finally {
      setResolving(false)
    }
  }, [onChange])

  // Re-bound on every relevant change so the handler never closes over a stale
  // endpoint or setter.
  useEffect(() => {
    const instance = map.current
    if (!ready || !instance) return
    const handler = (event: L.LeafletMouseEvent) => { void pick(active, { latitude: event.latlng.lat, longitude: event.latlng.lng }) }
    instance.on('click', handler)
    return () => { instance.off('click', handler) }
  }, [ready, active, pick])

  useEffect(() => {
    const instance = map.current
    if (!ready || !instance) return
    const points: Record<EndpointKey, RoutePointInput | null> = { origin, destination }
    for (const key of ENDPOINTS) {
      const point = points[key]
      const existing = markers.current[key]
      if (!point) {
        if (existing) {
          existing.remove()
          delete markers.current[key]
        }
        continue
      }
      const latLng: L.LatLngExpression = [point.latitude, point.longitude]
      if (existing) {
        existing.setLatLng(latLng)
        existing.setIcon(pinIcon(key, key === active))
      } else {
        const marker = L.marker(latLng, { icon: pinIcon(key, key === active), keyboard: true }).addTo(instance)
        marker.on('click', () => onActiveChange(key))
        markers.current[key] = marker
      }
    }
  }, [ready, origin, destination, active, onActiveChange])

  useEffect(() => {
    const instance = map.current
    const point = active === 'origin' ? origin : destination
    if (!ready || !instance || !point) return
    instance.flyTo([point.latitude, point.longitude], Math.max(instance.getZoom(), 14), { duration: 0.5 })
  }, [ready, active, origin, destination])

  const search = useQuery({
    queryKey: ['geo-search', query, center],
    enabled: query.trim().length >= 2,
    staleTime: 60_000,
    queryFn: async () => toArray((await api.get<ResolvedPlace[]>('/locations/geo/', {
      params: { q: query.trim(), lat: center[0], lon: center[1], limit: 8 },
    })).data),
  })

  function choose(place: ResolvedPlace) {
    const key = active
    onChange(key, placeToRoutePoint(place))
    setQuery('')
    setNotice('')
    map.current?.flyTo([place.latitude, place.longitude], Math.max(map.current.getZoom(), 15), { duration: 0.5 })
    onActiveChange(key === 'origin' ? 'destination' : 'origin')
  }

  return <div className="route-picker">
    <div className="picker-tabs" role="tablist">
      {ENDPOINTS.map((key) => <button
        key={key}
        type="button"
        role="tab"
        aria-selected={key === active}
        className={`picker-tab${key === active ? ' picker-tab-active' : ''}`}
        onClick={() => onActiveChange(key)}
      >
        <span className={`picker-tab-dot picker-tab-dot-${key}`} />
        <span className="picker-tab-text">
          <strong>{LABELS[key]}</strong>
          <small>{describePoint(key === 'origin' ? origin : destination) || 'Xaritada nuqta tanlang'}</small>
        </span>
      </button>)}
      {resolving && <LoaderCircle className="spin picker-spinner" size={16} />}
    </div>

    <div className="picker-search">
      <Search size={15} />
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={`${LABELS[active]} — manzil yoki joy nomini yozing`}
      />
    </div>

    {search.isError && <p className="inline-error"><CircleAlert size={15} />{readableError(search.error)}</p>}
    {!!search.data?.length && <ul className="picker-results">
      {search.data.map((place) => <li key={place.place_id}>
        <button type="button" onClick={() => choose(place)}>
          <MapPin size={14} />
          <span><strong>{place.short_name || place.display_name}</strong><small>{place.full_address || place.display_name}</small></span>
        </button>
      </li>)}
    </ul>}
    {search.isSuccess && !search.data?.length && <p className="picker-empty">Hech narsa topilmadi. Xaritada nuqtani bosib tanlang.</p>}
    {notice && <p className="picker-notice"><CircleAlert size={14} />{notice}</p>}

    <div className="picker-map" ref={container} />
    <p className="picker-hint">Xaritada <strong>{LABELS[active]}</strong> nuqtasini bosing yoki yuqoridan qidirib tanlang. Ikkala nuqta ham tanlanmasdan yo‘lovni saqlab bo‘lmaydi.</p>
  </div>
}
