// A stand-in for the tm-control API: replaces fetch, answers from a table of canned responses, and records every
// request, so tests run the real API client and check what it sent.
import { vi } from 'vitest'
import type { components } from '../src/api/schema'

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

// A claimed device with the license accepted, `user` logged in, and these answers besides
export function signedIn(user: object, answers: Record<string, unknown> = {}) {
  return fakeApi({
    'GET /api/v1/setup/status': status(true),
    'GET /api/v1/auth/session': session(true, user),
    ...(answers as Record<string, Answer>),
  })
}

// GET /status: a report of these groups, with the summary counted from them. The types are the API's own (schema.d.ts),
// so these fakes can't drift from what the API sends.
export type Group = components['schemas']['Group']
export type Check = components['schemas']['Check']
type Fix = components['schemas']['Fix']

export function report(groups: Group[], generatedAt = '2026-10-28T14:32:00-07:00') {
  const summary = { ok: 0, warn: 0, error: 0, unknown: 0 }
  for (const check of groups.flatMap((group) => group.checks)) summary[check.status] += 1
  return { generated_at: generatedAt, summary, groups }
}

// A group of n checks with each status, for the verdict
export function counts(ok: number, warn: number, error: number, unknown: number): Group {
  const make = (status: Check['status'], n: number): Check[] =>
    Array.from({ length: n }, (_, i) => ({ id: `${status}${i}`, title: `${status} ${i}`, status, detail: '' }))
  return {
    id: 'services',
    title: 'Services',
    checks: [...make('ok', ok), ...make('warn', warn), ...make('error', error), ...make('unknown', unknown)],
  }
}

export const RESTART_FRIGATE: Fix = { kind: 'restart', text: 'Restart Frigate', unit: 'frigate.service' }
export const RESCAN: Fix = { kind: 'rescan', text: 'Re-scan hardware' }

export const SERVICES: Group = {
  id: 'services',
  title: 'Services',
  checks: [
    { id: 'services.pod', title: 'Traffic Monitor pod', status: 'ok', detail: 'Running since 07:12.' },
    { id: 'services.frigate', title: 'Frigate', status: 'error', detail: 'Stopped after a failure.', fix: RESTART_FRIGATE },
  ],
}

export const HARDWARE_RESCAN: Group = {
  id: 'hardware',
  title: 'Hardware',
  checks: [
    {
      id: 'hardware.radar.ttyACM1',
      title: 'Radar on /dev/ttyACM1',
      status: 'warn',
      detail: "A radar is plugged in, but it isn't enabled.",
      fix: RESCAN,
    },
  ],
}

// GET /system/info
const GB = 2 ** 30
export const SYSTEM_INFO: components['schemas']['SystemInfo'] = {
  hostname: 'tm-fake',
  serial: '0000000012345678',
  model: 'Raspberry Pi 5 Model B Rev 1.0',
  os: 'Debian GNU/Linux 13 (trixie)',
  kernel: '6.12.47+rpt-rpi-2712',
  uptime_seconds: 2 * 86400 + 3 * 3600,
  memory: { total: 8 * GB, available: 5.5 * GB },
  disks: [{ path: '/', total: 58 * GB, used: 50.5 * GB, free: 7.5 * GB }],
  tm: { version: '0.8.0', commit: '2da617a1234567890abcdef1234567890abcdef1', branch: 'dev', installing_user: 'pi' },
  components: { frigate: '0.18.1', node_red: '5.0.8', go2rtc: 'v1.9.14', nginx: '1.31.0' },
  soc_temperature_c: 52.7,
  throttled: { raw: '0x0', now: [], since_boot: [] },
}

// GET /time: the device's clock, 3 minutes behind a phone at 2026-10-28T21:35:12Z
export const PHONE_NOW = new Date('2026-10-28T21:35:12Z')
type TimeResult = components['schemas']['TimeResult']
export const TIME_STATE: components['schemas']['TimeState'] = {
  device_time: '2026-10-28T14:32:12-07:00',
  timezone: 'America/Los_Angeles',
  ntp: { enabled: true, synchronized: false, available: true },
  rtc_time: null,
}
export const TIMEZONES = ['America/Los_Angeles', 'Etc/UTC', 'Europe/Berlin']

// POST /time's answer: the clock as it is afterwards, and what happened
export function timeResult(changes: Partial<TimeResult>): TimeResult {
  return { ...TIME_STATE, time_kept_from_ntp: false, restarting: [], ...changes }
}
