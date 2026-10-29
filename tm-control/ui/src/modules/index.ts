// The app's features. Each module's index.ts lists its pages (routes) and its entries in the menu (nav).
import type { RouteRecordRaw } from 'vue-router'
import account from './account'
import auth from './auth'
import device from './device'
import home from './home'
import setup from './setup'
import status from './status'
import time from './time'

export interface NavItem {
  title: string
  to: string
  icon: string // an @mdi/js icon path
  adminOnly?: boolean
}

export interface Module {
  id: string
  routes: RouteRecordRaw[]
  nav: NavItem[]
}

// In menu order
export const MODULES: Module[] = [home, status, device, time, account, auth, setup]
