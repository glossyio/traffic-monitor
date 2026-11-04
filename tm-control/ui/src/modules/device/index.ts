// The device itself: its facts and versions (GET /system/info), and for admins the diagnostics file and reboot or
// shut down (GET /system/diagnostics, POST /system/reboot, /system/power-off), and the entered secrets
// (GET/POST/DELETE /secrets). Not /system: nginx sends that to Cockpit.
import { mdiChip } from '@mdi/js'
import type { Module } from '..'
import DevicePage from './DevicePage.vue'

export default {
  id: 'device',
  routes: [{ path: '/device', component: DevicePage }],
  nav: [{ title: 'Device', to: '/device', icon: mdiChip }],
} satisfies Module
