// Mount the whole app at a path, as a browser would open it, and find things in it by their visible text.
import { flushPromises, mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { expect } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import App from '../src/App.vue'
import { createAppRouter } from '../src/router'
import { createAppVuetify } from '../src/theme'

export async function mountApp(path: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  const wrapper = mount(App, {
    global: { plugins: [pinia, router, createAppVuetify(undefined)] },
    attachTo: document.body,
  })
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
