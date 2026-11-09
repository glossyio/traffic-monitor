// Where the router sends each navigation, given what /setup/status and /auth/session say.
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createAppRouter } from '../src/router'
import { useSession } from '../src/stores/session'
import { ADMIN, VIEWER, fakeApi, session, status } from './fake-api'

function device(claimed: boolean, user: object | null, accepted = claimed) {
  return fakeApi({
    'GET /api/v1/setup/status': status(claimed, accepted),
    'GET /api/v1/auth/session': session(claimed, user, accepted),
  })
}

async function landing(path: string) {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  return router.currentRoute.value.fullPath
}

describe('router', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('sends an unclaimed device to setup', async () => {
    device(false, null)
    expect(await landing('/')).toBe('/setup')
    expect(await landing('/login')).toBe('/setup')
  })

  it('sends a visitor without a session to the login page, to come back afterwards', async () => {
    device(true, null)
    expect(await landing('/account')).toBe('/login?next=/account')
    expect(await landing('/')).toBe('/login')
  })

  it("keeps a viewer off the users page", async () => {
    device(true, VIEWER)
    expect(await landing('/users')).toBe('/')
  })

  it('lets a viewer open the Status, Device, and Date and time pages', async () => {
    device(true, VIEWER)
    expect(await landing('/status')).toBe('/status')
    expect(await landing('/device')).toBe('/device')
    expect(await landing('/time')).toBe('/time')
  })

  it('has no page under /system, which nginx sends to Cockpit', () => {
    device(true, ADMIN)
    const paths = createAppRouter(createMemoryHistory()).getRoutes().map((route) => route.path)
    expect(paths.filter((path) => path === '/system' || path.startsWith('/system/'))).toEqual([])
  })

  it('lets an admin open the users page', async () => {
    device(true, ADMIN)
    expect(await landing('/users')).toBe('/users')
  })

  it('sends an admin to the license page while a new license is outstanding', async () => {
    device(true, ADMIN, false)
    expect(await landing('/')).toBe('/welcome')
    expect(await landing('/users')).toBe('/welcome')
  })

  it('tells a viewer to wait while a new license is outstanding', async () => {
    device(true, VIEWER, false)
    expect(await landing('/account')).toBe('/waiting')
  })

  it('leaves setup and the license pages once they are done', async () => {
    device(true, ADMIN)
    expect(await landing('/setup')).toBe('/')
    expect(await landing('/welcome')).toBe('/')
    expect(await landing('/login')).toBe('/')
  })

  it('keeps guarding with what it last knew when a refresh fails', async () => {
    const api = device(true, VIEWER)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    api.fetch.mockRejectedValue(new TypeError('Failed to fetch')) // the device stops answering
    await useSession().refresh()
    expect(useSession().loadError).not.toBe('')
    await router.push('/users')
    expect(router.currentRoute.value.fullPath).toBe('/')
  })

  it('loads the status and session once, not on every navigation', async () => {
    const api = device(true, ADMIN)
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    await router.push('/account')
    await router.push('/users')
    expect(api.sent.map((r) => r.path).sort()).toEqual(['/api/v1/auth/session', '/api/v1/setup/status'])
  })
})
