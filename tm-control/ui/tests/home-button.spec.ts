// The home button on an app's page: where it draws, what it shows once the device answers, and how it moves and tucks.
import { readFileSync } from 'node:fs'
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { start } from '../src/home-button/main'
import { apiError, fakeApi, THEME } from './fake-api'

const DEVICE = { hostname: 'tm-01', theme: THEME }

function host(): HTMLElement {
  return document.getElementById('tm-home-button')!
}

function link(): HTMLAnchorElement {
  return host().shadowRoot!.querySelector('a')!
}

function handle(): HTMLButtonElement {
  return host().shadowRoot!.querySelector('button')!
}

function isHidden(element: Element): boolean {
  return element.hasAttribute('hidden')
}

function pointer(type: string, [clientX, clientY]: number[], buttons = 0) {
  link().dispatchEvent(new MouseEvent(type, { clientX, clientY, buttons, bubbles: true, cancelable: true }))
}

// A move while the button is down reports `buttons: 1`, as a mouse, a finger, and a pen all do
function drag(from: number[], to: number[]) {
  pointer('pointerdown', from, 1)
  pointer('pointermove', to, 1)
  pointer('pointerup', to)
}

// Runs fn, then clicks the link, and says whether the click was left to go home. The listener on the shadow root runs
// after the link's own, and stops jsdom from trying to navigate.
function clickIsLetThrough(fn: () => void): boolean {
  fn()
  let letThrough = false
  const seen = (event: Event) => {
    letThrough = !event.defaultPrevented
    event.preventDefault()
  }
  host().shadowRoot!.addEventListener('click', seen)
  link().dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
  host().shadowRoot!.removeEventListener('click', seen)
  return letThrough
}

beforeEach(() => {
  document.getElementById('tm-home-button')?.remove()
  localStorage.clear()
  document.title = ''
  vi.stubGlobal('innerWidth', 1000)
  vi.stubGlobal('innerHeight', 800)
  fakeApi({})
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('draws a link home on an app page, and nothing on any other page', async () => {
  start(window, null)
  expect(document.getElementById('tm-home-button')).toBeNull()
  start(window, 'frigate')
  expect(link().getAttribute('href')).toBe('/')
})

it('draws once, however often it is loaded', () => {
  start(window, 'frigate'); start(window, 'frigate')
  expect(document.querySelectorAll('#tm-home-button').length).toBe(1)
})

it('draws nothing inside an embedded page', () => {
  const framed = Object.create(window, { top: { value: {} }, self: { value: window } })
  start(framed, 'frigate')
  expect(document.getElementById('tm-home-button')).toBeNull()
})

it('shows the hostname and names the tab once the device answers', async () => {
  fakeApi({ 'GET /api/v1/system/device': DEVICE })
  document.title = 'Frigate'
  start(window, 'frigate'); await flushPromises()
  expect(link().textContent).toContain('tm-01')
  expect(link().getAttribute('aria-label')).toBe('Traffic Monitor home, tm-01')
  expect(document.title).toBe('tm-01 · Frigate')
})

it('keeps the name on the tab when the app changes its title', async () => {
  fakeApi({ 'GET /api/v1/system/device': DEVICE })
  start(window, 'frigate'); await flushPromises()
  document.title = 'Review - Frigate'; await flushPromises()
  expect(document.title).toBe('tm-01 · Review - Frigate')
})

it.each([['a 401', apiError(401, 'unauthenticated', 'Log in to continue.')], ['no hostname', { theme: THEME }],
         ['a hostname that is not text', { hostname: 5 }]])('is the icon alone after %s', async (_, answer) => {
  fakeApi({ 'GET /api/v1/system/device': answer })
  document.title = 'Frigate'
  start(window, 'frigate'); await flushPromises()
  expect(link().getAttribute('href')).toBe('/')
  expect(link().getAttribute('aria-label')).toBe('Traffic Monitor home')
  expect(document.title).toBe('Frigate')
})

it('is the icon alone when the device cannot be reached at all', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')))
  start(window, 'frigate'); await flushPromises()
  expect(link().getAttribute('href')).toBe('/')
})

it('goes home on a press, and not after a drag', () => {
  start(window, 'dashboard')
  expect(clickIsLetThrough(() => drag([900, 700], [904, 702]))).toBe(true)     // 4.5 px: a press
  expect(clickIsLetThrough(() => drag([900, 700], [300, 400]))).toBe(false)    // a drag
})

it('remembers where it was dropped, for this app only', () => {
  start(window, 'dashboard')
  drag([900, 700], [300, 400])
  expect(JSON.parse(localStorage.getItem('tm-home-button')!)).toEqual({ dashboard: { side: 'left', y: 0.5, tucked: false } })
})

it('starts where it was left', () => {
  localStorage.setItem('tm-home-button', JSON.stringify({ nr: { side: 'left', y: 0.25, tucked: false } }))
  start(window, 'nr')
  expect(host().style.left).not.toBe('')
  expect(host().style.top).toBe('180px')                                        // 0.25 of 800, less half of 40
})

it('tucks when dropped at the edge, and comes back from its handle', () => {
  start(window, 'dashboard')
  drag([900, 700], [995, 400])
  expect(isHidden(link())).toBe(true)
  expect(isHidden(handle())).toBe(false)
  handle().click()
  expect(isHidden(link())).toBe(false)
  expect(JSON.parse(localStorage.getItem('tm-home-button')!).dashboard.tucked).toBe(false)
})

it('tucks on Escape and moves focus to the handle', () => {
  start(window, 'dashboard')
  link().focus()
  link().dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  expect(isHidden(link())).toBe(true)
  expect(host().shadowRoot!.activeElement).toBe(handle())
})

it('keeps Escape to itself, so the app under it does not also close a dialog', () => {
  start(window, 'dashboard')
  link().focus()
  const seen = vi.fn()
  document.addEventListener('keydown', seen)
  const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, composed: true, cancelable: true })
  link().dispatchEvent(escape)
  document.removeEventListener('keydown', seen)
  expect(isHidden(link())).toBe(true)
  expect(seen).not.toHaveBeenCalled()
  expect(escape.defaultPrevented).toBe(true)
})

