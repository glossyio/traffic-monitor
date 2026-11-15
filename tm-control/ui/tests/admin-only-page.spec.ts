// What a viewer sees after nginx sends them away from an app that needs the administrator.
import { describe, expect, it } from 'vitest'
import { VIEWER, fakeApi, session, status } from './fake-api'
import { mountApp } from './mount'

describe('the administrators-only page', () => {
  async function open() {
    fakeApi({
      'GET /api/v1/setup/status': status(true),
      'GET /api/v1/auth/session': session(true, VIEWER),
    })
    return mountApp('/admin-only')
  }

  it('says who the viewer is and what the app needs', async () => {
    const { wrapper } = await open()
    expect(wrapper.find('h1').text()).toBe('This app is for administrators')
    expect(wrapper.text()).toContain(
      "You're logged in as alice, a viewer. The app you opened needs this device's administrator.",
    )
  })

  it('offers Home and Log out', async () => {
    const { wrapper } = await open()
    const links = (text: string) => wrapper.find('main').findAll('a').filter((a) => a.text().trim() === text)
    expect(links('Home').map((a) => a.attributes('href'))).toEqual(['/'])
    expect(links('Log out').map((a) => a.attributes('href'))).toEqual(['/logout'])
  })

  it('keeps the menu and names the page in the tab', async () => {
    const { wrapper } = await open()
    expect(wrapper.find('.v-navigation-drawer').exists()).toBe(true)
    expect(document.title).toBe('tm-01 · Administrators only | Traffic Monitor')
  })
})
