// The device's date, time, time zone, and NTP (GET /time, GET /time/timezones, POST /time): any user sees them,
// admins change them
import { mdiClockOutline } from '@mdi/js'
import type { Module } from '..'
import TimePage from './TimePage.vue'

export default {
  id: 'time',
  routes: [{ path: '/time', component: TimePage }],
  nav: [{ title: 'Date and time', to: '/time', icon: mdiClockOutline }],
} satisfies Module
