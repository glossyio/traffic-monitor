// The parade: a strip of road on the About page where one traveler crosses every two seconds and the tally counts it.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import RoadParade from '../src/modules/about/RoadParade.vue'
import { COMMON, PASS_MS, RARE, pickTraveler, tallyText } from '../src/modules/about/parade'
import { mountAlone } from './mount'

const car = () => COMMON[2]

function parade() {
  return mountAlone(RoadParade, { pick: car })
}

async function click(wrapper: ReturnType<typeof parade>) {
  await wrapper.find('button[aria-label="Count some traffic"]').trigger('click')
}

async function advance(ms: number) {
  await vi.advanceTimersByTimeAsync(ms)
  await flushPromises()
}

describe('the parade', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('picks a rare traveler about one time in twelve', () => {
    expect(RARE).toContain(pickTraveler(() => 0.01))
    expect(COMMON).toContain(pickTraveler(() => 0.5))
  })

  it('writes the tally in order and leaves out zeros', () => {
    expect(tallyText({})).toBe('Counted so far: nothing yet')
    expect(tallyText({ duck: 1, walker: 3, bicycle: 2 })).toBe('Counted so far: 3 walking, 2 bicycles, 1 duck')
    expect(tallyText({ bus: 1, car: 1 })).toBe('Counted so far: 1 car, 1 bus')
  })

  it('is closed until the cone is clicked', () => {
    const wrapper = parade()
    expect(wrapper.text()).not.toContain('Counted so far')
    const cone = wrapper.find('button[aria-label="Count some traffic"]')
    expect(cone.attributes('aria-expanded')).toBe('false')
  })

  it('counts a traveler every two seconds once open', async () => {
    const wrapper = parade()
    await click(wrapper)
    expect(wrapper.text()).toContain('Counted so far: nothing yet')
    expect(wrapper.find('.moving').exists()).toBe(true)
    await advance(PASS_MS)
    expect(wrapper.text()).toContain('Counted so far: 1 car')
    expect(wrapper.text()).not.toContain('1 cars')
    await advance(PASS_MS * 2)
    expect(wrapper.text()).toContain('Counted so far: 3 cars')
  })

  it('closes on a second click and stops counting', async () => {
    const wrapper = parade()
    await click(wrapper)
    await click(wrapper)
    expect(wrapper.text()).not.toContain('Counted so far')
    expect(vi.getTimerCount()).toBe(0)
  })

  it('never runs two timers, however fast the cone is clicked', async () => {
    const wrapper = parade()
    await click(wrapper)
    await click(wrapper)
    await click(wrapper)
    expect(wrapper.text()).toContain('Counted so far')
    expect(vi.getTimerCount()).toBe(1)
  })

  it('stops when the page is left', async () => {
    const wrapper = parade()
    await click(wrapper)
    wrapper.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('opens and counts where the browser has no matchMedia', async () => {
    vi.stubGlobal('matchMedia', undefined)
    const wrapper = parade()
    await click(wrapper)
    await advance(PASS_MS)
    expect(wrapper.text()).toContain('Counted so far: 1 car')
  })

  it('moves nothing when the browser asks for reduced motion', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }))
    const wrapper = parade()
    await click(wrapper)
    await advance(PASS_MS)
    expect(wrapper.text()).toContain('Counted so far: 1 car')
    expect(wrapper.find('.moving').exists()).toBe(false)
  })
})
