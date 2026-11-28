// The Software update page (GET /update, POST /update/check, POST /update/start, GET /update/log), for admins only:
// what is installed, a check against GitHub, the start of an update, and the run as it goes. The API refuses viewers.
import { mdiUpdate } from '@mdi/js'
import type { Module } from '..'
import UpdatePage from './UpdatePage.vue'

export default {
  id: 'update',
  routes: [{ path: '/update', component: UpdatePage, meta: { adminOnly: true } }],
  nav: [{ title: 'Software update', to: '/update', icon: mdiUpdate, adminOnly: true }],
} satisfies Module
