// Where to go after login or setup. nginx sends a browser to /login?next=<the page it asked for>; following `next`
// blindly would let a link send someone to another site after they log in, so only this device's pages qualify.
import type { Router } from 'vue-router'

// The device's other apps, served by nginx next to this UI (container/revproxy/tm/locations/)
export const APP_PATHS = ['/dashboard', '/frigate', '/ui', '/nr', '/feeds', '/system', '/storefiles']

export type NextStep = { route: string } | { href: string }

// `spaPaths` are this app's own route paths. Anything that isn't one of them or one of the device's apps goes home.
export function nextStep(next: unknown, origin: string, spaPaths: string[]): NextStep {
  if (typeof next !== 'string' || next === '') return { route: '/' }
  let url: URL
  try {
    url = new URL(next, origin)
  } catch {
    return { route: '/' }
  }
  // The parsed URL decides, never the text: "/.//host" parses to the path "//host", which a browser reads as a site.
  if (url.origin !== origin) return { route: '/' }
  if (spaPaths.includes(url.pathname)) return { route: url.href.slice(url.origin.length) }
  if (APP_PATHS.some((path) => url.pathname === path || url.pathname.startsWith(`${path}/`))) return { href: url.href }
  return { route: '/' }
}

export async function goNext(router: Router, next: unknown) {
  const paths = router.getRoutes().map((route) => route.path)
  const step = nextStep(next, window.location.origin, paths)
  if ('href' in step) window.location.assign(step.href)
  else await router.push(step.route)
}
