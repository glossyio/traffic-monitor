// A stand-in for the tm-control API: replaces fetch, answers from a table of canned responses, and records every
// request, so tests run the real API client and check what it sent.
import { vi } from 'vitest'
import type { components } from '../src/api/schema'

type Answer = Response | object | ((request: Request) => Response | Promise<Response>)

export interface Sent {
  method: string
  path: string
  body: unknown // the parsed JSON, an upload's length in bytes, or null
}

// What a request sent: JSON parsed, an upload (application/octet-stream) as its length, anything else as null
async function bodyOf(request: Request): Promise<unknown> {
  const type = request.headers.get('Content-Type')?.split(';')[0].trim()
  if (type === 'application/json') {
    const text = await request.clone().text()
    return text ? JSON.parse(text) : null
  }
  if (type === 'application/octet-stream') return (await request.clone().arrayBuffer()).byteLength
  return null
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
  // The API client sends a Request; the home button's script sends a path and its options
  const fetch = vi.fn(async (input: Request | string, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(new URL(input, window.location.href), init)
    const path = new URL(request.url).pathname
    sent.push({ method: request.method, path, body: await bodyOf(request) })
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

export function status(
  claimed: boolean,
  accepted = claimed,
  hotspot: { local_name: string } | null = null,
  hostname: unknown = 'tm-01',
) {
  return { claimed, eula: { version: '1', accepted }, theme: THEME, hotspot, hostname }
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

export const RESTART_FRIGATE: Fix = {
  kind: 'restart',
  text: 'Restart Frigate',
  unit: 'frigate.service',
  external: false,
}
export const RESCAN: Fix = { kind: 'rescan', text: 'Re-scan hardware', external: false }

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
  tm: { version: '0.8.0', commit: '2da617a1234567890abcdef1234567890abcdef1', branch: 'dev', modified: false, installing_user: 'pi' },
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
  const outcome = {
    time_kept_from_ntp: false,
    restarting: [],
    timezone_unknown: false,
    ntp_left_off: false,
    ntp_took_over: false,
  }
  return { ...TIME_STATE, ...outcome, ...changes }
}

// GET /cameras: the Cameras page's state. The rows and radars use the API's own types (schema.d.ts).
export type CameraRow = components['schemas']['CameraRow']
export type CamerasState = components['schemas']['CamerasState']
export type CameraRadar = components['schemas']['CameraRadar']

// An entry that is in step with Frigate: neutral key, all four zones, recording, no radar
export function cameraRow(changes: Partial<CameraRow> = {}): CameraRow {
  return {
    name: 'camera_1_3fa9c2',
    frigate_camera: 'oak_ave_wide',
    in_frigate: 'on',
    detect: true,
    neutral: true,
    duplicate_of: null,
    enabled: true,
    camera_radar: null,
    plate_recognizer: null,
    zones_missing: [],
    zones_off: [],
    zone_names: [],
    issues: [],
    ...changes,
  }
}

// A camera's other zones, one of each kind: known words, unknown words, and a name like an address
export const ZONE_NAMES = [
  { name: 'zone_lane_bus', check: null, friendly_name: null },
  { name: 'zone_maple', check: 'unknown_word' as const, friendly_name: null },
  { name: 'zone_nord', check: 'unknown_word' as const, friendly_name: null },
  { name: 'zone_1420_oak_st', check: 'pattern' as const, friendly_name: null },
]

// A zone key Frigate's zone editor made up from a name it couldn't use as a key: not checked, Frigate's name beside it
export const MADE_UP_ZONE = { name: 'zone_a9bacc03', check: null, friendly_name: 'Bus lane (north)' }

// A Frigate camera that no entry points at
export function newRow(frigate_camera = 'oak_ave_tele', changes: Partial<CameraRow> = {}): CameraRow {
  return cameraRow({
    name: null,
    frigate_camera,
    neutral: null,
    enabled: null,
    zones_missing: [],
    issues: [{ level: 'error', code: 'not_paired' }],
    ...changes,
  })
}

export const RADARS: CameraRadar[] = [
  { name: 'TM_RADAR_SERIAL_PORT_00', in_config: true, enabled: true, port_open: true },
  { name: 'TM_RADAR_SERIAL_PORT_01', in_config: true, enabled: false, port_open: false },
]

export function camerasState(changes: Partial<CamerasState> = {}): CamerasState {
  return { frigate: 'ok', plates: false, rows: [cameraRow()], radars: RADARS, ...changes }
}

// POST /cameras/{name}/reference: a take of the first camera's pictures, at a place with a point. Its zones are one
// with side lengths, one with none, one that is off in Frigate, and one with no outline.
export type ReferenceOut = components['schemas']['ReferenceOut']
type PictureOut = components['schemas']['PictureOut']
type PicturesState = components['schemas']['PicturesState']
export type ZoneFacts = components['schemas']['ZoneFacts']

export function zoneFacts(changes: Partial<ZoneFacts> = {}): ZoneFacts {
  return {
    key: 'zone_radar',
    color: '#40a05c',
    enabled: true,
    drawn: true,
    corners: [
      { letter: 'A', x: 0.169, y: 0.489 },
      { letter: 'B', x: 0.451, y: 0.358 },
      { letter: 'C', x: 0.821, y: 0.528 },
      { letter: 'D', x: 0.472, y: 0.796 },
    ],
    distances: [12, 7.3, 12, 7.3],
    sides: [
      { start: 'A', end: 'B', length: 12 },
      { start: 'B', end: 'C', length: 7.3 },
      { start: 'C', end: 'D', length: 12 },
      { start: 'D', end: 'A', length: 7.3 },
    ],
    inertia: 3,
    loitering_time: 0,
    speed_threshold: null,
    objects: ['car'],
    filters: {},
    ...changes,
  }
}

export function referenceOut(changes: Partial<ReferenceOut> = {}): ReferenceOut {
  return {
    ticket: 'made-up-ticket',
    expires_in: 600,
    stem: 'tm-reference_3f9a1c2e-si_camera_1_3fa9c2_20261118T183005Z',
    camera: 'camera_1_3fa9c2',
    survey_id: '3f9a1c2e-si',
    taken_at: '2026-11-18T18:30:05Z',
    width: 1536,
    height: 864,
    unit: 'm',
    zones: [
      zoneFacts(),
      zoneFacts({ key: 'zone_capture', color: '#7035b0', distances: [], sides: [] }),
      zoneFacts({ key: 'zone_far', color: '#be8f28', enabled: false, drawn: false, distances: [], sides: [] }),
      zoneFacts({ key: 'zone_lane_bus', color: null, drawn: false, corners: [], distances: [], sides: [] }),
    ],
    has_location: true,
    people: 'none',
    ...changes,
  }
}

// A reference picture kept on the device, as POST .../keep and GET /pictures answer it
export function pictureOut(changes: Partial<PictureOut> = {}): PictureOut {
  return {
    id: '0123456789abcdef',
    survey_id: '3f9a1c2e-si',
    camera: 'camera_1_3fa9c2',
    taken_at: '2026-11-18T18:30:05Z',
    reason: 'manual',
    mark: 'clear',
    after_restart: false,
    bytes: 412000,
    ...changes,
  }
}

// GET /pictures: this many pictures, newest first, and the device's totals
export function picturesState(pictures: number): PicturesState {
  const list = Array.from({ length: pictures }, (_, at) => pictureOut({ id: (at + 1).toString(16).padStart(16, '0') }))
  return { pictures: list, stored: pictures, stored_bytes: list.reduce((sum, one) => sum + one.bytes, 0) }
}

// GET /network: Ethernet connected, and the Wi-Fi radio on the unit's own hotspot
type NetworkState = components['schemas']['NetworkState']
export const NETWORK_STATE: NetworkState = {
  hostname: 'tm-ab12',
  local_name: 'tm-ab12.local',
  readable: true,
  ethernet: {
    connected: true,
    mac: '2C:CF:67:00:AB:11',
    addresses: ['192.168.1.57'],
    gateway: '192.168.1.1',
    dns: ['192.168.1.1', '1.1.1.1'],
  },
  wifi: {
    connected: true,
    mac: '2C:CF:67:00:AB:12',
    addresses: ['10.42.0.1'],
    gateway: null,
    dns: [],
    mode: 'hotspot',
    network: null,
    signal: null,
  },
  internet: 'reachable',
  hotspot: { enabled: true, active: true, name: 'TM-AB12', hidden: false, security: 'wpa2', address: '10.42.0.1' },
}

export function networkState(changes: Partial<NetworkState>): NetworkState {
  return { ...NETWORK_STATE, ...changes }
}

// GET /network/wifi: two saved networks (Home in range, Depot not) and five nearby, strongest first, scanned a minute
// ago. The password-only rule of Join is the Join dialog's; this table only has what the section lists.
type WifiNetworks = components['schemas']['WifiNetworks']
export const WIFI_NETWORKS: WifiNetworks = {
  readable: true,
  radio: 'on',
  saved: [
    { uuid: 'u-home', name: 'HomeNet', in_use: false, automatic: true, hidden: false, in_range: true, could_not_join: false },
    { uuid: 'u-depot', name: 'Depot', in_use: false, automatic: true, hidden: false, in_range: false, could_not_join: false },
  ],
  nearby: [
    { name: 'HomeNet', signal: 82, security: 'password', saved: true, in_use: false },
    { name: 'CafeGuest', signal: 64, security: 'open', saved: false, in_use: false },
    { name: 'OfficeCorp', signal: 55, security: 'enterprise', saved: false, in_use: false },
    { name: 'Neighbour', signal: 41, security: 'password', saved: false, in_use: false },
    { name: 'NewerRouter', signal: 30, security: 'wpa3', saved: false, in_use: false },
  ],
  scanned_seconds_ago: 90,
  join: null,
}

export function wifiNetworks(changes: Partial<WifiNetworks>): WifiNetworks {
  return { ...WIFI_NETWORKS, ...changes }
}

// GET /network/join: a join whose test passed, 3 minutes 12 seconds before the unit switches. The unit was on its
// hotspot (profile tm-hotspot) when it started.
type JoinState = components['schemas']['JoinState']
export const JOIN_COUNTDOWN: JoinState = {
  stage: 'countdown',
  network: 'Neighbour',
  saved: false,
  before: 'tm-hotspot',
  joined: true,
  reason: null,
  address: '192.168.1.80',
  internet: 'reachable',
  seconds_left: 192,
  finished_at: null,
}

export function joinState(changes: Partial<JoinState>): JoinState {
  return { ...JOIN_COUNTDOWN, ...changes }
}

// GET /sharing: a new device that has never been asked, with a place in use that has a location and a maintainer's
// server it could upload to. An admin sees the token's state; a viewer's `token` is null (see viewerSharing).
export type SharingState = components['schemas']['SharingState']
export const SHARING_NONE = { granted: false, at: null, notice_version: null }
export const SHARING_STATE: SharingState = {
  enabled: false,
  target: null,
  host: null,
  protocol: 'https',
  port: null,
  maintainer_host: 'tb.example.invalid',
  token: {
    name: 'thingsboard_access_token',
    title: 'ThingsBoard access token',
    set: false,
    ends_with: null,
    restarts: ['node-red-tm.service'],
  },
  share_data: SHARING_NONE,
  exact_location: SHARING_NONE,
  public_map: SHARING_NONE,
  public_map_live: false,
  notice_version: '1',
  notice_current: false,
  review_needed: false,
  has_location: true,
  precision: '1',
  writable: true,
  server: { state: 'off', at: null },
  download: null,
}

export function sharingState(changes: Partial<SharingState> = {}): SharingState {
  return { ...SHARING_STATE, ...changes }
}

// What an admin's Sharing state says about the download card: the database's size in bytes (700 MB) and the places with
// an exact location
export const DOWNLOAD_FACTS: NonNullable<SharingState['download']> = { database_bytes: 734003200, exact_places: 2, pictures: 0 }

// A device sharing data with the maintainer's server under the current notice, with the token set
export const SHARING_ON: SharingState = sharingState({
  enabled: true,
  target: 'maintainer',
  host: 'tb.example.invalid',
  token: { ...SHARING_STATE.token!, set: true, ends_with: '0001' },
  share_data: { granted: true, at: '2026-11-01T12:00:00+00:00', notice_version: '1' },
  notice_current: true,
  server: { state: 'waiting', at: null },
})
