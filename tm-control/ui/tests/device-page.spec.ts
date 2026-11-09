// The Device page: the device card, software, and for admins the diagnostics and the power buttons.
import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ADMIN, SYSTEM_INFO, VIEWER, apiError, json, signedIn } from './fake-api'
import { click, clickInDialog, dialogText, mountApp } from './mount'

const INFO = 'GET /api/v1/system/info'
const DIAGNOSTICS = 'tm-control diagnostics\nhostname: tm-fake\n'

function headings(wrapper: VueWrapper) {
  return wrapper.findAll('h2').map((h) => h.text().trim())
}

function diagnosticsFile() {
  return new Response(DIAGNOSTICS, {
    status: 200,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Content-Disposition': 'attachment; filename="tm-diagnostics-tm-fake-20261028-143200.txt"',
    },
  })
}

describe('the Device page', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    vi.restoreAllMocks()
    Reflect.deleteProperty(document, 'execCommand') // jsdom has none; the copy tests add their own
  })

  it('shows the device card with the storage line and its bar', async () => {
    signedIn(VIEWER, { [INFO]: SYSTEM_INFO })
    const { wrapper } = await mountApp('/device')
    expect(headings(wrapper)[0]).toBe('tm-fake')
    expect(wrapper.text()).toContain('Raspberry Pi 5 Model B Rev 1.0, 8 GB memory')
    expect(wrapper.text()).toContain('Traffic Monitor 0.8.0')
    expect(wrapper.text()).toContain('0000000012345678')
    expect(wrapper.text()).toContain('7.5 GB free of 58 GB')
    const bar = wrapper.find('[role="progressbar"][aria-label="Storage: 87% used"]')
    expect(bar.attributes('aria-valuenow')).toBe('87')
    expect(wrapper.text()).toContain('53 °C')
  })

  it('lists the software versions and the commit', async () => {
    signedIn(VIEWER, { [INFO]: SYSTEM_INFO })
    const text = (await mountApp('/device')).wrapper.text()
    for (const part of ['Frigate', '0.18.1', 'Node-RED', '5.0.8', 'go2rtc', '1.9.14', 'nginx', '1.31.0', '2da617a on dev']) {
      expect(text).toContain(part)
    }
  })

  it('shows a viewer no Diagnostics or Power section', async () => {
    signedIn(VIEWER, { [INFO]: SYSTEM_INFO })
    const { wrapper } = await mountApp('/device')
    expect(headings(wrapper)).not.toContain('Diagnostics')
    expect(headings(wrapper)).not.toContain('Power')
    expect(wrapper.findAll('button').map((b) => b.text().trim())).toEqual([])
  })

  it('reboots only after the admin confirms, then says so in place', async () => {
    const api = signedIn(ADMIN, { [INFO]: SYSTEM_INFO, 'POST /api/v1/system/reboot': json(202, { action: 'reboot' }) })
    const { wrapper } = await mountApp('/device')
    await click(wrapper, 'Reboot the device')
    expect(dialogText()).toContain('Reboot the device?')
    expect(dialogText()).toContain('The device will be unreachable for about two minutes.')
    expect(api.sent.some((r) => r.method === 'POST')).toBe(false)

    await clickInDialog('Reboot')
    expect(api.sent.filter((r) => r.method === 'POST').map((r) => r.path)).toEqual(['/api/v1/system/reboot'])
    expect(wrapper.text()).toContain('Rebooting. This page will stop answering for about two minutes.')
  })

  it('shuts down only after the admin confirms', async () => {
    const api = signedIn(ADMIN, { [INFO]: SYSTEM_INFO, 'POST /api/v1/system/power-off': json(202, { action: 'power_off' }) })
    const { wrapper } = await mountApp('/device')
    await click(wrapper, 'Shut down the device')
    expect(dialogText()).toContain('The device will turn off. To start it again, unplug it and plug it back in.')
    await clickInDialog('Shut down')
    expect(api.sent.filter((r) => r.method === 'POST').map((r) => r.path)).toEqual(['/api/v1/system/power-off'])
  })

  it("shows the API's message, and not \"Rebooting\", when the device can't reboot right now", async () => {
    const refused =
      "The device can't reboot right now. Something, such as an update, is holding it off, or the control app isn't " +
      'allowed to; try again in a few minutes, and download the diagnostics if it keeps happening.'
    signedIn(ADMIN, { [INFO]: SYSTEM_INFO, 'POST /api/v1/system/reboot': apiError(409, 'conflict', refused) })
    const { wrapper } = await mountApp('/device')
    await click(wrapper, 'Reboot the device')
    await clickInDialog('Reboot')
    expect(wrapper.text()).toContain(refused)
    expect(wrapper.text()).not.toContain('Rebooting.')
  })

  it("downloads the diagnostics under the server's file name", async () => {
    signedIn(ADMIN, { [INFO]: SYSTEM_INFO, 'GET /api/v1/system/diagnostics': diagnosticsFile })
    // jsdom's createObjectURL can't read jsdom's own Blob, so stand in for it and keep what it was given
    const blobs: Blob[] = []
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      blobs.push(blob as Blob)
      return 'blob:http://localhost/diagnostics'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const saved: { name: string; href: string }[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      saved.push({ name: this.download, href: this.href })
    })
    const { wrapper } = await mountApp('/device')
    await click(wrapper, 'Download diagnostics')
    expect(saved).toEqual([
      { name: 'tm-diagnostics-tm-fake-20261028-143200.txt', href: 'blob:http://localhost/diagnostics' },
    ])
    expect(await blobs[0].text()).toBe(DIAGNOSTICS)
  })

  // The browser's copy command: what it would copy (the focused textarea's selected text), and whether it agrees
  function execCommandThat(agrees: boolean) {
    const copied: string[] = []
    const execCommand = vi.fn((command: string) => {
      const area = document.activeElement as HTMLTextAreaElement
      if (command === 'copy') copied.push(area.value.slice(area.selectionStart, area.selectionEnd))
      return agrees
    })
    Object.defineProperty(document, 'execCommand', { value: execCommand, configurable: true })
    return copied
  }

  // iOS Safari ignores select() on a read-only textarea; a page must set the selection range itself
  function selectDoesNothing() {
    vi.spyOn(HTMLTextAreaElement.prototype, 'select').mockImplementation(() => {})
  }

  it('copies the diagnostics where the clipboard API is missing (plain HTTP), and says so', async () => {
    signedIn(ADMIN, { [INFO]: SYSTEM_INFO, 'GET /api/v1/system/diagnostics': diagnosticsFile })
    const copied = execCommandThat(true)
    selectDoesNothing()
    const { wrapper } = await mountApp('/device')
    await click(wrapper, 'Copy')
    expect(copied).toEqual([DIAGNOSTICS])
    expect(wrapper.text()).toContain('Copied.')
  })

  it("shows the text, selected, to copy by hand when the browser didn't let the page copy", async () => {
    signedIn(ADMIN, { [INFO]: SYSTEM_INFO, 'GET /api/v1/system/diagnostics': diagnosticsFile })
    execCommandThat(false)
    selectDoesNothing()
    const { wrapper } = await mountApp('/device')
    await click(wrapper, 'Copy')
    expect(wrapper.text()).toContain('Copy the text from the box below.')
    const box = wrapper.find<HTMLTextAreaElement>('main textarea')
    expect(box.element.value).toBe(DIAGNOSTICS)
    expect(box.attributes('readonly')).toBeDefined()
    expect([box.element.selectionStart, box.element.selectionEnd]).toEqual([0, DIAGNOSTICS.length])
  })

  it('hides the box again once the diagnostics are downloaded', async () => {
    signedIn(ADMIN, { [INFO]: SYSTEM_INFO, 'GET /api/v1/system/diagnostics': diagnosticsFile })
    execCommandThat(false)
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:http://localhost/diagnostics')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const { wrapper } = await mountApp('/device')
    await click(wrapper, 'Copy')
    expect(wrapper.find('main textarea').exists()).toBe(true)
    await click(wrapper, 'Download diagnostics')
    expect(wrapper.find('main textarea').exists()).toBe(false)
  })
})
