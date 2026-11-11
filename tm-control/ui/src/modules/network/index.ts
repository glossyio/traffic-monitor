// The unit's network as the person sees it: names, Ethernet and Wi-Fi addresses, the internet, and the hotspot
// (GET /network). Every signed-in user may open it.
import { mdiLan } from '@mdi/js'
import type { Module } from '..'
import NetworkPage from './NetworkPage.vue'

export default {
  id: 'network',
  routes: [{ path: '/network', component: NetworkPage }],
  nav: [{ title: 'Network', to: '/network', icon: mdiLan }],
} satisfies Module
