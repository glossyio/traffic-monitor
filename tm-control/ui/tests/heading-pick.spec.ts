// The one eight-point pick the Location pages share: choosing a point gives its centre, and a measured heading that
// isn't a centre is shown and kept until another is chosen, and stays choosable after one is.
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import HeadingPick from '../src/modules/location/HeadingPick.vue'
import { mountAlone } from './mount'

async function pick(wrapper: ReturnType<typeof mountAlone>, value: number | null) {
  await wrapper.findComponent({ name: 'VSelect' }).setValue(value)
  await flushPromises()
}

function choices(wrapper: ReturnType<typeof mountAlone>) {
  return wrapper.findComponent({ name: 'VSelect' }).props('items') as { value: number | null; title: string }[]
}

function emitted(wrapper: ReturnType<typeof mountAlone>) {
  return (wrapper.emitted('update:modelValue') ?? []).map((args) => args[0])
}

describe('the heading pick', () => {
  beforeEach(() => document.body.replaceChildren())

  it('gives the centre of a chosen point', async () => {
    const wrapper = mountAlone(HeadingPick, { modelValue: null, label: 'Facing, picam_h265' })
    await pick(wrapper, 135)
    expect(emitted(wrapper)).toEqual([135])
  })

  it('gives null for Not set', async () => {
    const wrapper = mountAlone(HeadingPick, { modelValue: 90, label: 'Facing, picam_h265' })
    await pick(wrapper, null)
    expect(emitted(wrapper)).toEqual([null])
  })

  it('shows what it has, a point or Not set', () => {
    expect(mountAlone(HeadingPick, { modelValue: 45, label: 'Facing' }).text()).toContain('NE')
    expect(mountAlone(HeadingPick, { modelValue: null, label: 'Facing' }).text()).toContain('Not set')
  })

  it('shows a measured heading and keeps it until another is chosen', async () => {
    const wrapper = mountAlone(HeadingPick, { modelValue: 40, label: 'Facing, picam_h265' })
    expect(wrapper.text()).toContain('NE (40°)')
    expect(emitted(wrapper)).toEqual([]) // opening and showing it sends nothing
    const items = wrapper.findComponent({ name: 'VSelect' }).props('items') as { value: number | null }[]
    expect(items[0].value).toBe(40)
    await pick(wrapper, 45)
    expect(emitted(wrapper)).toEqual([45])
  })

  it('keeps a measured heading choosable after a point is chosen', async () => {
    const wrapper = mountAlone(HeadingPick, { modelValue: 40, label: 'Facing, picam_h265' })
    await pick(wrapper, 0)
    await wrapper.setProps({ modelValue: 0 })
    expect(choices(wrapper)[0]).toEqual({ value: 40, title: 'NE (40°)' })
    await pick(wrapper, 40)
    expect(emitted(wrapper)).toEqual([0, 40])
  })

  it('remembers only the last measured heading it was given', async () => {
    const wrapper = mountAlone(HeadingPick, { modelValue: 40, label: 'Facing, picam_h265' })
    await wrapper.setProps({ modelValue: 100 })
    await wrapper.setProps({ modelValue: 90 })
    expect(choices(wrapper).map((choice) => choice.value)).toEqual([100, 0, 45, 90, 135, 180, 225, 270, 315, null])
  })

  it('names itself for a screen reader when it has no visible label', () => {
    const wrapper = mountAlone(HeadingPick, { modelValue: null, ariaLabel: 'Heading to deploy picam_h265 with' })
    expect(wrapper.find('input').attributes('aria-label')).toBe('Heading to deploy picam_h265 with')
  })
})
