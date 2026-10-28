// Logging in, and the pages shown while a new license agreement waits for an admin
import type { Module } from '..'
import LoginPage from './LoginPage.vue'
import WaitingPage from './WaitingPage.vue'
import WelcomePage from './WelcomePage.vue'

export default {
  id: 'auth',
  routes: [
    { path: '/login', component: LoginPage, meta: { bare: true } },
    { path: '/welcome', component: WelcomePage, meta: { bare: true } },
    { path: '/waiting', component: WaitingPage, meta: { bare: true } },
  ],
  nav: [],
} satisfies Module
