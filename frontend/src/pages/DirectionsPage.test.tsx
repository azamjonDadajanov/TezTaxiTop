import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { api } from '../api'
import { requested, stubApi } from '../test/http'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

const role = vi.hoisted(() => ({ current: 'passenger' as 'driver' | 'passenger' }))
vi.mock('../authContext', () => ({
  useAuth: () => ({
    user: { id: 1, role: role.current, driver_profile: role.current === 'driver' ? { id: 7 } : null },
  }),
}))

vi.mock('./useRoleMode', () => ({
  useRoleMode: () => role.current,
}))

import { DirectionsPage } from './DirectionsPage'

function mockTrip(overrides: Record<string, unknown> = {}) {
  return {
    id: 101,
    origin: {
      latitude: 41.311,
      longitude: 69.24,
      display: 'Toshkent, Chilonzor',
      name: 'Chilonzor',
    },
    destination: {
      latitude: 39.654,
      longitude: 66.975,
      display: 'Samarqand, Markaz',
      name: 'Samarqand',
    },
    driver_name: 'Azamjon',
    driver_username: 'azamjon',
    driver_rating: '4.9',
    vehicle_brand: 'Chevrolet',
    vehicle_model: 'Cobalt',
    vehicle_plate_number: '01A123BC',
    available_seats: 3,
    total_seats: 4,
    price_per_seat: 85000,
    departure_time: '2026-10-05T14:30:00+05:00',
    distance_km: 4.8,
    trip_km: 310,
    status: 'active',
    status_display: 'Faol',
    ...overrides,
  }
}

function mockRequest(overrides: Record<string, unknown> = {}) {
  return {
    id: 202,
    origin: {
      latitude: 41.32,
      longitude: 69.25,
      display: 'Toshkent, Yunusobod',
      name: 'Yunusobod',
    },
    destination: {
      latitude: 39.654,
      longitude: 66.975,
      display: 'Samarqand, Vokzal',
      name: 'Samarqand',
    },
    passenger_name: 'Dilshod',
    passenger_username: 'dilshod',
    passenger_count: 2,
    max_price_per_seat: 90000,
    departure_from: '2026-10-05T15:00:00+05:00',
    distance_km: 5.1,
    trip_km: 305,
    status: 'active',
    status_display: 'Faol',
    ...overrides,
  }
}

function renderDirectionsPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <DirectionsPage />
      </QueryClientProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  role.current = 'passenger'
  mockNavigate.mockClear()
})

afterEach(() => {
  delete api.defaults.adapter
})

describe('DirectionsPage', () => {
  it('renders nearby taxi trips for passenger with starting distance', async () => {
    stubApi((config) => {
      if (config.url?.includes('/rides/trips/nearby/')) {
        return {
          data: {
            center: { latitude: 41.311081, longitude: 69.240562 },
            radius_km: 25,
            count: 1,
            results: [mockTrip()],
          },
        }
      }
      return { data: {} }
    })

    renderDirectionsPage()

    await waitFor(() => expect(requested('/rides/trips/nearby/')).toHaveLength(1))

    expect(await screen.findByText(/4.8 km sizdan/i)).toBeTruthy()
    expect(screen.getByText(/Toshkent, Chilonzor/i)).toBeTruthy()
    expect(screen.getByText(/Samarqand, Markaz/i)).toBeTruthy()
    expect(screen.getAllByText(/Azamjon/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/Band qilish/i)).toBeTruthy()
    expect(screen.getByText(/Suhbat/i)).toBeTruthy()
  })

  it('renders nearby passenger requests when in driver mode', async () => {
    role.current = 'driver'
    stubApi((config) => {
      if (config.url?.includes('/rides/requests/nearby/')) {
        return {
          data: {
            center: { latitude: 41.311081, longitude: 69.240562 },
            radius_km: 25,
            count: 1,
            results: [mockRequest()],
          },
        }
      }
      return { data: {} }
    })

    renderDirectionsPage()

    await waitFor(() => expect(requested('/rides/requests/nearby/')).toHaveLength(1))

    expect(await screen.findByText(/5.1 km sizdan/i)).toBeTruthy()
    expect(screen.getByText(/Toshkent, Yunusobod/i)).toBeTruthy()
    expect(screen.getAllByText(/Dilshod/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/Qabul qilish/i)).toBeTruthy()
  })

  it('handles successful booking from the Directions card', async () => {
    let orderCreated = false
    stubApi((config) => {
      if (config.url?.includes('/rides/trips/nearby/')) {
        return {
          data: {
            center: { latitude: 41.311081, longitude: 69.240562 },
            radius_km: 25,
            count: 1,
            results: [mockTrip()],
          },
        }
      }
      if (config.url?.includes('/orders/orders/') && config.method?.toLowerCase() === 'post') {
        orderCreated = true
        return {
          status: 201,
          data: { id: 77, trip: 101, status: 'pending' },
        }
      }
      return { data: {} }
    })

    renderDirectionsPage()

    const bookBtn = await screen.findByText(/Band qilish/i)
    fireEvent.click(bookBtn)

    await waitFor(() => {
      expect(orderCreated).toBe(true)
      expect(screen.getByText(/muvaffaqiyatli band qilindi/i)).toBeTruthy()
    })
  })

  it('handles backend error when booking fails (e.g. duplicate booking)', async () => {
    stubApi((config) => {
      if (config.url?.includes('/rides/trips/nearby/')) {
        return {
          data: {
            center: { latitude: 41.311081, longitude: 69.240562 },
            radius_km: 25,
            count: 1,
            results: [mockTrip()],
          },
        }
      }
      if (config.url?.includes('/orders/orders/') && config.method?.toLowerCase() === 'post') {
        return {
          status: 400,
          data: { detail: 'Siz ushbu safar uchun allaqachon buyurtma bergansiz.' },
        }
      }
      return { data: {} }
    })

    renderDirectionsPage()

    const bookBtn = await screen.findByText(/Band qilish/i)
    fireEvent.click(bookBtn)

    await waitFor(() => {
      expect(screen.getByText(/allaqachon buyurtma bergansiz/i)).toBeTruthy()
    })
  })

  it('handles chat button opening existing/new conversation and navigating to /chat', async () => {
    stubApi((config) => {
      if (config.url?.includes('/rides/trips/nearby/')) {
        return {
          data: {
            center: { latitude: 41.311081, longitude: 69.240562 },
            radius_km: 25,
            count: 1,
            results: [mockTrip()],
          },
        }
      }
      if (config.url?.includes('/chat/chats/open/') && config.method?.toLowerCase() === 'post') {
        return {
          status: 200,
          data: {
            thread: { id: 12, order_id: 88 },
            order_id: 88,
            created: false,
          },
        }
      }
      return { data: {} }
    })

    renderDirectionsPage()

    const chatBtn = await screen.findByText(/Suhbat/i)
    fireEvent.click(chatBtn)

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith('/chat', { state: { orderId: 88 } })
    })
  })

  it('allows selecting different search radii up to 25 km', async () => {
    stubApi((config) => {
      if (config.url?.includes('/rides/trips/nearby/')) {
        return {
          data: {
            center: { latitude: 41.311081, longitude: 69.240562 },
            radius_km: 10,
            count: 0,
            results: [],
          },
        }
      }
      return { data: {} }
    })

    renderDirectionsPage()

    await waitFor(() => expect(requested('/rides/trips/nearby/')).toHaveLength(1))

    fireEvent.click(screen.getByText('10 km'))

    await waitFor(() => {
      expect(requested('/rides/trips/nearby/').length).toBeGreaterThanOrEqual(2)
    })
  })
})
