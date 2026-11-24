// The About page: what the project is, what it is built on, and the licenses. It asks the device for nothing.
import type { VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import credits from '../src/modules/about/credits.json'
import { ADMIN, VIEWER, signedIn } from './fake-api'
import { mountApp } from './mount'

// The pages in the menu, in order. The drawer's second list (who is signed in, Log out) is not one of them.
function menu(wrapper: VueWrapper) {
  return wrapper
    .find('.v-navigation-drawer .v-list')
    .findAll('.v-list-item-title')
    .map((t) => t.text().trim())
}

async function aboutPage() {
  signedIn(VIEWER)
  return (await mountApp('/about')).wrapper
}

// The section whose h2 is `title`
function section(wrapper: VueWrapper, title: string) {
  const found = wrapper.findAll('section').find((s) => s.find('h2').text() === title)
  expect(found, `a section "${title}"`).toBeDefined()
  return found!
}

const OUTSIDE_LINKS = [
  ['trafficmonitor.ai', 'https://www.trafficmonitor.ai/'],
  ['Documentation', 'https://docs.trafficmonitor.ai/'],
  ['Source code on GitHub', 'https://github.com/glossyio/traffic-monitor'],
  ['Roadway Biome', 'https://www.roadwaybiome.com/'],
]

describe('the About page', () => {
  beforeEach(() => document.body.replaceChildren())

  it('is the last entry in the menu, for a viewer and for an admin', async () => {
    signedIn(VIEWER)
    const viewer = (await mountApp('/about')).wrapper
    expect(menu(viewer).at(-1)).toBe('About')
    expect(viewer.find('h1').text()).toBe('About')
    viewer.unmount()

    signedIn(ADMIN)
    const admin = (await mountApp('/about')).wrapper
    expect(menu(admin).at(-1)).toBe('About')
    expect(menu(admin).at(-2)).toBe('Users')
  })

  it('asks the device for nothing of its own', async () => {
    const { sent } = signedIn(VIEWER)
    await mountApp('/about')
    const paths = new Set(sent.map((s) => s.path))
    expect([...paths].sort()).toEqual(['/api/v1/auth/session', '/api/v1/setup/status'])
  })

  it('says what the project is and links to its four places', async () => {
    const page = await aboutPage()
    expect(page.text()).toContain('open source roadway counter and speed monitor')
    expect(page.text()).toContain('maintained by Roadway Biome')
    for (const [text, href] of OUTSIDE_LINKS) {
      // The repository is linked again, by its address, in the license notice
      const links = page.findAll(`a[href="${href}"]`).filter((a) => a.text() === text)
      expect(links, href).toHaveLength(1)
    }
  })

  it('says whose product Roadway Biome is, with a link to the company', async () => {
    const page = await aboutPage()
    expect(page.text()).toContain('Roadway Biome is a product of Green Dormer Solutions, LLC.')
    const links = page.findAll('a[href="https://www.greendormer.com/"]')
    expect(links.map((a) => a.text())).toEqual(['Green Dormer Solutions, LLC'])
  })

  it('sends the reader to the Device page for versions', async () => {
    const page = await aboutPage()
    expect(page.text()).toContain('Software versions are on the Device page.')
    expect(page.find('a[href="/device"]').exists()).toBe(true)
  })

  it('puts Frigate and Node-RED first, each with what it does', async () => {
    const built = section(await aboutPage(), 'Built on')
    expect(built.findAll('a').map((a) => a.text())).toEqual(['Frigate NVR', 'Node-RED'])
    for (const row of credits.filter((r) => r.group === 'built-on')) {
      expect(row.does, `${row.name} has a "does" sentence`).toBeTruthy()
      expect(built.text()).toContain(row.does)
      expect(built.text()).toContain(row.license)
    }
  })

  it('lists every other credit under its group, with its license and a link', async () => {
    const page = await aboutPage()
    const headings = page.findAll('h2, h3').map((h) => h.text())
    const order = ['Built on', 'Also on this device', 'Map', 'Licenses and source code']
    expect(headings.filter((h) => order.includes(h))).toEqual(order)
    const groups = ['Video and detection', 'Data and dashboards', 'The control app', 'The device']
    expect(headings.filter((h) => groups.includes(h))).toEqual(groups)

    for (const row of credits) {
      const links = page.findAll(`a[href="${row.url}"]`).filter((a) => a.text() === row.name)
      expect(links, row.name).toHaveLength(1)
      const item = links[0].element.closest('.v-list-item')
      expect(item, `${row.name} is in a list item`).not.toBeNull()
      expect(item!.textContent).toContain(row.license)
      if ('note' in row) expect(item!.textContent).toContain(row.note)
    }
  })

  // Whitespace between inline elements doesn't survive Vue's template condensing, so the gap is a Vuetify class
  it('spaces the four links, and each credit’s name from its license, with gap classes', async () => {
    const page = await aboutPage()
    const places = page.find('a[href="https://www.trafficmonitor.ai/"]').element.parentElement!
    expect(places.querySelectorAll('a')).toHaveLength(4)
    expect(places.className).toMatch(/\bgc-\d+\b/)
    const rows = page.find('.v-main').findAll('.v-list-item')
    expect(rows).toHaveLength(credits.length)
    for (const row of rows) {
      const line = row.find('a').element.parentElement!
      expect(line.className, row.find('a').text()).toMatch(/\bgc-\d+\b/)
    }
  })

  // The list item hides what overflows it, and the focus ring is drawn 4 px outside a link (pa-1 is 4 px)
  it('lets each credit’s row wrap, and leaves room around its link for the focus ring', async () => {
    const page = await aboutPage()
    for (const row of page.find('.v-main').findAll('.v-list-item')) {
      const line = row.find('a').element.parentElement!
      expect(line.classList.contains('flex-wrap'), row.find('a').text()).toBe(true)
      expect(line.classList.contains('pa-1'), row.find('a').text()).toBe(true)
    }
  })

  it('opens every outside link in a new tab without a referrer', async () => {
    const page = await aboutPage()
    const outside = page.findAll('a[href^="https://"]')
    expect(outside.length).toBeGreaterThan(credits.length)
    for (const a of outside) {
      expect(a.attributes('target'), a.attributes('href')).toBe('_blank')
      expect(a.attributes('rel'), a.attributes('href')).toBe('noopener noreferrer')
    }
  })

  it('credits the map in OpenFreeMap’s words', async () => {
    const map = section(await aboutPage(), 'Map')
    for (const href of ['https://openfreemap.org', 'https://www.openmaptiles.org/', 'https://www.openstreetmap.org/copyright']) {
      expect(map.find(`a[href="${href}"]`).exists(), href).toBe(true)
    }
    expect(map.text()).toContain('© OpenMapTiles')
    expect(map.text()).toContain('Data from OpenStreetMap')
    expect(map.text()).toContain('Open Database License')
  })

  it('carries the notices', async () => {
    const text = (await aboutPage()).text()
    for (const sentence of [
      'Copyright © TrafficMonitor.ai (Traffic Monitor), Roadway Biome, and Green Dormer Solutions, LLC.',
      'GNU General Public License, version 3',
      'It comes with no warranty',
      'write to info@roadwaybiome.com',
      'Frigate, Frigate NVR, and Frigate+ are trademarks of Frigate, Inc.',
      'Node-RED is a trademark of the OpenJS Foundation.',
      'Raspberry Pi is a trademark of Raspberry Pi Ltd',
      'FFmpeg is a trademark of Fabrice Bellard.',
      'The licenses of Raspberry Pi OS\'s own packages are on the device, in /usr/share/doc.',
    ]) {
      expect(text).toContain(sentence)
    }
    const page = await aboutPage()
    expect(page.find('a[href="mailto:info@roadwaybiome.com"]').exists()).toBe(true)
    expect(page.find('a[href="https://github.com/glossyio/traffic-monitor/blob/main/LICENSE"]').text()).toBe(
      'GNU General Public License, version 3',
    )
    expect(page.find('a[href="/third-party-licenses.txt"]').text()).toBe('License texts of the libraries built into this app')
  })

  it('hides the parade behind the cone at the very end', async () => {
    const page = await aboutPage()
    const buttons = page.find('main').findAll('button')
    expect(buttons.at(-1)?.attributes('aria-label')).toBe('Count some traffic')
    expect(page.text()).not.toContain('Counted so far')
  })
})
