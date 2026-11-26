// The side view on the Mounting page: the road, the support with the unit on it, the line of sight down to the centre
// of the view, and the three values beside their parts. It draws what it is given and works nothing out.
import { describe, expect, it } from 'vitest'
import type { VueWrapper } from '@vue/test-utils'
import MountSideView from '../src/modules/location/MountSideView.vue'
import { mountAlone } from './mount'

type Props = { heightM: number | null; pitchDeg: number | null; distanceM: number | null; unit: 'ft' | 'm' }

function view(props: Partial<Props>) {
  return mountAlone(MountSideView, { heightM: 2.13, pitchDeg: 15, distanceM: 7.95, unit: 'ft', ...props })
}

function labels(wrapper: VueWrapper): string[] {
  return wrapper.findAll('svg text').map((t) => t.text())
}

function sight(wrapper: VueWrapper) {
  const line = wrapper.find('[data-sight]')
  expect(line.exists(), 'a line of sight').toBe(true)
  const [x1, y1, x2, y2] = ['x1', 'y1', 'x2', 'y2'].map((a) => Number(line.attributes(a)))
  return { x1, y1, x2, y2, dashed: line.attributes('stroke-dasharray') !== undefined }
}

// Every number the drawing puts on a shape or a label, with the viewBox it must stay inside
function insideTheDrawing(wrapper: VueWrapper) {
  const svg = wrapper.find('svg')
  const [, , width, height] = svg.attributes('viewBox')!.split(' ').map(Number)
  const x = ['x', 'x1', 'x2', 'cx']
  const y = ['y', 'y1', 'y2', 'cy']
  for (const element of svg.findAll('line, rect, circle, text')) {
    for (const name of x) {
      const value = element.attributes(name)
      if (value !== undefined) expect(Number(value), `${element.element.tagName} ${name}`).toBeGreaterThanOrEqual(0)
      if (value !== undefined) expect(Number(value), `${element.element.tagName} ${name}`).toBeLessThanOrEqual(width)
    }
    for (const name of y) {
      const value = element.attributes(name)
      if (value !== undefined) expect(Number(value), `${element.element.tagName} ${name}`).toBeGreaterThanOrEqual(0)
      if (value !== undefined) expect(Number(value), `${element.element.tagName} ${name}`).toBeLessThanOrEqual(height)
    }
  }
}

describe('the side view', () => {
  it('the labels follow the values and the unit', async () => {
    const wrapper = view({})
    expect(labels(wrapper)).toEqual(['7.0 ft', '15°', '26.1 ft'])
    await wrapper.setProps({ unit: 'm' })
    expect(labels(wrapper)).toEqual(['2.13 m', '15°', '7.95 m'])
    await wrapper.setProps({ heightM: 3.66, pitchDeg: 14.9, distanceM: 13.72 })
    expect(labels(wrapper)).toEqual(['3.66 m', '14.9°', '13.72 m'])
  })

  it('a tilt of zero draws a level line and labels no distance', () => {
    const wrapper = view({ pitchDeg: 0, distanceM: null })
    const line = sight(wrapper)
    expect(line.y1).toBe(line.y2)
    expect(line.x2).toBeGreaterThan(line.x1)
    expect(labels(wrapper)).toEqual(['7.0 ft', '0°'])
    insideTheDrawing(wrapper)
  })

  it('a tilt of 90 draws straight down', () => {
    const wrapper = view({ pitchDeg: 90, distanceM: 0 })
    const line = sight(wrapper)
    expect(line.x1).toBe(line.x2)
    expect(line.y2).toBeGreaterThan(line.y1)
    expect(labels(wrapper)).toEqual(['7.0 ft', '90°', '0.0 ft'])
    insideTheDrawing(wrapper)
  })

  it('no height shows the one line', () => {
    const wrapper = view({ heightM: null })
    expect(wrapper.text()).toBe('Enter the height to see the side view.')
    expect(wrapper.find('svg').exists()).toBe(false)
    expect(view({ heightM: 0 }).text()).toBe('Enter the height to see the side view.')
  })

  it('a height of 100 m and one of 0.5 m both stay inside the drawing', async () => {
    const tall = view({ heightM: 100, pitchDeg: 45, distanceM: 100, unit: 'm' })
    insideTheDrawing(tall)
    expect(labels(tall)).toEqual(['100.00 m', '45°', '100.00 m'])
    const low = view({ heightM: 0.5, pitchDeg: 15, distanceM: 1.87, unit: 'm' })
    insideTheDrawing(low)
    const far = view({ heightM: 0.5, pitchDeg: 0.1, distanceM: 286, unit: 'ft' })
    insideTheDrawing(far)
    const tallAndNear = view({ heightM: 100, pitchDeg: 90, distanceM: 0, unit: 'ft' })
    insideTheDrawing(tallAndNear)
  })

  it('a missing tilt or distance is dashed and unlabelled', () => {
    const noTilt = view({ pitchDeg: null })
    expect(labels(noTilt)).toEqual(['7.0 ft', '26.1 ft'])
    expect(sight(noTilt).dashed).toBe(true)
    const noDistance = view({ distanceM: null })
    expect(labels(noDistance)).toEqual(['7.0 ft', '15°'])
    const neither = view({ pitchDeg: null, distanceM: null })
    expect(labels(neither)).toEqual(['7.0 ft'])
    expect(sight(neither).dashed).toBe(true)
    insideTheDrawing(neither)
    expect(sight(view({})).dashed).toBe(false)
  })

  it('draws only a height, and a line of sight to the distance when the tilt is missing', () => {
    const wrapper = view({ pitchDeg: null })
    const line = sight(wrapper)
    expect(line.x2).toBeGreaterThan(line.x1)
    expect(line.y2).toBeGreaterThan(line.y1)
  })

  it('a tilt above zero with no distance draws a solid line at that tilt to the edge', () => {
    const wrapper = view({ pitchDeg: 15, distanceM: null })
    const line = sight(wrapper)
    expect(line.dashed).toBe(false)
    expect(line.x2).toBe(284)
    expect((line.y2 - line.y1) / (line.x2 - line.x1)).toBeCloseTo(Math.tan((15 * Math.PI) / 180), 6)
    expect(labels(wrapper)).toEqual(['7.0 ft', '15°'])
    insideTheDrawing(wrapper)
  })

  it('a steep tilt with no distance ends on the road, and a tilt of 90 goes straight down', () => {
    const steep = sight(view({ pitchDeg: 80, distanceM: null }))
    expect(steep.y2).toBeCloseTo(130, 6)
    expect(steep.x2).toBeGreaterThan(steep.x1)
    expect(steep.x2).toBeLessThan(284)
    const down = sight(view({ pitchDeg: 90, distanceM: null }))
    expect(down.x2).toBe(down.x1)
    expect(down.y2).toBe(130)
    expect(down.dashed).toBe(false)
  })

  it('the text alternative names the three values', async () => {
    const wrapper = view({})
    const alternative = wrapper.find('svg').attributes('aria-label')!
    expect(wrapper.find('svg').attributes('role')).toBe('img')
    expect(alternative).toContain('7.0 ft')
    expect(alternative).toContain('15°')
    expect(alternative).toContain('26.1 ft')
    await wrapper.setProps({ unit: 'm', pitchDeg: null, distanceM: null })
    const missing = wrapper.find('svg').attributes('aria-label')!
    expect(missing).toContain('2.13 m')
    expect(missing).not.toContain('°')
    expect(missing).toMatch(/tilt.*not set/i)
    expect(missing).toMatch(/distance.*not set/i)
  })
})
