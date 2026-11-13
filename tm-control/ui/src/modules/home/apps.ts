// What each app tile on the home page says and shows, by the app ids that GET /system/device returns (APPS in
// tm-control/backend/tm_control/modules/system/router.py, which matches the revproxy location files).
import {
  mdiApplicationOutline,
  mdiCctv,
  mdiChartBar,
  mdiServerOutline,
  mdiSitemapOutline,
  mdiVideoOutline,
  mdiViewDashboardOutline,
} from '@mdi/js'
import type { DeviceApp } from '../../api/types'

export interface AppDetails {
  icon: string
  description: string
}

const DETAILS: Record<string, AppDetails> = {
  dashboard: { icon: mdiChartBar, description: 'Counts and speeds, and the data export.' },
  frigate: { icon: mdiCctv, description: 'The camera view and the objects it detects.' },
  'legacy-ui': { icon: mdiViewDashboardOutline, description: 'The older dashboard, which also shows air quality.' },
  nodered: { icon: mdiSitemapOutline, description: 'The flows that count and measure the traffic.' },
  feeds: { icon: mdiVideoOutline, description: "The camera's live video streams." },
  cockpit: {
    icon: mdiServerOutline,
    description: 'Services, logs, updates, and a terminal, on port 9090. Log in with the system password.',
  },
}

// systemUser is the system account's name (GET /system/device's system_user), which Cockpit's tile names when known
export function appDetails(id: string, systemUser: string | null = null): AppDetails {
  if (id === 'cockpit' && systemUser) {
    return {
      icon: DETAILS.cockpit.icon,
      description:
        `Services, logs, updates, and a terminal, on port 9090. Log in as ${systemUser} with the system password.`,
    }
  }
  return DETAILS[id] ?? { icon: mdiApplicationOutline, description: '' }
}

// A tile's link. An app nginx serves is a path on this page's own address; an app on its own port gets that port on
// the name the browser used (window.location.hostname keeps an IPv6 address's brackets). Always http: Cockpit, the one
// such app, is set up for plain HTTP. An answer with no port at all (an older tm-control, for a moment during an
// upgrade) is a path too, hence == null.
export function appHref(app: Pick<DeviceApp, 'path' | 'port'>, hostname: string = window.location.hostname): string {
  return app.port == null ? app.path : `http://${hostname}:${app.port}${app.path}`
}
