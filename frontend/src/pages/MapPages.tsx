import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { CalendarClock, Compass, Crosshair, Navigation, RefreshCw, Route, UserRound, UsersRound, X, ZoomIn } from 'lucide-react'
import { api, dateTime, endpointLabel, money, readableError, type NearbyRequests, type RouteEndpoint } from '../api'
import { PageHeading, RouteLine, StatusBadge } from '../components/ui'

type LatLng = [number, number]

/** Where the position currently shown comes from, so the UI can say so. */
type PositionSource = 'gps' | 'saved' | 'fallback'

/** Fallback centre when the browser refuses to share a position: Tashkent. */
const TASHKENT: LatLng = [41.311081, 69.240562]

/** How far the map looks for passengers. Matches the API default radius. */
const SEARCH_RADIUS_KM = 25

/** Last known driver position, so a reopen does not have to wait for the GPS. */
const POSITION_KEY = 'teztaxitop_driver_position'

/** Marker colour follows how far away the passenger is: the closer, the hotter. */
const BANDS = [
  { key: 'near', limit: 5, label: '5 km ichida' },
  { key: 'mid', limit: 12, label: '5 – 12 km' },
  { key: 'far', limit: SEARCH_RADIUS_KM, label: '12 – 25 km' },
] as const

/** Compass names for the eight sectors, starting at north. */
const COMPASS = ['shimol', 'shimol-g‘arb', 'g‘arb', 'janub-g‘arb', 'janub', 'janub-sharq', 'sharq', 'shimol-sharq']

/** A person glyph (head + shoulders) drawn in the marker's colour. */
const PERSON_GLYPH = '<svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><circle cx="12" cy="7.2" r="3.4"/><path d="M12 12.2c-4.1 0-7.1 2.7-7.1 6v1.3c0 .8.6 1.4 1.4 1.4h11.4c.8 0 1.4-.6 1.4-1.4v-1.3c0-3.3-3-6-7.1-6z"/></svg>'

/** Solid arrow that points where the passenger wants to go. */
const ARROW_GLYPH = '<svg viewBox="0 0 24 24" width="30" height="30" aria-hidden="true"><path d="M12 1.5 23 22.5H1z"/></svg>'

/** The driver's own dot: ringed so it can never be mistaken for a passenger. */
const DRIVER_GLYPH = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><circle cx="12" cy="12" r="6.5"/></svg>'

function bandFor(distanceKm: number) {
  return BANDS.find((band) => distanceKm <= band.limit)?.key ?? 'far'
}

/** Turns one route endpoint into the pair Leaflet plots, or `null` when the
 *  endpoint has no coordinates (a catalogue-only endpoint resolves server side). */
function endpointLatLng(endpoint?: RouteEndpoint | null): LatLng | null {
  if (endpoint?.latitude == null || endpoint?.longitude == null) return null
  return [Number(endpoint.latitude), Number(endpoint.longitude)]
}

/** Initial great-circle bearing from one point to another, in degrees. */
function bearingDegrees(from: LatLng, to: LatLng) {
  const toRadians = (value: number) => (value * Math.PI) / 180
  const latitude = toRadians(from[0])
  const targetLatitude = toRadians(to[0])
  const deltaLongitude = toRadians(to[1] - from[1])
  const y = Math.sin(deltaLongitude) * Math.cos(targetLatitude)
  const x = Math.cos(latitude) * Math.sin(targetLatitude) - Math.sin(latitude) * Math.cos(targetLatitude) * Math.cos(deltaLongitude)
  return (Math.atan2(y, x) * 180) / Math.PI
}

function compassOf(bearing: number) {
  const normalized = ((bearing % 360) + 360) % 360
  return COMPASS[Math.round(normalized / 45) % 8]
}

