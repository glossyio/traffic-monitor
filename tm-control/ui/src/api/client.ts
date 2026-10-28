// The API client: openapi-fetch, with paths and request bodies typed from schema.d.ts (generated from openapi.json,
// see README.md). Every call either returns the API's data or throws an ApiError.
import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from './schema'

// An error answer from the API ({"error": {"code", "message", "detail"}}), or status 0 when the device didn't answer
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly detail: unknown = null,
    readonly retryAfter: number | null = null, // seconds, from a 429's Retry-After
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export const OFFLINE_MESSAGE =
  "The device didn't answer. Check that this phone or computer is still connected to the device's network, then try again."

// Where a 401 means the password typed was wrong, not that the session ended
const PASSWORD_CHECKS = new Set(['/api/v1/auth/login', '/api/v1/account/password'])

let sessionLost = () => {}

// What to do when the API says the session has ended (the router sends the browser to the login page)
export function whenSessionLost(handler: () => void) {
  sessionLost = handler
}

const errors: Middleware = {
  onRequest({ request }) {
    // The API's cross-site check wants JSON on every request that changes something, even one without a body
    if (request.method !== 'GET') request.headers.set('Content-Type', 'application/json')
    return request
  },
  async onResponse({ request, response }) {
    if (response.ok) return undefined
    const body = await response
      .clone()
      .json()
      .catch(() => null)
    const error = body?.error
    const retryAfter = Number(response.headers.get('Retry-After')) || null
    if (response.status === 401 && !PASSWORD_CHECKS.has(new URL(request.url).pathname)) sessionLost()
    throw new ApiError(
      response.status,
      error?.code ?? 'error',
      error?.message ?? `The device answered with an error (HTTP ${response.status}).`,
      error?.detail ?? null,
      retryAfter,
    )
  },
  onError() {
    return new ApiError(0, 'offline', OFFLINE_MESSAGE)
  },
}

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: 'same-origin',
  // Looked up on each call rather than once, so tests can replace fetch
  fetch: (request) => globalThis.fetch(request),
})
api.use(errors)

// The words to show for an error a call threw
export function messageOf(error: unknown): string {
  if (!(error instanceof ApiError)) return `Something went wrong on this page: ${String(error)}`
  if (error.retryAfter === null) return error.message
  const wait = error.retryAfter < 120 ? `${error.retryAfter} seconds` : `${Math.ceil(error.retryAfter / 60)} minutes`
  return `${error.message} Wait ${wait} before the next try.`
}
