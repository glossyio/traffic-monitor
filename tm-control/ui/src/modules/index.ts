// The app's features. Each module's index.ts lists its pages (routes) and its entries in the menu (nav).
import type { RouteRecordRaw } from 'vue-router'
import about from './about'
import account from './account'
import auth from './auth'
import cameras from './cameras'
import detection from './detection'
import device from './device'
import home from './home'
import location from './location'
import network from './network'
import setup from './setup'
import sharing from './sharing'
import status from './status'
import time from './time'
import update from './update'

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
export const MODULES: Module[] = [home, status, device, network, detection, cameras, location, sharing, time, update, account, about, auth, setup]
