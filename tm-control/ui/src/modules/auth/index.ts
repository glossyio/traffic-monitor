// Logging in, the pages shown while a new license agreement waits for an admin, and the page for a viewer who
// opened an admin app
import type { Module } from '..'
import AdminOnlyPage from './AdminOnlyPage.vue'
import LoginPage from './LoginPage.vue'
import WaitingPage from './WaitingPage.vue'
import WelcomePage from './WelcomePage.vue'

export default {
  id: 'auth',
  routes: [
    { path: '/login', component: LoginPage, meta: { bare: true } },
    { path: '/welcome', component: WelcomePage, meta: { bare: true } },
    { path: '/waiting', component: WaitingPage, meta: { bare: true } },
    { path: '/admin-only', component: AdminOnlyPage, meta: { title: 'Administrators only' } },
  ],
  nav: [],
} satisfies Module
