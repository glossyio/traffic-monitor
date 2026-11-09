// First run: claim the device with its setup code (GET /setup/status, /setup/eula; POST /setup/claim)
import type { Module } from '..'
import SetupPage from './SetupPage.vue'

export default {
  id: 'setup',
  routes: [{ path: '/setup', component: SetupPage, meta: { bare: true } }],
  nav: [],
} satisfies Module
