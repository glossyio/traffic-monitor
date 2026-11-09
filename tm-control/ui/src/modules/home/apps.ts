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
  cockpit: { icon: mdiServerOutline, description: 'Updates, services, and logs. Log in with the system password.' },
}

export function appDetails(id: string): AppDetails {
  return DETAILS[id] ?? { icon: mdiApplicationOutline, description: '' }
}
