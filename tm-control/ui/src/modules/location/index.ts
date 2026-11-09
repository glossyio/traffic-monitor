// Where the unit is (GET/PUT/DELETE /surveys), for admins only: the place in use, the precision the database stores
// locations at, and the list of places. The API refuses viewers, because the places hold exact coordinates.
import { mdiMapMarkerOutline } from '@mdi/js'
import type { Module } from '..'
import LocationPage from './LocationPage.vue'

export default {
  id: 'location',
  routes: [{ path: '/location', component: LocationPage, meta: { adminOnly: true } }],
  nav: [{ title: 'Location', to: '/location', icon: mdiMapMarkerOutline, adminOnly: true }],
} satisfies Module