function readStoredPosition(): LatLng | null {
  try {
    const raw = localStorage.getItem(POSITION_KEY)
    if (!raw) return null
    const [latitude, longitude] = JSON.parse(raw) as number[]
    return Number.isFinite(latitude) && Number.isFinite(longitude) ? [latitude, longitude] : null
  } catch {
    // Private mode / corrupted value: fall back to the city centre instead.
    return null
  }
}

/** The driver's position, preferring live GPS and degrading to the last known
 *  one (kept in `localStorage`) and finally to the city centre. */
function useDriverPosition() {
  const [state, setState] = useState<{ position: LatLng; source: PositionSource }>(() => {
    const saved = readStoredPosition()
    return { position: saved ?? TASHKENT, source: saved ? 'saved' : 'fallback' }
  })

  const locate = useCallback(() => {
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (result) => {
        const next: LatLng = [result.coords.latitude, result.coords.longitude]
        try {
          localStorage.setItem(POSITION_KEY, JSON.stringify(next))
        } catch {
          // Not being able to cache the position is not a reason to hide it.
        }
        setState({ position: next, source: 'gps' })
      },
      () => setState((current) => (current.source === 'saved' ? current : { ...current, source: 'fallback' })),
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 120_000 },
    )
  }, [])

  useEffect(() => { locate() }, [locate])

  return { ...state, locate }
}

