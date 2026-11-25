// The heading dial on the Mounting page: a ring to tap or drag, the eight compass points as buttons, a number field,
// and Not set. It is a plain input: it emits update:heading and sends nothing to the API.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import HeadingDial from '../src/modules/location/HeadingDial.vue'
import { buttonsIn, field, mountAlone, typeInto } from './mount'

const ORDER = ['NW', 'N', 'NE', 'W', 'E', 'SW', 'S', 'SE']
const NAMES = [
  'NW, north-west, 315°',
  'N, north, 0°',
  'NE, north-east, 45°',
  'W, west, 270°',
  'E, east, 90°',
  'SW, south-west, 225°',
  'S, south, 180°',
  'SE, south-east, 135°',
]

function dial(props: Record<string, unknown>) {
  return mountAlone(HeadingDial, { label: 'Heading', ...props })
}

// As a page binds it with v-model: each heading sent comes back as the prop
function bound(heading: number | null): VueWrapper {
  const wrapper: VueWrapper = dial({
    heading,
    'onUpdate:heading': (value: number | null) => wrapper.setProps({ heading: value }),
  })
  return wrapper
}

async function leave(input: HTMLInputElement) {
  input.focus()
  input.blur()
  await flushPromises()
}

function emitted(wrapper: VueWrapper) {
  return (wrapper.emitted('update:heading') ?? []).map((args) => args[0])
}

function point(wrapper: VueWrapper, text: string) {
  const buttons = buttonsIn(wrapper.element, text)
  expect(buttons.length, `one button reading "${text}"`).toBe(1)
  return buttons[0]
}

function degrees(wrapper: VueWrapper) {
  return field(wrapper, 'Degrees from north')
}

// The ring sits at (10, 20) on the page, 200 px square, so its centre is (110, 120)
function ring(wrapper: VueWrapper): SVGSVGElement {
  const svg = wrapper.find('svg[aria-hidden="true"]').element as SVGSVGElement
  svg.getBoundingClientRect = () =>
    ({ left: 10, top: 20, right: 210, bottom: 220, width: 200, height: 200, x: 10, y: 20 }) as DOMRect
  return svg
}

async function pointer(target: Element, type: string, clientX: number, clientY: number) {
  const Event = typeof PointerEvent === 'function' ? PointerEvent : MouseEvent
  const init: PointerEventInit = { bubbles: true, clientX, clientY, button: 0, pointerId: 1 }
  target.dispatchEvent(new Event(type, init))
  await flushPromises()
}

