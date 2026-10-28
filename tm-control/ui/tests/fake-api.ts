// A stand-in for the tm-control API: replaces fetch, answers from a table of canned responses, and records every
// request, so tests run the real API client and check what it sent.
import { vi } from 'vitest'

type Answer = Response | object | ((request: Request) => Response | Promise<Response>)

export interface Sent {
  method: string
  path: string
  body: unknown
}

export function json(status: number, body: unknown): Response {
  if (body === null) return new Response(null, { status })
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

export function apiError(status: number, code: string, message: string): Response {
  return json(status, { error: { code, message, detail: null } })
}

// `answers` maps "METHOD /path" to a body (sent as 200), a Response, or a function of the request.
export function fakeApi(answers: Record<string, Answer>) {
  const sent: Sent[] = []
  const fetch = vi.fn(async (request: Request) => {
    const path = new URL(request.url).pathname
    const text = request.method === 'GET' ? '' : await request.clone().text()
    sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null })
    const answer = answers[`${request.method} ${path}`]
    if (answer === undefined) return apiError(404, 'not_found', `No fake answer for ${request.method} ${path}`)
    if (typeof answer === 'function') return answer(request)
    return answer instanceof Response ? answer.clone() : json(200, answer)
  })
  vi.stubGlobal('fetch', fetch)
  return { sent, fetch }
}

export const THEME = {
  font: 'Helvetica',
  colors: { background: '#0C1120', header_text: '#3a82ff', body_text: '#f8fafc', link_hover_text: '#8895a7' },
}

export function status(claimed: boolean, accepted = claimed) {
  return { claimed, eula: { version: '1', accepted }, theme: THEME }
}

export const ADMIN = { id: 1, username: 'owner', role: 'admin', created_at: '2026-10-27T12:00:00+00:00' }
export const VIEWER = { id: 2, username: 'alice', role: 'viewer', created_at: '2026-10-27T12:00:00+00:00' }

export function session(claimed: boolean, user: object | null, accepted = claimed) {
  return { claimed, eula_accepted: accepted, user }
}
