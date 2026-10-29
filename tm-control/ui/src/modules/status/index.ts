// The device's checks, and restarting what they name (GET /status, POST /status/rescan, POST /services/{unit}/restart)
import { mdiHeartPulse } from '@mdi/js'
import type { Module } from '..'
import StatusPage from './StatusPage.vue'

export default {
  id: 'status',
  routes: [{ path: '/status', component: StatusPage }],
  nav: [{ title: 'Status', to: '/status', icon: mdiHeartPulse }],
} satisfies Module
