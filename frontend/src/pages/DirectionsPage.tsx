import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CarTaxiFront,
  CircleAlert,
  Compass,
  Crosshair,
  MapPin,
  RefreshCw,
  SlidersHorizontal,
  UsersRound,
} from 'lucide-react'
import {
  api,
  readableError,
  type NearbyRequests,
  type NearbyTrips,
} from '../api'
import { ContentState, PageHeading } from '../components/ui'
import { TripActionCard } from '../components/TripActionCard'
import { useRoleMode } from './useRoleMode'

type LatLng = [number, number]
const TASHKENT: LatLng = [41.311081, 69.240562]
const MAX_RADIUS_KM = 25
const RADIUS_OPTIONS = [5, 10, 15, 25] as const

const DIRECTIONS_POS_KEY = 'teztaxitop_directions_position'

function readStoredPosition(): LatLng | null {
  try {
    const raw = localStorage.getItem(DIRECTIONS_POS_KEY)
    if (!raw) return null
    const [lat, lon] = JSON.parse(raw) as number[]
    return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null
  } catch {
    return null
  }
}

export function DirectionsPage() {
  const roleMode = useRoleMode()
  const isDriver = roleMode === 'driver'

  const [position, setPosition] = useState<LatLng>(() => readStoredPosition() ?? TASHKENT)
  const [positionSource, setPositionSource] = useState<'gps' | 'saved' | 'fallback'>(() =>
    readStoredPosition() ? 'saved' : 'fallback'
  )
  const [gpsError, setGpsError] = useState<string | null>(null)
  const [radiusKm, setRadiusKm] = useState<number>(MAX_RADIUS_KM)

  const locate = useCallback(() => {
    setGpsError(null)
    if (!navigator.geolocation) {
      setGpsError("Brauzeringiz geolokatsiyani qo‘llab-quvvatlamaydi.")
      return
    }
    navigator.geolocation.getCurrentPosition(
      (res) => {
        const next: LatLng = [res.coords.latitude, res.coords.longitude]
        try {
          localStorage.setItem(DIRECTIONS_POS_KEY, JSON.stringify(next))
        } catch {
          // Ignore storage errors
        }
        setPosition(next)
        setPositionSource('gps')
      },
      () => {
        if (positionSource === 'fallback') {
          setGpsError("GPS joylashuvni aniqlab bo‘lmadi. Standart Toshkent koordinatalari ishlatilmoqda.")
        }
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 }
    )
  }, [positionSource])

  useEffect(() => {
    locate()
  }, [locate])

  // Queries for nearby routes
  const [lat, lon] = position

  // 1. Passenger query: finds nearby driver trips (taxis)
  const nearbyTripsQuery = useQuery({
    queryKey: ['nearby-trips', lat, lon, radiusKm],
    enabled: !isDriver,
    queryFn: async () => {
      const { data } = await api.get<NearbyTrips>('/rides/trips/nearby/', {
        params: { lat, lon, radius_km: radiusKm },
      })
      return data
    },
  })

  // 2. Driver query: finds nearby passenger requests
  const nearbyRequestsQuery = useQuery({
    queryKey: ['nearby-requests', lat, lon, radiusKm],
    enabled: isDriver,
    queryFn: async () => {
      const { data } = await api.get<NearbyRequests>('/rides/requests/nearby/', {
        params: { lat, lon, radius_km: radiusKm },
      })
      return data
    },
  })

  const currentQuery = isDriver ? nearbyRequestsQuery : nearbyTripsQuery
  const items = (isDriver ? nearbyRequestsQuery.data?.results : nearbyTripsQuery.data?.results) ?? []
  const count = items.length

  const refetchAll = () => {
    void currentQuery.refetch()
  }

  return (
    <div className="directions-page-container">
      <PageHeading
        eyebrow={isDriver ? "HAYDOVCHI UCHUN YO‘NALISHLAR" : "YO‘LOVCHI UCHUN YO‘NALISHLAR"}
        title="Yaqin Marshrutlar va Yo‘nalishlar"
        description={
          isDriver
            ? "Joylashuvingiz atrofidagi (25 km gacha) yo‘lovchilar so‘rovlari va boshlang‘ich nuqtalari."
            : "Joylashuvingiz atrofidagi (25 km gacha) taksi yo‘lovlari va jo‘nash nuqtalari."
        }
        action={
          <div className="topbar-actions">
            <button
              type="button"
              className="button button-outline button-small"
              onClick={locate}
            >
              <Crosshair size={15} />
              GPS Yangilash
            </button>
            <button
              type="button"
              className="button button-dark button-small"
              onClick={refetchAll}
              disabled={currentQuery.isFetching}
            >
              <RefreshCw className={currentQuery.isFetching ? 'spin' : undefined} size={15} />
              Yangilash
            </button>
          </div>
        }
      />

      {/* Geolocation Status Bar & Filter Controls */}
      <section className="directions-filter-bar">
        <div className="directions-geo-status">
          <MapPin size={16} className="directions-geo-icon" />
          <div className="directions-geo-text">
            <strong>
              {positionSource === 'gps'
                ? 'Aniq GPS joylashuv'
                : positionSource === 'saved'
                ? 'Saqlangan joylashuv'
                : 'Standart shahar markazi (Toshkent)'}
            </strong>
            <small>
              {lat.toFixed(4)}, {lon.toFixed(4)} · Qidiruv radiusi: {radiusKm} km (maksimal 25 km)
            </small>
          </div>
        </div>

        <div className="directions-radius-selector">
          <SlidersHorizontal size={15} />
          <span>Radius:</span>
          <div className="directions-radius-pills">
            {RADIUS_OPTIONS.map((r) => (
              <button
                key={r}
                type="button"
                className={`pill-button ${radiusKm === r ? 'pill-active' : ''}`}
                onClick={() => setRadiusKm(r)}
              >
                {r} km
              </button>
            ))}
          </div>
        </div>
      </section>

      {gpsError && (
        <p className="inline-error">
          <CircleAlert size={15} />
          {gpsError}
        </p>
      )}

      {/* Route List / Content State */}
      <ContentState
        loading={currentQuery.isLoading}
        error={currentQuery.error ? readableError(currentQuery.error) : undefined}
        empty={!currentQuery.isLoading && count === 0}
        emptyTitle={isDriver ? "Yaqin atrofda yo‘lovchi so‘rovi yo‘q" : "Yaqin atrofda faol taksi yo‘lovi yo‘q"}
        emptyDescription={
          isDriver
            ? `${radiusKm} km radius ichida hozircha yangi so‘rov topilmadi. Radiusni oshiring yoki xaritani tekshiring.`
            : `${radiusKm} km radius ichida hozircha mos taksi topilmadi. Radiusni oshiring yoki xaritani tekshiring.`
        }
        emptyIcon={isDriver ? UsersRound : CarTaxiFront}
        emptyAction={
          <a
            href={isDriver ? "/map" : "/taxi-map"}
            className="button button-outline"
          >
            <Compass size={16} />
            Xaritada ko‘rish
          </a>
        }
        onRetry={refetchAll}
      >
        <div className="directions-results-header">
          <span className="directions-results-count">
            Topilgan yo‘nalishlar: <strong>{count} ta</strong> ({radiusKm} km ichida)
          </span>
          <span className="directions-role-indicator">
            {isDriver ? '🚗 Haydovchi rejimi (Yo‘lovchilarni qidirish)' : '👤 Yo‘lovchi rejimi (Taksilarni qidirish)'}
          </span>
        </div>

        <div className="record-list directions-list">
          {items.map((item) => (
            <TripActionCard
              key={item.id}
              item={item}
              type={isDriver ? 'passenger' : 'taxi'}
              onBookSuccess={refetchAll}
            />
          ))}
        </div>
      </ContentState>
    </div>
  )
}
