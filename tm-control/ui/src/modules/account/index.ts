// One's own account (GET /account, POST /account/password) and the admin's list of users (/users)
import { mdiAccountCircleOutline, mdiAccountMultipleOutline } from '@mdi/js'
import type { Module } from '..'
import AccountPage from './AccountPage.vue'
import UsersPage from './UsersPage.vue'

export default {
  id: 'account',
  routes: [
    { path: '/account', component: AccountPage },
    { path: '/users', component: UsersPage, meta: { adminOnly: true } },
  ],
  nav: [
    { title: 'Account', to: '/account', icon: mdiAccountCircleOutline },
    { title: 'Users', to: '/users', icon: mdiAccountMultipleOutline, adminOnly: true },
  ],
} satisfies Module
