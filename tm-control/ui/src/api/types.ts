// The bodies the API answers with, as the routers in tm-control/backend/tm_control/modules/ return them. The API
// doesn't declare response schemas yet, so schema.d.ts types these as unknown: keep this file in step with the routers.
import type { components } from './schema'

export interface User {
  id: number
  username: string
  role: 'admin' | 'viewer'
  created_at: string
}

// GET /setup/status
export interface SetupStatus {
  claimed: boolean
  eula: { version: string; accepted: boolean }
  theme: { font: string; colors: Record<string, string> }
}

// GET /auth/session
export interface Session {
  claimed: boolean
  eula_accepted: boolean
  user: User | null
}

// GET /setup/eula
export interface Eula {
  version: string
  markdown: string
}

export interface DeviceApp {
  id: string
  path: string
  title: string
  admin_only: boolean
}

// GET /system/device
export interface Device {
  hostname: string
  serial: string
  tm_version: string
  time: string
  apps: DeviceApp[]
}

// GET /jobs/{id} declares its schema
export type Job = components['schemas']['Job']
