// Mount the whole app at a path, as a browser would open it, and find things in it by their visible text.
import { flushPromises, mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, expect } from 'vitest'
import type { Component } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import App from '../src/App.vue'
import { createAppRouter } from '../src/router'
import { createAppVuetify } from '../src/theme'

// Every app or component a test mounted. After each test of a file that imports this module, the ones still mounted
// are unmounted, so a page's timers and listeners (the Status page's polling) don't run on into the next test.
const mounted: VueWrapper[] = []
afterEach(() => {
  for (const wrapper of mounted.splice(0)) if (wrapper.exists()) wrapper.unmount()
})

export async function mountApp(path: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(App, {
    global: { plugins: [pinia, router, createAppVuetify(undefined)] },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  await flushPromises()
  return { wrapper, router }
}

// The input whose <label for=...> reads `label`. (An outlined Vuetify field adds a second, floating label without for.)
export function field(wrapper: VueWrapper, label: string): DOMWrapper<HTMLInputElement> {
  const labels = wrapper.findAll('label').filter((l) => l.text().trim() === label && l.attributes('for'))
  const ids = new Set(labels.map((l) => l.attributes('for')))
  expect([...ids].length, `one field labelled "${label}"`).toBe(1)
  return wrapper.find<HTMLInputElement>(`#${[...ids][0]}`)
}

export function button(wrapper: VueWrapper, text: string) {
  const buttons = wrapper.findAll('button').filter((b) => b.text().trim() === text)
  expect(buttons.length, `one button reading "${text}"`).toBe(1)
  return buttons[0]
}

export async function click(wrapper: VueWrapper, text: string) {
  await button(wrapper, text).trigger('click')
  await flushPromises()
}

// Vuetify moves an open dialog to the end of <body>, outside the wrapper, so its buttons are found there
export function dialogButtons(text: string): HTMLButtonElement[] {
  return [...document.querySelectorAll<HTMLButtonElement>('.v-overlay-container .v-dialog button')].filter(
    (b) => b.textContent?.trim() === text,
  )
}

export async function clickInDialog(text: string) {
  const buttons = dialogButtons(text)
  expect(buttons.length, `one dialog button reading "${text}"`).toBe(1)
  buttons[0].click()
  await flushPromises()
}

// The open dialog's text, or '' when none is open
export function dialogText(): string {
  return document.querySelector('.v-overlay-container .v-dialog')?.textContent ?? ''
}

// One component on its own, with Vuetify and a router (for its links)
export function mountAlone(component: Component, props: Record<string, unknown>): VueWrapper {
  const routes = [{ path: '/:any(.*)*', component: { render: () => null } }]
  const router = createRouter({ history: createMemoryHistory(), routes })
  const wrapper = mount(component, {
    props,
    global: { plugins: [router, createAppVuetify(undefined)] },
    attachTo: document.body,
  })
  mounted.push(wrapper)
  return wrapper
}
