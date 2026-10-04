/** A stand-in for the Django API.
 *
 *  The pages reach the network only through the shared `api` axios instance, so
 *  swapping its adapter is enough to make every test deterministic and to record
 *  exactly which endpoints a screen asked for - which is how the "nothing is
 *  chosen for the user" requirement is asserted.
 */
import { type AxiosAdapter, type AxiosRequestConfig, type AxiosResponse, AxiosError } from 'axios'
import { api } from '../api'

export type StubReply = { status?: number; data?: unknown }

type Responder = (config: AxiosRequestConfig) => StubReply | Promise<StubReply>

let responder: Responder = () => ({ data: {} })

/** Every URL the page asked for, in order, e.g. `/matching/trips/<id>/requests/`. */
export const requestedUrls: string[] = []

const adapter: AxiosAdapter = async (config) => {
  const url = String(config.url)
  requestedUrls.push(url)
  const reply = await responder(config)
  const status = reply.status ?? 200
  const response: AxiosResponse = {
    data: reply.data ?? null,
    status,
    statusText: status >= 400 ? 'Error' : 'OK',
    headers: {},
    config,
  }
  if (status >= 400) {
    throw new AxiosError(
      `Request failed with status code ${status}`,
      String(status),
      config,
      undefined,
      response,
    )
  }
  return response
}

export function stubApi(next: Responder) {
  responder = next
  requestedUrls.length = 0
  api.defaults.adapter = adapter
}

export function requested(urlFragment: string) {
  return requestedUrls.filter((url) => url.includes(urlFragment))
}

/** A promise the test resolves itself, so the loading state can be observed. */
export function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((settle) => { resolve = settle })
  return { promise, resolve }
}