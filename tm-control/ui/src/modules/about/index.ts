// The About page (/about): what the project is, what it is built on, and the licenses. It makes no request of its own.
import { mdiInformationOutline } from '@mdi/js'
import type { Module } from '..'
import AboutPage from './AboutPage.vue'

export default {
  id: 'about',
  routes: [{ path: '/about', component: AboutPage }],
  nav: [{ title: 'About', to: '/about', icon: mdiInformationOutline }],
} satisfies Module