export function DriverMapPage() {
  const container = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const passengerLayer = useRef<L.LayerGroup | null>(null)
  const routeLayer = useRef<L.LayerGroup | null>(null)
  const driverLayer = useRef<L.LayerGroup | null>(null)
  // Marker click handlers are bound once, so they read the latest selection
  // through a ref instead of being re-bound on every render.
  const selectRef = useRef<(id: number) => void>(() => {})
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [focusNonce, setFocusNonce] = useState(0)

  const { position: driver, source, locate } = useDriverPosition()
  const nearby = useQuery({
    queryKey: ['nearby-requests', driver[0], driver[1]],
    refetchInterval: 60_000,
    queryFn: async () => (await api.get<NearbyRequests>('/rides/requests/nearby/', {
      params: { lat: driver[0], lon: driver[1], radius_km: SEARCH_RADIUS_KM },
    })).data,
  })

  const list = useMemo(() => nearby.data?.results ?? [], [nearby.data])
  const selected = useMemo(() => list.find((item) => item.id === selectedId) ?? null, [list, selectedId])
  const origin = endpointLatLng(selected?.origin)
  const destination = endpointLatLng(selected?.destination)
  const heading = origin && destination ? bearingDegrees(origin, destination) : null

  const select = useCallback((id: number) => {
    setSelectedId((current) => (current === id ? null : id))
    setFocusNonce((nonce) => nonce + 1)
  }, [])
  useEffect(() => { selectRef.current = select })

  // The map is created once, on the first position we know; later GPS fixes only
  // move the layers below, so the position is read through a ref here.
  const firstPosition = useRef(driver)
  useEffect(() => { firstPosition.current = driver }, [driver])

  useEffect(() => {
    if (!container.current || map.current) return
    const instance = L.map(container.current, { center: firstPosition.current, zoom: 12 })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '&copy; OpenStreetMap' }).addTo(instance)
    passengerLayer.current = L.layerGroup().addTo(instance)
    routeLayer.current = L.layerGroup().addTo(instance)
    driverLayer.current = L.layerGroup().addTo(instance)
    instance.on('click', () => setSelectedId(null))
    map.current = instance
    return () => {
      instance.remove()
      map.current = null
      passengerLayer.current = null
      routeLayer.current = null
      driverLayer.current = null
    }
  }, [])

  // One coloured person marker per nearby passenger, recoloured when the
  // selection changes so the picked one stands out.
  useEffect(() => {
    const instance = map.current
    const layer = passengerLayer.current
    if (!instance || !layer) return
    layer.clearLayers()
    for (const passenger of list) {
      const point = endpointLatLng(passenger.origin)
      if (!point) continue
      const active = passenger.id === selectedId
      const icon = L.divIcon({
        className: 'driver-map-pin-host',
        html: `<span class="driver-map-pin driver-map-pin-${bandFor(passenger.distance_km)}${active ? ' driver-map-pin-active' : ''}">${PERSON_GLYPH}</span>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17],
      })
      const marker = L.marker(point, { icon, title: passenger.passenger_name, zIndexOffset: active ? 1000 : 0 })
      marker.on('click', () => selectRef.current(passenger.id))
      marker.addTo(layer)
    }
  }, [list, selectedId])

  // The picked passenger's ride: a dashed line from the pickup point to the
  // drop-off, ending in an arrow that points the way they want to travel.
  useEffect(() => {
    const instance = map.current
    const layer = routeLayer.current
    if (!instance || !layer) return
    layer.clearLayers()
    if (!origin) return
    if (destination) {
      L.polyline([origin, destination], { color: '#1f3d33', weight: 3, dashArray: '7 8', opacity: 0.75 }).addTo(layer)
      const bearing = bearingDegrees(origin, destination)
      L.marker(destination, {
        icon: L.divIcon({
          className: 'driver-map-arrow-host',
          html: `<span class="driver-map-arrow" style="transform:rotate(${bearing}deg)">${ARROW_GLYPH}</span>`,
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        }),
        zIndexOffset: 900,
      }).addTo(layer)
    }
    if (origin[0] !== driver[0] || origin[1] !== driver[1]) {
      // How far the driver still has to drive to the pickup point.
      L.polyline([driver, origin], { color: '#8bab3e', weight: 2, dashArray: '3 7', opacity: 0.7 }).addTo(layer)
    }
  }, [origin, destination, driver])

  useEffect(() => {
    const instance = map.current
    const layer = driverLayer.current
    if (!instance || !layer) return
    layer.clearLayers()
    L.circle(driver, {
      radius: SEARCH_RADIUS_KM * 1000,
      color: '#4d7a5c',
      weight: 1,
      dashArray: '6 8',
      fillColor: '#8bab3e',
      fillOpacity: 0.06,
    }).addTo(layer)
    L.marker(driver, {
      icon: L.divIcon({
        className: 'driver-map-driver-host',
        html: `<span class="driver-map-driver">${DRIVER_GLYPH}</span>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11],
      }),
      zIndexOffset: 1100,
    }).addTo(layer)
  }, [driver])

  // Pressing a person zooms the map onto the whole ride, so the driver sees the
  // pickup and the arrow in one glance.
  useEffect(() => {
    const instance = map.current
    if (!instance || !selected || focusNonce === 0) return
    if (!origin) return
    const points = destination ? [origin, destination] : [origin]
    instance.flyToBounds(L.latLngBounds(points), { padding: [70, 70], maxZoom: 16, duration: 0.6 })
  }, [focusNonce, selected, origin, destination])

  const showDriver = useCallback(() => {
    const instance = map.current
    if (!instance) return
    setSelectedId(null)
    instance.flyTo(driver, 13, { duration: 0.6 })
  }, [driver])

  return <>
    <PageHeading
      eyebrow="HAYDOVCHI XARITASI"
      title="Atrofingizdagi yo‘lovchilar"
      description={`Faol so‘rovlar ${SEARCH_RADIUS_KM} km radiusda ko‘rsatiladi. Odam belgisini bosing — qayeraga borayotgani strelka bilan chiziladi va pastdagi kartada ma’lumot chiqadi.`}
    />
    {source === 'fallback' && <p className="notice notice-warning driver-map-notice"><Crosshair size={16} /><p>Joylashuvni aniqlab bo‘lmadi. Xarita Toshkent markazidan boshlandi — “Meni ko‘rsatish” tugmasi bilan qayta urinib ko‘ring.</p></p>}

    <section className="driver-map-wrap">
      <div className="driver-map" ref={container} />
      <div className="driver-map-hud">
        <div className="driver-map-toolbar">
          <span className="driver-map-count"><UsersRound size={15} /><strong>{nearby.isLoading ? '—' : list.length}</strong> ta yo‘lovchi · {SEARCH_RADIUS_KM} km</span>
          <button className="button button-outline button-small" onClick={() => void nearby.refetch()} disabled={nearby.isFetching}><RefreshCw className={nearby.isFetching ? 'spin' : undefined} size={15} />Yangilash</button>
          <button className="button button-dark button-small" onClick={() => { locate(); showDriver() }}><Crosshair size={15} />Meni ko‘rsatish</button>
        </div>
        <div className="driver-map-legend">
          {BANDS.map((band) => <span key={band.key}><i className={`driver-map-dot driver-map-dot-${band.key}`} />{band.label}</span>)}
        </div>
      </div>

      {nearby.isError && <p className="inline-error driver-map-error"><X size={15} />{readableError(nearby.error)}</p>}
      {!nearby.isError && !nearby.isLoading && !list.length && <p className="driver-map-empty"><UsersRound size={17} /><strong>Atrofingizda so‘rov yo‘q</strong><span>{SEARCH_RADIUS_KM} km ichida faol yo‘lovchi topilmadi. Boshqa joyda turibsiz — GPS ishlayotganini “Meni ko‘rsatish” orqali tekshiring.</span></p>}

      {selected && <article className="driver-map-sheet">
        <span className="driver-map-grip" />
        <div className="driver-map-sheet-head">
          <span className="avatar-small">{(selected.passenger_name || 'Y').charAt(0).toUpperCase()}</span>
          <div className="driver-map-sheet-who">
            <strong>{selected.passenger_name}</strong>
            <small>{selected.passenger_username ? `@${selected.passenger_username}` : `SO‘ROV #${selected.id}`} · yaratilgan {dateTime(selected.created_at)}</small>
          </div>
          <StatusBadge value={selected.status_display || selected.status} />
          <button className="icon-button" onClick={() => setSelectedId(null)} aria-label="Kartani yopish"><X size={18} /></button>
        </div>

        <RouteLine from={endpointLabel(selected.origin, selected.from_location_detail)} to={endpointLabel(selected.destination, selected.to_location_detail)} />

        <div className="driver-map-sheet-metrics">
          <span><Navigation size={14} />{selected.distance_km} km sizdan</span>
          <span><Route size={14} />{selected.trip_km ?? '—'} km yo‘l</span>
          <span><UsersRound size={14} />{selected.passenger_count} ta yo‘lovchi</span>
          <span><CalendarClock size={14} />{dateTime(selected.departure_from || undefined)}</span>
          <strong>{selected.max_price_per_seat ? `≤ ${money(selected.max_price_per_seat)}` : 'Narx erkin'}</strong>
        </div>

        <p className="driver-map-sheet-direction">
          {heading !== null
            ? <><Compass size={15} />{compassOf(heading)} tomon, taxminan {selected.trip_km ?? '—'} km. Strelka qayerga borishini ko‘rsatadi.</>
            : <><Compass size={15} />{origin ? 'Borish manzili ko‘rsatilmagan' : 'Manzil nuqtasi aniqlanmagan'} — haydovchi so‘rov matnidan foydalanadi.</>}
        </p>

        {selected.comment && <p className="driver-map-sheet-note"><UserRound size={14} />{selected.comment}</p>}

        <div className="driver-map-sheet-actions">
          <button className="button button-dark button-small" onClick={() => setFocusNonce((nonce) => nonce + 1)}><ZoomIn size={15} />Yo‘nalishni kattalashtirish</button>
          <button className="button button-outline button-small" onClick={showDriver}><Crosshair size={15} />Mening joylashuvim</button>
        </div>
      </article>}
    </section>
  </>
}