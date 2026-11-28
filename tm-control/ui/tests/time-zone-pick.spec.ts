// The one time zone control the Location page's forms share: the unit's clock's time zone by default, and a list
// behind one box for a place in another time zone.
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import TimeZonePick from '../src/modules/location/TimeZonePick.vue'
import { mountAlone } from './mount'

const LIST = ['America/New_York', 'Asia/Tokyo', 'Europe/Berlin']
const HINT = "Recorded with this place's data, also when no location is stored."

function mountPick(props: Record<string, unknown> = {}) {
  return mountAlone(TimeZonePick, {
    modelValue: 'America/New_York',
    timeZones: LIST,
    clockTimeZone: 'America/New_York',
    ...props,
  })
}

function emitted(wrapper: ReturnType<typeof mountPick>) {
  return (wrapper.emitted('update:modelValue') ?? []).map((args) => args[0])
}

function box(wrapper: ReturnType<typeof mountPick>) {
  return wrapper.find<HTMLInputElement>('input[type="checkbox"]')
}

function list(wrapper: ReturnType<typeof mountPick>) {
  return wrapper.findComponent({ name: 'VAutocomplete' })
}

describe('the time zone control', () => {
  beforeEach(() => document.body.replaceChildren())

  it("shows the clock's time zone with the box unticked", () => {
    const wrapper = mountPick()
    expect(wrapper.text()).toContain("America/New_York, the same as the unit's clock")
    expect(wrapper.text()).toContain('This place is in a different time zone')
    expect(box(wrapper).element.checked).toBe(false)
  })

  it('hides the list until the box is ticked', () => {
    expect(list(mountPick()).exists()).toBe(false)
  })

  it('ticking shows the list at the same time zone', async () => {
    const wrapper = mountPick()
    await box(wrapper).setValue(true)
    expect(list(wrapper).exists()).toBe(true)
    expect(list(wrapper).props('modelValue')).toBe('America/New_York')
    expect(list(wrapper).props('items')).toEqual(LIST)
    expect(emitted(wrapper)).toEqual([]) // ticking changes nothing
  })

  it('emits the picked time zone', async () => {
    const wrapper = mountPick()
    await box(wrapper).setValue(true)
    await list(wrapper).setValue('Asia/Tokyo')
    await flushPromises()
    expect(emitted(wrapper)).toEqual(['Asia/Tokyo'])
  })

  it("unticking emits the clock's time zone", async () => {
    const wrapper = mountPick({ modelValue: 'Asia/Tokyo' })
    expect(box(wrapper).element.checked).toBe(true)
    await box(wrapper).setValue(false)
    expect(emitted(wrapper)).toEqual(['America/New_York'])
    await wrapper.setProps({ modelValue: 'America/New_York' })
    expect(list(wrapper).exists()).toBe(false)
    expect(wrapper.text()).toContain("America/New_York, the same as the unit's clock")
  })

  it("starts ticked when the value differs from the clock's", () => {
    const wrapper = mountPick({ modelValue: 'Europe/Berlin' })
    expect(box(wrapper).element.checked).toBe(true)
    expect(list(wrapper).props('modelValue')).toBe('Europe/Berlin')
    expect(wrapper.text()).not.toContain("the same as the unit's clock")
  })

  it("shows the list with no box when the clock's time zone is unknown", () => {
    const wrapper = mountPick({ modelValue: null, clockTimeZone: null })
    expect(box(wrapper).exists()).toBe(false)
    expect(wrapper.text()).not.toContain("the same as the unit's clock")
    expect(list(wrapper).exists()).toBe(true)
  })

  it('shows the hint', async () => {
    const wrapper = mountPick()
    expect(wrapper.text()).toContain(HINT)
    await box(wrapper).setValue(true)
    expect(wrapper.text()).toContain(HINT)
  })

  it('has no clear button', async () => {
    const wrapper = mountPick({ modelValue: 'Asia/Tokyo' })
    expect(list(wrapper).props('clearable')).toBeFalsy()
    expect(wrapper.find('.v-field__clearable').exists()).toBe(false)
  })

  it('keeps the name when its text is emptied', async () => {
    const wrapper = mountPick({ modelValue: 'Asia/Tokyo' })
    const input = list(wrapper).find<HTMLInputElement>('input')
    await input.trigger('focus')
    await input.setValue('')
    await flushPromises()
    expect(emitted(wrapper)).toEqual([]) // never null, never an empty name
    await input.trigger('blur')
    await flushPromises()
    expect(list(wrapper).props('modelValue')).toBe('Asia/Tokyo')
    // Unfocused, a list shows its choice as a selection, not as the input's text
    expect(wrapper.find('.v-autocomplete__selection').text()).toBe('Asia/Tokyo')
  })

  it("shows an error and disables the list when it didn't load", async () => {
    const wrapper = mountPick({ timeZones: [], error: 'The list is unavailable.', modelValue: 'Asia/Tokyo' })
    expect(list(wrapper).props('disabled')).toBe(true)
    expect(wrapper.text()).toContain('The list is unavailable.')
    expect(wrapper.text()).not.toContain(HINT)
  })

  it('leaves the box working when the list did not load', async () => {
    const wrapper = mountPick({ timeZones: [], error: 'The list is unavailable.' })
    expect(box(wrapper).element.disabled).toBe(false)
    expect(wrapper.text()).toContain(HINT)
    expect(list(wrapper).exists()).toBe(false)
  })

  it('disables the box and the list while disabled', () => {
    const wrapper = mountPick({ modelValue: 'Asia/Tokyo', disabled: true })
    expect(box(wrapper).element.disabled).toBe(true)
    expect(list(wrapper).props('disabled')).toBe(true)
  })
})
