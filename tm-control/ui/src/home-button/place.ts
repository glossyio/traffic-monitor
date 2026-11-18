// The home button's logic as plain functions: which app a page belongs to, where the button sits, what it remembers, and
// the tab's title. No imports, so the button's script stays small and the tests need no browser.

export type Side = 'left' | 'right'

// `y` is the button's center as a fraction of the window's height, 0 to 1
export interface Place {
  side: Side
  y: number
  tucked: boolean
}

export const APPS = ['dashboard', 'frigate', 'ui', 'nr', 'feeds'] as const

export const STORAGE_KEY = 'tm-home-button'
// A window under this many pixels wide is narrow
export const NARROW = 600
// A movement of more than this many pixels is a drag, not a tap
export const DRAG_PX = 8
// Dropped within this many pixels of an edge, the button tucks
export const TUCK_PX = 12
// The button stays this many pixels inside the window
const MARGIN_PX = 8

// The app a page belongs to, by the first segment of its path
export function appOf(pathname: string): string | null {
  const first = pathname.split('/')[1]
  return (APPS as readonly string[]).includes(first) ? first : null
}

export function defaultPlace(app: string, narrow: boolean): Place {
  // Frigate's bottom bar on a narrow screen
  return { side: 'right', y: narrow && app === 'frigate' ? 0.72 : 0.9, tucked: false }
}

// Where the button settles when dropped at (x, y) in a window of this size
export function dropped(x: number, y: number, width: number, height: number): Place {
  return {
    side: x < width / 2 ? 'left' : 'right',
    y: Math.min(1, Math.max(0, y / height)),
    tucked: x <= TUCK_PX || x >= width - TUCK_PX,
  }
}

export function isDrag(dx: number, dy: number): boolean {
  return Math.hypot(dx, dy) > DRAG_PX
}

// The button's top in pixels, kept at least 8 px inside the window (and never above it)
export function topOf(place: Place, height: number, size: number): number {
  const top = place.y * height - size / 2
  return Math.max(MARGIN_PX, Math.min(top, height - size - MARGIN_PX))
}

// The tab's title with the device's name in front, once
export function titled(hostname: string, title: string): string {
  const text = title.trim()
  if (!hostname) return title
  if (!text || text === hostname || text.startsWith(`${hostname} · `)) return text || hostname
  return `${hostname} · ${text}`
}

function isPlace(value: unknown): value is Place {
  if (typeof value !== 'object' || value === null) return false
  const { side, y, tucked } = value as Record<string, unknown>
  return (side === 'left' || side === 'right') && typeof y === 'number' && Number.isFinite(y) && y >= 0 && y <= 1
    && typeof tucked === 'boolean'
}

// What the browser remembers, per app. Anything unusable is left out; this never throws.
export function readPlaces(storage: Pick<Storage, 'getItem'> | null): Record<string, Place> {
  const places: Record<string, Place> = {}
  try {
    const stored: unknown = JSON.parse(storage?.getItem(STORAGE_KEY) ?? '')
    if (typeof stored !== 'object' || stored === null || Array.isArray(stored)) return places
    for (const app of APPS) {
      const place = (stored as Record<string, unknown>)[app]
      if (isPlace(place)) places[app] = { side: place.side, y: place.y, tucked: place.tucked }
    }
  } catch {
    // No storage, or nothing readable in it: the defaults apply
  }
  return places
}

// Remembers one app's place beside the others. Never throws: a private window may refuse to store.
export function savePlace(storage: Pick<Storage, 'getItem' | 'setItem'> | null, app: string, place: Place): void {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify({ ...readPlaces(storage), [app]: place }))
  } catch {
    // Not remembered; the button still works
  }
}
