// The pages, and where each navigation may go. nginx serves index.html for every path it doesn't know, and this
// router picks the page: an unclaimed device shows setup, a visitor without a session the login page, an outstanding
// license the license page (admins) or a waiting page (viewers), and admin-only pages need an admin.
import { createRouter, createWebHistory, type RouteLocationNormalized, type RouteLocationRaw, type RouterHistory } from 'vue-router'
import { whenSessionLost } from './api/client'
import type { User } from './api/types'
import { MODULES } from './modules'
import { useSession } from './stores/session'

declare module 'vue-router' {
  interface RouteMeta {
    adminOnly?: boolean // only admins may open it
    bare?: boolean // shown without the menu, before login or while the license is outstanding
  }
}

interface Access {
  claimed: boolean
  eulaAccepted: boolean
  user: User | null
}

function loginFor(to: RouteLocationNormalized): RouteLocationRaw {
  return to.fullPath === '/' ? '/login' : { path: '/login', query: { next: to.fullPath } }
}

// Where to send a navigation to `to` instead, or true to let it through
export function redirectFor(to: RouteLocationNormalized, access: Access): RouteLocationRaw | true {
  if (!access.claimed) return to.path === '/setup' ? true : '/setup'
  if (to.path === '/setup') return access.user ? '/' : '/login'
  if (!access.user) return to.path === '/login' ? true : loginFor(to)
  if (to.path === '/login') return '/'
  if (!access.eulaAccepted) {
    const page = access.user.role === 'admin' ? '/welcome' : '/waiting'
    return to.path === page ? true : page
  }
  if (to.path === '/welcome' || to.path === '/waiting') return '/'
  if (to.meta.adminOnly && access.user.role !== 'admin') return '/'
  return true
}

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({
    history,
    routes: [...MODULES.flatMap((module) => module.routes), { path: '/:unknown(.*)*', redirect: '/' }],
  })

  router.beforeEach(async (to) => {
    const session = useSession()
    await session.load()
    // Never loaded: App.vue shows the error instead of the page. A later refresh that failed leaves the last known
    // state, which keeps guarding.
    if (!session.loaded) return true
    return redirectFor(to, session)
  })

  // A call answered 401: the session ended (logged out elsewhere, password changed, or user removed)
  whenSessionLost(() => {
    useSession().sessionEnded()
    void router.push(loginFor(router.currentRoute.value))
  })
  return router
}
