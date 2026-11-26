// Where the unit is (GET/PUT/DELETE /surveys), for admins only: the place in use, the precision the database stores
// locations at, and the list of places; and how the unit is mounted at the place in use (/surveys/{id}/mounting), a
// page the Location page leads to, with no menu entry of its own. The API refuses viewers, because the places hold
// exact coordinates.
import { mdiMapMarkerOutline } from '@mdi/js'
import type { Module } from '..'
import LocationPage from './LocationPage.vue'
import MountingPage from './MountingPage.vue'

export default {
  id: 'location',
  routes: [
    { path: '/location', component: LocationPage, meta: { adminOnly: true } },
    { path: '/location/mounting', component: MountingPage, meta: { adminOnly: true, title: 'Mounting' } },
  ],
  nav: [{ title: 'Location', to: '/location', icon: mdiMapMarkerOutline, adminOnly: true }],
} satisfies Module