describe('the heading dial', () => {
  beforeEach(() => document.body.replaceChildren())

  it('choosing a compass point sets its centre', async () => {
    const wrapper = dial({ heading: 52 })
    point(wrapper, 'SE').click()
    await flushPromises()
    expect(emitted(wrapper)).toEqual([135])
    expect(degrees(wrapper).element.value).toBe('135')
    point(wrapper, 'N').click()
    await flushPromises()
    expect(emitted(wrapper)).toEqual([135, 0])
  })

  it('typing a number sets the heading', async () => {
    const wrapper = dial({ heading: null })
    await typeInto(degrees(wrapper).element, '52')
    await typeInto(degrees(wrapper).element, '0')
    await typeInto(degrees(wrapper).element, ' 359 ')
    expect(emitted(wrapper)).toEqual([52, 0, 359])
    expect(wrapper.text()).not.toContain('Enter a whole number')
  })

  it('a number outside 0 to 359 is not sent, and the field says why', async () => {
    const wrapper = dial({ heading: 52 })
    for (const text of ['400', '360', '52.5', '-1', 'ne']) {
      await typeInto(degrees(wrapper).element, text)
      expect(wrapper.text(), text).toContain('Enter a whole number from 0 to 359.')
    }
    expect(emitted(wrapper)).toEqual([])
    expect(wrapper.text()).toContain('52°, north-east.') // the heading stays as it was
    await typeInto(degrees(wrapper).element, '60')
    expect(emitted(wrapper)).toEqual([60])
    expect(wrapper.text()).not.toContain('Enter a whole number')
    await typeInto(degrees(wrapper).element, '999')
    point(wrapper, 'W').click() // a point puts its heading in the field, and the message goes
    await flushPromises()
    expect(degrees(wrapper).element.value).toBe('270')
    expect(wrapper.text()).not.toContain('Enter a whole number')
  })

  it('typed one key at a time, each whole number on the way is sent, and leaving the field shows the heading', async () => {
    const wrapper = bound(52)
    const input = degrees(wrapper).element
    input.focus()
    for (const text of ['4', '40', '400']) await typeInto(input, text)
    expect(emitted(wrapper)).toEqual([4, 40]) // the needle follows the typing; the third key is refused
    expect(input.value).toBe('400')
    expect(wrapper.text()).toContain('Enter a whole number from 0 to 359.')
    expect(wrapper.text()).toContain('40°, north-east.')
    const live = () => wrapper.find('.d-sr-only[aria-live="polite"]').text()
    expect(live()).toBe('') // nothing is said while typing
    await leave(input)
    expect(input.value).toBe('40')
    expect(live()).toBe('40°, north-east.') // but leaving the field says the heading
    expect(wrapper.text()).not.toContain('Enter a whole number')
  })

  it('leaving the field puts it back in step with the heading', async () => {
    const wrapper = bound(52)
    const input = degrees(wrapper).element
    await typeInto(input, '')
    await leave(input)
    expect(input.value).toBe('52') // an empty box isn't Not set, so it doesn't stay empty
    await typeInto(input, '999')
    await leave(input)
    expect(input.value).toBe('52')
    expect(wrapper.text()).not.toContain('Enter a whole number')
    await typeInto(input, '05')
    await leave(input)
    expect(emitted(wrapper)).toEqual([5])
    expect(input.value).toBe('5')
    point(wrapper, 'Not set').click()
    await flushPromises()
    await leave(input)
    expect(input.value).toBe('')
  })

  it('an empty field sends nothing', async () => {
    const wrapper = dial({ heading: 52 })
    await typeInto(degrees(wrapper).element, '')
    await typeInto(degrees(wrapper).element, '   ')
    expect(emitted(wrapper)).toEqual([])
    expect(wrapper.text()).not.toContain('Enter a whole number')
    expect(wrapper.text()).toContain('52°, north-east.')
    expect(wrapper.find('[data-needle]').exists()).toBe(true)
  })

  it('a click on the dial sets the heading there', async () => {
    const wrapper = dial({ heading: 52 })
    const svg = ring(wrapper)
    expect(svg.style.touchAction).toBe('none') // a drag on the ring doesn't scroll the page
    svg.setPointerCapture = vi.fn()
    await pointer(svg, 'pointerdown', 210, 120) // straight right of the centre
    expect(svg.setPointerCapture).toHaveBeenCalledWith(1) // the drag keeps going off the ring
    await pointer(svg, 'pointerup', 210, 120)
    expect(emitted(wrapper)).toEqual([90])
    await pointer(svg, 'pointerdown', 110, 220) // straight down
    await pointer(svg, 'pointerup', 110, 220)
    expect(emitted(wrapper)).toEqual([90, 180])
    expect(degrees(wrapper).element.value).toBe('180')

    // A drag across the top goes 359, 0, 1 without a jump, and ends at pointerup
    await pointer(svg, 'pointerdown', 108, 30)
    await pointer(svg, 'pointermove', 110, 30)
    await pointer(svg, 'pointermove', 112, 30)
    await pointer(svg, 'pointerup', 112, 30)
    await pointer(svg, 'pointermove', 10, 120)
    expect(emitted(wrapper)).toEqual([90, 180, 359, 0, 1])

    // A drag whose capture is lost (a hidden tab, say) is over: hovering afterwards moves nothing
    await pointer(svg, 'pointerdown', 210, 120)
    await pointer(svg, 'lostpointercapture', 210, 120)
    await pointer(svg, 'pointermove', 110, 220)
    expect(emitted(wrapper)).toEqual([90, 180, 359, 0, 1, 90])

    // A press on the hub, within 12 px of the centre, changes nothing
    await pointer(svg, 'pointerdown', 118, 127)
    await pointer(svg, 'pointerup', 118, 127)
    expect(emitted(wrapper)).toEqual([90, 180, 359, 0, 1, 90])
  })

  it('a drag is announced once, when it ends', async () => {
    const wrapper = bound(52)
    const live = () => wrapper.find('[aria-live="polite"]').text()
    const svg = ring(wrapper)
    await pointer(svg, 'pointerdown', 210, 120)
    await pointer(svg, 'pointermove', 110, 220)
    expect(wrapper.text()).toContain('180°, south.') // the words follow the drag
    expect(live()).toBe('') // but nothing is said at each step
    await pointer(svg, 'pointerup', 110, 220)
    expect(live()).toBe('180°, south.')
  })

  it('the eight points and the number field can be reached and used from the keyboard', async () => {
    const wrapper = dial({ heading: null })
    const buttons = wrapper.findAll('button').map((b) => b.element)
    const points = buttons.filter((b) => ORDER.includes(b.textContent!.trim()))
    expect(points.map((b) => b.textContent!.trim())).toEqual(ORDER) // reading order is Tab order
    expect(points.map((b) => b.getAttribute('aria-label'))).toEqual(NAMES)
    for (const b of points) {
      expect(b.tagName).toBe('BUTTON')
      expect(b.disabled).toBe(false)
      expect(b.getAttribute('tabindex')).not.toBe('-1')
    }
    // The ring is for the pointer only: no Tab stop, hidden from screen readers
    const svg = wrapper.find('svg').element
    expect(svg.getAttribute('aria-hidden')).toBe('true')
    expect(svg.hasAttribute('tabindex')).toBe(false)

    // A point takes the focus and acts on a click, which is what a browser sends for Enter or Space on a native
    // <button>; jsdom has no keyboard activation of its own, so the click stands in for the key
    point(wrapper, 'NE').focus()
    expect(document.activeElement?.textContent?.trim()).toBe('NE')
    point(wrapper, 'NE').click()
    await flushPromises()
    expect(emitted(wrapper)).toEqual([45])

    const input = degrees(wrapper).element
    expect(input.tagName).toBe('INPUT')
    expect(input.getAttribute('inputmode')).toBe('numeric')
    expect(input.getAttribute('aria-describedby')).toContain(
      wrapper.findAll('p').find((p) => p.text().startsWith('North is up on a map.'))!.attributes('id'),
    )
    input.focus()
    expect(document.activeElement).toBe(input)
    await typeInto(input, '200')
    expect(emitted(wrapper)).toEqual([45, 200])

    // The group is named by the label, so a screen reader says whose heading a button sets
    const group = wrapper.find('[role="group"]')
    const labelId = group.attributes('aria-labelledby')!
    expect(wrapper.find(`#${labelId}`).text()).toBe('Heading')
  })

  it('the needle and the words follow the heading', async () => {
    const wrapper = dial({ heading: 90 })
    const needle = () => wrapper.find('[data-needle]')
    const tip = () => [Number(needle().attributes('x2')), Number(needle().attributes('y2'))]
    expect(wrapper.text()).toContain('90°, east.')
    expect(tip()[0]).toBeGreaterThan(100)
    expect(tip()[1]).toBeCloseTo(100, 5)

    await wrapper.setProps({ heading: 180 })
    expect(wrapper.text()).toContain('180°, south.')
    expect(tip()[0]).toBeCloseTo(100, 5)
    expect(tip()[1]).toBeGreaterThan(100)
    expect(degrees(wrapper).element.value).toBe('180')
    expect(wrapper.find('[aria-live="polite"]').text()).toBe('180°, south.')

    // A point is shown pressed only when the heading is its centre
    expect(point(wrapper, 'S').getAttribute('aria-pressed')).toBe('true')
    await wrapper.setProps({ heading: 52 })
    expect(wrapper.text()).toContain('52°, north-east.')
    expect(point(wrapper, 'NE').getAttribute('aria-pressed')).toBe('false')
    expect(ORDER.filter((p) => point(wrapper, p).getAttribute('aria-pressed') === 'true')).toEqual([])

    await wrapper.setProps({ heading: null })
    expect(wrapper.text()).toContain('Not set.')
    expect(needle().exists()).toBe(false)
    expect(degrees(wrapper).element.value).toBe('')
  })

  it('Not set clears it', async () => {
    const wrapper = bound(52)
    expect(point(wrapper, 'Not set').getAttribute('aria-pressed')).toBe('false')
    point(wrapper, 'Not set').click()
    await flushPromises()
    expect(emitted(wrapper)).toEqual([null])
    expect(point(wrapper, 'Not set').getAttribute('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-needle]').exists()).toBe(false)
    expect(degrees(wrapper).element.value).toBe('')
    point(wrapper, 'Not set').click() // already not set: nothing to send
    await flushPromises()
    expect(emitted(wrapper)).toEqual([null])
  })

  it('disabled, nothing can be changed', async () => {
    const wrapper = dial({ heading: 52, disabled: true })
    for (const text of [...ORDER, 'Not set']) expect(point(wrapper, text).disabled, text).toBe(true)
    expect(degrees(wrapper).element.disabled).toBe(true)
    const svg = ring(wrapper)
    expect(svg.style.touchAction).toBe('') // the page scrolls over a disabled dial
    expect(svg.getAttribute('opacity')).toBe('0.38')
    await pointer(svg, 'pointerdown', 210, 120)
    await pointer(svg, 'pointermove', 110, 220)
    await pointer(svg, 'pointerup', 110, 220)
    expect(emitted(wrapper)).toEqual([])
    expect(wrapper.text()).toContain('52°, north-east.')
  })
})
