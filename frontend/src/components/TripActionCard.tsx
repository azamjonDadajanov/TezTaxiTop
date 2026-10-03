import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  CalendarClock,
  CarTaxiFront,
  CheckCircle2,
  CircleAlert,
  MessageCircle,
  Navigation,
  Route,
  User,
  UserRound,
  UsersRound,
} from 'lucide-react'
import {
  createBooking,
  dateTime,
  endpointLabel,
  money,
  openChat,
  readableError,
  type NearbyRequest,
  type NearbyTrip,
} from '../api'
import { RouteLine, StatusBadge } from './ui'

export type RouteActionButtonsProps = {
  tripId?: number
  requestId?: number
  orderId?: number
  seatsBooked?: number
  variant?: 'card' | 'map'
  onBookSuccess?: () => void
}

export function RouteActionButtons({
  tripId,
  requestId,
  orderId,
  seatsBooked = 1,
  variant = 'card',
  onBookSuccess,
}: RouteActionButtonsProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  const bookMutation = useMutation({
    mutationFn: async () => {
      setFeedback(null)
      if (tripId != null) {
        return await createBooking({ trip: tripId, seats_booked: seatsBooked })
      }
      if (requestId != null) {
        return await createBooking({ request_id: requestId })
      }
      throw new Error("Band qilish uchun yo'lov yoki so'rov tanlanmagan.")
    },
    onSuccess: () => {
      setFeedback({
        type: 'success',
        message: tripId != null ? 'Safar muvaffaqiyatli band qilindi!' : 'So‘rov muvaffaqiyatli qabul qilindi!',
      })
      void queryClient.invalidateQueries({ queryKey: ['my-orders'] })
      void queryClient.invalidateQueries({ queryKey: ['my-trips'] })
      void queryClient.invalidateQueries({ queryKey: ['my-requests'] })
      void queryClient.invalidateQueries({ queryKey: ['nearby-trips'] })
      void queryClient.invalidateQueries({ queryKey: ['nearby-requests'] })
      if (onBookSuccess) {
        onBookSuccess()
      }
    },
    onError: (error) => {
      setFeedback({
        type: 'error',
        message: readableError(error),
      })
    },
  })

  const chatMutation = useMutation({
    mutationFn: async () => {
      setFeedback(null)
      return await openChat({
        order_id: orderId,
        trip_id: tripId,
        request_id: requestId,
      })
    },
    onSuccess: (response) => {
      void queryClient.invalidateQueries({ queryKey: ['chat-threads'] })
      navigate('/chat', { state: { orderId: response.order_id } })
    },
    onError: (error) => {
      setFeedback({
        type: 'error',
        message: readableError(error),
      })
    },
  })

  const isMap = variant === 'map'
  const btnSize = isMap ? 'button-small' : ''

  return (
    <div className="trip-action-buttons-wrap">
      {feedback && (
        <div
          className={feedback.type === 'success' ? 'notice notice-success inline-feedback' : 'inline-error inline-feedback'}
          role="alert"
        >
          {feedback.type === 'success' ? <CheckCircle2 size={16} /> : <CircleAlert size={16} />}
          <span>{feedback.message}</span>
        </div>
      )}
      <div className={isMap ? 'driver-map-sheet-actions' : 'record-actions'}>
        <button
          type="button"
          className={`button button-dark ${btnSize}`}
          disabled={bookMutation.isPending || chatMutation.isPending || (feedback?.type === 'success' && !isMap)}
          onClick={() => bookMutation.mutate()}
        >
          {bookMutation.isPending ? 'Band qilinmoqda…' : tripId != null ? 'Band qilish' : 'Qabul qilish'}
        </button>

        <button
          type="button"
          className={`button button-outline ${btnSize}`}
          disabled={chatMutation.isPending || bookMutation.isPending}
          onClick={() => chatMutation.mutate()}
        >
          <MessageCircle size={15} />
          {chatMutation.isPending ? 'Suhbat ochilmoqda…' : 'Suhbat'}
        </button>
      </div>
    </div>
  )
}

export type TripActionCardProps = {
  item: NearbyTrip | NearbyRequest
  type: 'taxi' | 'passenger'
  onBookSuccess?: () => void
}

