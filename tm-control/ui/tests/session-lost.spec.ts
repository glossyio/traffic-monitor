// A 401 means the session ended, except where it answers a password the user typed (ruling R18).
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import { ADMIN, apiError, fakeApi, session, status } from './fake-api'
import { click, field, mountApp } from './mount'

function loggedIn(answers: Record<string, unknown>) {
  return fakeApi({
    'GET /api/v1/setup/status': status(true),
    'GET /api/v1/auth/session': session(true, ADMIN),
    ...(answers as object),
  })
}

describe('a 401 from the API', () => {
  beforeEach(() => document.body.replaceChildren())

  it('sends the browser to the login page, to come back afterwards', async () => {
    loggedIn({ 'GET /api/v1/users': apiError(401, 'unauthenticated', 'Log in to continue.') })
    const { router } = await mountApp('/users')
    await flushPromises() // the page's call, its 401, and the navigation it starts
    await flushPromises()
    expect(router.currentRoute.value.fullPath).toBe('/login?next=/users')
  })

  it('is a form error on the account page when the current password is wrong', async () => {
    loggedIn({ 'POST /api/v1/account/password': apiError(401, 'unauthenticated', 'The current password is wrong.') })
    const { wrapper, router } = await mountApp('/account')
    await field(wrapper, 'Current password').setValue('not it at all')
    await field(wrapper, 'New password').setValue('new pass 1234')
    await field(wrapper, 'Confirm new password').setValue('new pass 1234')
    await click(wrapper, 'Change password')
    expect(router.currentRoute.value.fullPath).toBe('/account')
    expect(wrapper.text()).toContain('The current password is wrong.')
  })

  it('is a form error on the login page when the password is wrong', async () => {
    fakeApi({
      'GET /api/v1/setup/status': status(true),
      'GET /api/v1/auth/session': session(true, null),
      'POST /api/v1/auth/login': apiError(401, 'unauthenticated', 'The username or password is wrong.'),
    })
    const { wrapper, router } = await mountApp('/login?next=/account')
    await field(wrapper, 'Username').setValue('owner')
    await field(wrapper, 'Password').setValue('wrong password')
    await click(wrapper, 'Log in')
    expect(router.currentRoute.value.fullPath).toBe('/login?next=/account')
    expect(wrapper.text()).toContain('The username or password is wrong.')
  })
})
