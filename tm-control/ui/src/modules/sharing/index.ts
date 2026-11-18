// What the device shares (GET and PUT /sharing): the server it uploads to, the access token, and the three choices
// about what leaves the device. Every signed-in user may read the page; only admins see the form.
import { mdiShareVariantOutline } from '@mdi/js'
import type { Module } from '..'
import SharingPage from './SharingPage.vue'

export default {
  id: 'sharing',
  routes: [{ path: '/sharing', component: SharingPage }],
  nav: [{ title: 'Sharing', to: '/sharing', icon: mdiShareVariantOutline }],
} satisfies Module
