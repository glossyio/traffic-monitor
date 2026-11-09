// The home page: the device card and a tile for each app (GET /system/device)
import { mdiHomeOutline } from '@mdi/js'
import type { Module } from '..'
import HomePage from './HomePage.vue'

export default {
  id: 'home',
  routes: [{ path: '/', component: HomePage }],
  nav: [{ title: 'Home', to: '/', icon: mdiHomeOutline }],
} satisfies Module