export function TripActionCard({ item, type, onBookSuccess }: TripActionCardProps) {
  const isTaxi = type === 'taxi'
  const trip = isTaxi ? (item as NearbyTrip) : null
  const req = !isTaxi ? (item as NearbyRequest) : null

  const originName = endpointLabel(item.origin, (item as any).from_location_detail)
  const destinationName = endpointLabel(item.destination, (item as any).to_location_detail)
  const distanceKm = (item as any).distance_km ?? 0
  const tripKm = (item as any).trip_km

  return (
    <article className="record-card directions-route-card">
      <div className="record-top">
        <div className="directions-card-type">
          {isTaxi ? (
            <span className="badge badge-taxi">
              <CarTaxiFront size={14} /> Taxi / Haydovchi
            </span>
          ) : (
            <span className="badge badge-passenger">
              <User size={14} /> Yo‘lovchi so‘rovi
            </span>
          )}
          <span className="record-id">#{item.id}</span>
        </div>
        <StatusBadge value={(item as any).status_display || item.status} />
      </div>

      {/* Prominent Starting Point Distance Banner */}
      <div className="directions-starting-point-banner">
        <Navigation size={16} className="directions-nav-icon" />
        <div className="directions-starting-point-copy">
          <span className="directions-starting-point-label">
            {isTaxi ? 'Boshlanish nuqtasi:' : 'Olib ketish nuqtasi:'}
          </span>
          <strong className="directions-starting-point-distance">
            {distanceKm > 0 ? `${distanceKm} km sizdan` : 'Yaqiningizda'}
          </strong>
        </div>
        {tripKm != null && tripKm > 0 && (
          <div className="directions-total-km">
            <Route size={14} />
            <span>{tripKm} km umumiy yo‘l</span>
          </div>
        )}
      </div>

      <RouteLine from={originName} to={destinationName} />

      {/* Driver/Vehicle or Passenger details */}
      {isTaxi && trip && (
        <div className="directions-meta-row">
          <div className="directions-person-info">
            <span className="avatar-small">{(trip.driver_name || 'H').charAt(0).toUpperCase()}</span>
            <div>
              <strong>{trip.driver_name || 'Haydovchi'}</strong>
              <small>
                {trip.driver_username ? `@${trip.driver_username}` : ''}
                {trip.driver_rating ? ` · ★ ${trip.driver_rating}` : ''}
              </small>
            </div>
          </div>
          {(trip.vehicle_brand || trip.vehicle_model || trip.vehicle_plate_number) && (
            <div className="directions-vehicle-chip">
              <CarTaxiFront size={14} />
              <span>{[trip.vehicle_brand, trip.vehicle_model].filter(Boolean).join(' ') || 'Taxi'}</span>
              {trip.vehicle_plate_number && (
                <span className="driver-map-plate">{trip.vehicle_plate_number}</span>
              )}
            </div>
          )}
        </div>
      )}

      {!isTaxi && req && (
        <div className="directions-meta-row">
          <div className="directions-person-info">
            <span className="avatar-small">{(req.passenger_name || 'Y').charAt(0).toUpperCase()}</span>
            <div>
              <strong>{req.passenger_name || 'Yo‘lovchi'}</strong>
              <small>{req.passenger_username ? `@${req.passenger_username}` : ''}</small>
            </div>
          </div>
        </div>
      )}

      <div className="record-detail-grid">
        <span>
          <CalendarClock size={15} />
          {dateTime(isTaxi ? trip?.departure_time : req?.departure_from || undefined)}
        </span>
        {isTaxi && trip && (
          <span>
            <UsersRound size={15} />
            {trip.available_seats} / {trip.total_seats} bo‘sh o‘rin
          </span>
        )}
        {!isTaxi && req && (
          <span>
            <UsersRound size={15} />
            {req.passenger_count} ta yo‘lovchi
          </span>
        )}
        <strong>
          {isTaxi && trip?.price_per_seat != null
            ? money(trip.price_per_seat)
            : !isTaxi && req?.max_price_per_seat != null
            ? `≤ ${money(req.max_price_per_seat)}`
            : 'Narx kelishiladi'}
        </strong>
      </div>

      {item.comment && (
        <p className="directions-comment-note">
          <UserRound size={14} />
          <span>{item.comment}</span>
        </p>
      )}

      <RouteActionButtons
        tripId={isTaxi ? item.id : undefined}
        requestId={!isTaxi ? item.id : undefined}
        seatsBooked={isTaxi ? 1 : req?.passenger_count || 1}
        variant="card"
        onBookSuccess={onBookSuccess}
      />
    </article>
  )
}
