// The cameras (GET/PUT /cameras), for admins only: each camera's record, radar, and plates settings. The API refuses
// viewers, and the page is a settings page.
import { mdiCctv } from '@mdi/js'
import type { Module } from '..'
import CamerasPage from './CamerasPage.vue'

export default {
  id: 'cameras',
  routes: [{ path: '/cameras', component: CamerasPage, meta: { adminOnly: true } }],
  nav: [{ title: 'Cameras', to: '/cameras', icon: mdiCctv, adminOnly: true }],
} satisfies Module
