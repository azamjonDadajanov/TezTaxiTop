/** The driver's "suitable passengers" screen.
 *
 *  The rules these tests protect: the driver never picks a passenger, nothing is
 *  chosen for them, the answer arrives already filled, every trip that has a
 *  match is shown, and every number on the card is the value the backend measured.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { api } from '../api'
import { requested, requestedUrls, stubApi } from '../test/http'

const role = vi.hoisted(() => ({ current: 'driver' as 'driver' | 'passenger' }))
vi.mock('../authContext', () => ({ useAuth: () => ({ user: { role: role.current, driver_profile: { id: 7 } } }) }))

import { MatchingPage } from './RidePages'

const SUITABLE_ENDPOINT = '/matching/trips/suitable-requests/'

function match(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    trip_id: 11,
    request_id: 101,
    route: 'Toshkent -> Samarqand',
    pickup_location: 'Toshkent',
    dropoff_location: 'Samarqand',
    departure_time: '2026-10-05T08:00:00+05:00',
    departure_from: '2026-10-05T07:40:00+05:00',
    departure_until: '2026-10-05T09:30:00+05:00',
    price_per_seat: '20000.00',
    available_seats: 4,
    required_seats: 2,
    passenger_name: 'John Doe',
    passenger_username: 'john',
    driver_name: 'Haydovchi',
    vehicle_name: 'Lacetti Chery - 01B 777AA',
    plate_number: '01B 777AA',
    distance_difference_km: 7.8,
    pickup_offset_km: 4.2,
    dropoff_offset_km: 7.8,
    route_deviation_km: 12.5,
    time_difference_minutes: 35,
    route_compatible: true,
    route_status: '',
    route_match_basis: 'coordinates',
    score: '92.50',
    rank: 1,
    reasons: ['Chuqish vaqti yaqin'],
    ...overrides,
  }
}

function group(overrides: Record<string, unknown> = {}, results: unknown[] = [match()]) {
  return {
    trip_id: 11,
    route: 'Toshkent -> Samarqand',
    departure_time: '2026-10-05T08:00:00+05:00',
    available_seats: 4,
    total_seats: 4,
    vehicle_name: 'Lacetti Chery - 01B 777AA',
    plate_number: '01B 777AA',
    results,
    ...overrides,
  }
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MatchingPage />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  role.current = 'driver'
  stubApi(() => ({ data: { max_score: '100.00', trips: [] } }))
})

afterEach(() => {
  delete api.defaults.adapter
})

describe('suitable passengers screen - nothing is chosen by the user', () => {
  it('has no passenger selector of any kind', async () => {
    const { container } = renderPage()
    await waitFor(() => expect(requested(SUITABLE_ENDPOINT)).toHaveLength(1))

    expect(container.querySelector('select')).toBeNull()
    expect(container.querySelectorAll('option')).toHaveLength(0)
    expect(screen.queryByText(/so‘rovni tanlang/i)).toBeNull()
    expect(screen.queryByText(/passenger/i)).toBeNull()
  })

  it('asks the backend once, without naming a trip', async () => {
    renderPage()
    await waitFor(() => expect(requested(SUITABLE_ENDPOINT)).toHaveLength(1))

    // No per-trip feed call, and no "list my trips then pick one" round trip:
    // the driver screen never fetches the driver's trips to select from.
    expect(requestedUrls.filter((url) => /^\/matching\/trips\/\d+\/requests\/$/.test(url))).toHaveLength(0)
    expect(requested('/rides/trips/my_trips/')).toHaveLength(0)
    expect(requestedUrls).toEqual([SUITABLE_ENDPOINT])
  })

  it('loads the matches on open, with no click and no search button', async () => {
    stubApi(() => ({ data: { max_score: '100.00', trips: [group()] } }))
    renderPage()

    expect(await screen.findByText('John Doe')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /qidirish/i })).toBeNull()
    expect(screen.queryByRole('combobox')).toBeNull()
  })
})

describe('suitable passengers screen - every match is shown', () => {
  it('displays all matching passengers of a trip', async () => {
    stubApi(() => ({ data: { trips: [group({}, [
      match({ request_id: 1, passenger_name: 'John Doe' }),
      match({ request_id: 2, passenger_name: 'Alisher', rank: 2 }),
      match({ request_id: 3, passenger_name: 'Malika', rank: 3 }),
    ])] } }))
    renderPage()

    await screen.findByText('John Doe')
    expect(screen.getAllByTestId('suitable-passenger')).toHaveLength(3)
    expect(screen.getByText('Alisher')).toBeTruthy()
    expect(screen.getByText('Malika')).toBeTruthy()
  })

  it('groups the passengers by trip and omits a trip without a match', async () => {
    stubApi(() => ({ data: { trips: [
      group({ trip_id: 11, route: 'A -> B' }, [
        match({ request_id: 1, passenger_name: 'John Doe' }),
        match({ request_id: 2, passenger_name: 'Alisher', rank: 2 }),
      ]),
      group({ trip_id: 33, route: 'C -> D' }, [
        match({ request_id: 3, passenger_name: 'Malika' }),
      ]),
    ] } }))
    renderPage()

    await screen.findByText('John Doe')
    const groups = screen.getAllByTestId('suitable-trip-group')
    // Trip 22 had no suitable passenger, so the backend left it out and the
    // screen must not invent a group for it either.
    expect(groups).toHaveLength(2)
    expect(within(groups[0]).getByText('Alisher')).toBeTruthy()
    expect(within(groups[0]).queryByText('Malika')).toBeNull()
    expect(within(groups[1]).getByText('Malika')).toBeTruthy()
    expect(screen.getAllByText(/YO‘LOV #/i).map((node) => node.textContent)).toEqual(['YO‘LOV #11', 'YO‘LOV #33'])
  })

  it('keeps the backend ranking instead of re-sorting it', async () => {
    const weakestFirst = [
      match({ request_id: 1, passenger_name: 'Zaynab', rank: 1, score: '40.00' }),
      match({ request_id: 2, passenger_name: 'Alisher', rank: 2, score: '80.00' }),
    ]
    stubApi(() => ({ data: { trips: [group({}, weakestFirst)] } }))
    renderPage()

    await screen.findByText('Zaynab')
    const names = screen.getAllByTestId('suitable-passenger').map((card) => within(card).getByText(/Zaynab|Alisher/).textContent)
    expect(names).toEqual(['Zaynab', 'Alisher'])
  })
})

describe('suitable passengers screen - the measurements come from the API', () => {
  it('shows the passenger, the route, the clocks and the seats', async () => {
    stubApi(() => ({ data: { trips: [group()] } }))
    renderPage()

    const card = await screen.findByTestId('suitable-passenger')
    expect(within(card).getByText('John Doe')).toBeTruthy()
    expect(within(card).getByText(/2 yo‘lovchi/)).toBeTruthy()
    expect(within(card).getByText('Toshkent')).toBeTruthy()
    expect(within(card).getByText('Samarqand')).toBeTruthy()
    expect(within(card).getByText(/35 daqiqa/)).toBeTruthy()
    expect(within(card).getByText('4.2 km')).toBeTruthy()
    // Dropoff offset and the route maximum are both 7.8 km, and the card shows
    // the backend's two numbers rather than collapsing them into one.
    expect(within(card).getAllByText('7.8 km')).toHaveLength(2)
    expect(within(card).getByText('12.5 km')).toBeTruthy()
    expect(within(card).getByText('2 / 4')).toBeTruthy()
    expect(within(card).getByText('92.50 ball')).toBeTruthy()
  })

  it('does not invent a distance for a legacy route-identity match', async () => {
    stubApi(() => ({ data: { trips: [group({}, [match({
      route_match_basis: 'route_identity',
      pickup_offset_km: null,
      dropoff_offset_km: null,
      distance_difference_km: null,
      route_deviation_km: null,
    })])] } }))
    renderPage()

    const card = await screen.findByTestId('suitable-passenger')
    expect(within(card).queryByText('4.2 km')).toBeNull()
    expect(within(card).queryByText('7.8 km')).toBeNull()
    expect(within(card).getByText(/Koordinata mavjud emas/)).toBeTruthy()
  })
})

describe('suitable passengers screen - loading and empty states', () => {
  it('says it is loading while the answer is in flight', async () => {
    let release: (() => void) | undefined
    const gate = new Promise<void>((resolve) => { release = resolve })
    stubApi(async () => { await gate; return { data: { trips: [group()] } } })
    renderPage()

    expect(await screen.findByText('Mos yo‘lovchilar yuklanmoqda…')).toBeTruthy()
    release!()
    expect(await screen.findByText('John Doe')).toBeTruthy()
  })

  it('says there is no suitable passenger instead of inventing one', async () => {
    stubApi(() => ({ data: { max_score: '100.00', trips: [] } }))
    renderPage()

    expect(await screen.findByText('Mos yo‘lovchilar topilmadi.')).toBeTruthy()
    expect(screen.queryAllByTestId('suitable-passenger')).toHaveLength(0)
    expect(screen.queryByTestId('suitable-trip-group')).toBeNull()
  })
})

describe('passenger side - a request is chosen explicitly, never arbitrarily', () => {
  beforeEach(() => {
    role.current = 'passenger'
  })

  const requests = [
    { id: 41, passenger_count: 2, origin: { display: 'Toshkent' }, destination: { display: 'Samarqand' }, status: 'active' },
    { id: 42, passenger_count: 1, origin: { display: 'Buxoro' }, destination: { display: 'Nukus' }, status: 'active' },
  ]

  it('fetches nothing until the passenger says which request they mean', async () => {
    stubApi(() => ({ data: requests }))
    renderPage()

    await screen.findByText('So‘rov #41')
    expect(screen.getAllByTestId('passenger-request-option')).toHaveLength(2)
    expect(requested('/matching/requests/')).toHaveLength(0)
    expect(requestedUrls).toEqual(['/rides/requests/'])
  })

  it('loads the trips of the chosen request', async () => {
    stubApi((config) => (String(config.url) === '/rides/requests/'
      ? { data: requests }
      : { data: { request_id: 41, results: [match({ trip_id: 11, rank: 1 })] } }))
    renderPage()

    fireEvent.click((await screen.findAllByTestId('passenger-request-option'))[1])
    await waitFor(() => expect(requested('/matching/requests/42/trips/')).toHaveLength(1))
  })

  it('opens on its own when there is exactly one request', async () => {
    stubApi((config) => {
      if (String(config.url) === '/rides/requests/') return { data: [requests[0]] }
      return { data: { request_id: 41, results: [match()] } }
    })
    renderPage()

    await waitFor(() => expect(requested('/matching/requests/41/trips/')).toHaveLength(1))
  })

  it('has no passenger dropdown either', async () => {
    stubApi(() => ({ data: requests }))
    const { container } = renderPage()
    await screen.findByText('So‘rov #41')
    expect(container.querySelector('select')).toBeNull()
  })
})