it('does not leave Escape alone when the key is another one', () => {
  start(window, 'dashboard')
  const seen = vi.fn()
  document.addEventListener('keydown', seen)
  link().dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, composed: true }))
  document.removeEventListener('keydown', seen)
  expect(seen).toHaveBeenCalledTimes(1)
  expect(isHidden(link())).toBe(false)
})

it('does not start a drag from a hover after a press that ended elsewhere', () => {
  start(window, 'dashboard')
  const top = host().style.top
  pointer('pointerdown', [900, 700], 1)                                         // the pointerup never reaches the link
  pointer('pointermove', [300, 400], 0)                                         // a hover, no button down
  expect(host().style.top).toBe(top)
  expect(host().dataset.side).not.toBe('')
  pointer('pointermove', [300, 400], 1)                                         // and the press is over for good
  expect(host().style.top).toBe(top)
})

it('puts the button back when it loses the pointer in the middle of a drag', () => {
  start(window, 'dashboard')
  const [top, side] = [host().style.top, host().dataset.side]
  pointer('pointerdown', [900, 700], 1)
  pointer('pointermove', [300, 400], 1)
  expect(host().style.top).not.toBe(top)
  pointer('lostpointercapture', [300, 400])
  expect(host().style.top).toBe(top)
  expect(host().dataset.side).toBe(side)
  expect(localStorage.getItem('tm-home-button')).toBeNull()
})

it('lets a later click through when the one after a drag never came', async () => {
  start(window, 'dashboard')
  drag([900, 700], [300, 400])
  await new Promise((resolve) => setTimeout(resolve, 0))
  expect(clickIsLetThrough(() => {})).toBe(true)                                // Enter on the focused link
})

it('swallows only the one click after a drag', () => {
  start(window, 'dashboard')
  drag([900, 700], [300, 400])
  expect(clickIsLetThrough(() => {})).toBe(false)
  expect(clickIsLetThrough(() => {})).toBe(true)
})

it('still works when storage is refused', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
  start(window, 'dashboard')
  expect(() => drag([900, 700], [300, 400])).not.toThrow()
  expect(link().getAttribute('href')).toBe('/')
})

it('hides the hostname on a narrow window', async () => {
  vi.stubGlobal('innerWidth', 390)
  fakeApi({ 'GET /api/v1/system/device': DEVICE })
  start(window, 'frigate'); await flushPromises()
  expect(isHidden(link().querySelector('span')!)).toBe(true)
  expect(link().getAttribute('aria-label')).toBe('Traffic Monitor home, tm-01')
})

// Read through a variable: Vite rewrites `new URL(path, import.meta.url)` into a served asset's address
const here = import.meta.url

it("imports nothing of the control app's", () => {
  for (const file of ['main.ts', 'entry.ts', 'place.ts']) {
    const source = readFileSync(new URL(`../src/home-button/${file}`, here), 'utf8')
    const imports = [...source.matchAll(/from '([^']+)'/g)].map((m) => m[1])
    expect(imports.filter((name) => !['./main', './place', '../colors', '@mdi/js'].includes(name))).toEqual([])
  }
  expect(readFileSync(new URL('../src/colors.ts', here), 'utf8')).not.toMatch(/^import /m)
})
