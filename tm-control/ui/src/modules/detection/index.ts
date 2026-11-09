// Object detection: the detector, the model Frigate runs, the models on the device, and what the model recognises
// (GET /models), for every logged-in user; for admins the Frigate+ API key (GET/POST/DELETE /secrets).
import { mdiCubeScan } from '@mdi/js'
import type { Module } from '..'
import DetectionPage from './DetectionPage.vue'

export default {
  id: 'detection',
  routes: [{ path: '/detection', component: DetectionPage }],
  nav: [{ title: 'Detection', to: '/detection', icon: mdiCubeScan }],
} satisfies Module
