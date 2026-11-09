// A place's panel: its deployments grouped by the deploy they came from, newest first, each sensor under its deploy.
import { describe, expect, it, beforeEach } from 'vitest'
import type { components } from '../src/api/schema'
import PlaceDetails from '../src/modules/location/PlaceDetails.vue'
import { mountAlone } from './mount'

type DeploymentOut = components['schemas']['DeploymentOut']
type SurveyOut = components['schemas']['SurveyOut']

const FIRST = 1790000000000 // two sensors, deployed together
const SECOND = FIRST + 86400 * 1000 * 3 // two sensors, deployed together, later
const HOUR = 3600 * 1000

const PLACE: SurveyOut = {
  id: 'c0ffee01-si',
  description: 'Corner by the park',
  lat: 45.0,
  lon: -122.0,
  status: 'in_use',
  source: 'ui',
  created_at: '2026-10-01T12:00:00+00:00',
  updated_at: '2026-10-01T12:00:00+00:00',
  bearings: [],
  stored_lat: 45.0,
  stored_lon: -122.0,
  first_used: FIRST,
  last_used: FIRST + HOUR,
  open_count: 2,
  deployment_count: 4,
  imported: false,
}

function row(id: string, started: number | null, ended: number | null, type: string, name: string): DeploymentOut {
  return {
    id,
    started,
    ended,
    lat: 45.0,
    lon: -122.0,
    bearing: 'ne',
    sensor_type: type,
    sensor_name: name,
    location_precision: 1,
  }
}

const dateTime = (ms: number) => new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

function panel(deployments: DeploymentOut[]) {
  return mountAlone(PlaceDetails, {
    place: PLACE,
    nodered: true,
    details: { events: { event_count: 0, first_event: null, last_event: null }, deployments, error: '' },
  })
}

// The API lists them oldest first, the radar before the camera here
const FOUR = [
  row('a-radar', FIRST, FIRST + HOUR, 'radars', 'TM_RADAR_SERIAL_PORT_00'),
  row('a-camera', FIRST, FIRST + HOUR, 'cameras', 'picam_h265'),
  row('b-radar', SECOND, null, 'radars', 'TM_RADAR_SERIAL_PORT_00'),
  row('b-camera', SECOND, null, 'cameras', 'picam_h265'),
]

describe('the deployments in a place panel', () => {
  beforeEach(() => document.body.replaceChildren())

  it('groups the rows that started together, newest deploy first', () => {
    const wrapper = panel(FOUR)
    expect(wrapper.text()).toContain('Deployments (4)')
    const deploys = wrapper.findAll('[data-deploy]')
    expect(deploys).toHaveLength(2)
    expect(deploys[0].find('[data-deploy-title]').text()).toBe(`Deployed ${dateTime(SECOND)}, running now`)
    expect(deploys[1].find('[data-deploy-title]').text()).toContain(`Deployed ${dateTime(FIRST)} to `)
    expect(deploys[0].findAll('[data-deployment]').map((d) => d.attributes('data-deployment'))).toEqual([
      'b-camera',
      'b-radar',
    ])
    expect(deploys[1].findAll('[data-deployment]').map((d) => d.attributes('data-deployment'))).toEqual([
      'a-camera',
      'a-radar',
    ])
  })

  it('treats rows that started within a second as one deploy, as released versions recorded them', () => {
    const deploys = panel([
      row('radar', FIRST, FIRST + HOUR, 'radars', 'TM_RADAR_SERIAL_PORT_00'),
      row('camera', FIRST + 1, FIRST + HOUR, 'cameras', 'picam_h265'),
      row('radar-2', FIRST + 999, FIRST + HOUR, 'radars', 'TM_RADAR_SERIAL_PORT_01'),
    ]).findAll('[data-deploy]')
    expect(deploys).toHaveLength(1)
    expect(deploys[0].findAll('[data-deployment]').map((d) => d.attributes('data-deployment'))).toEqual([
      'camera',
      'radar',
      'radar-2',
    ])
  })

  it('measures that second from the first row of the deploy, so it never chains into the next', () => {
    const deploys = panel([
      row('first', FIRST, null, 'cameras', 'picam_h265'),
      row('near', FIRST + 600, null, 'radars', 'TM_RADAR_SERIAL_PORT_00'),
      row('next', FIRST + 1000, null, 'radars', 'TM_RADAR_SERIAL_PORT_01'),
    ]).findAll('[data-deploy]')
    expect(deploys.map((deploy) => deploy.findAll('[data-deployment]').length)).toEqual([1, 2])
    expect(deploys[0].find('[data-deployment]').attributes('data-deployment')).toBe('next')
  })

  it('marks the running deploy with the primary color, and only that one', () => {
    const [running, ended] = panel(FOUR).findAll('[data-deploy]')
    expect(running.classes()).toContain('border-primary')
    expect(ended.classes()).not.toContain('border-primary')
    expect(ended.classes()).toContain('border-s-md')
  })

  it('indents a radar under the camera deployed with it, but not one deployed alone', () => {
    const [together, alone] = panel([
      row('alone', FIRST, null, 'radars', 'TM_RADAR_SERIAL_PORT_00'),
      row('camera', SECOND, null, 'cameras', 'picam_h265'),
      row('radar', SECOND, null, 'radars', 'TM_RADAR_SERIAL_PORT_00'),
    ]).findAll('[data-deploy]')
    const classes = (id: string, within: typeof together) => within.find(`[data-deployment="${id}"]`).classes()
    expect(classes('camera', together)).not.toContain('ps-4')
    expect(classes('radar', together)).toContain('ps-4')
    expect(classes('alone', alone)).not.toContain('ps-4')
  })

  it('orders a group by sensor type, then name', () => {
    const [group] = panel([
      row('air', FIRST, null, 'airquality_monitors', 'a'),
      row('radar', FIRST, null, 'radars', 'a'),
      row('camera-b', FIRST, null, 'cameras', 'b'),
      row('camera-a', FIRST, null, 'cameras', 'a'),
    ]).findAll('[data-deploy]')
    expect(group.findAll('[data-deployment]').map((d) => d.attributes('data-deployment'))).toEqual([
      'camera-a',
      'camera-b',
      'radar',
      'air',
    ])
  })

  it('gives the latest end in the title, and an end on a row only when it differs', () => {
    const [group] = panel([
      row('camera', FIRST, FIRST + HOUR, 'cameras', 'picam_h265'),
      row('radar', FIRST, FIRST + 2 * HOUR, 'radars', 'TM_RADAR_SERIAL_PORT_00'),
    ]).findAll('[data-deploy]')
    const title = group.find('[data-deploy-title]').text()
    const late = new Date(FIRST + 2 * HOUR).toLocaleTimeString(undefined, { timeStyle: 'short' })
    expect(title.endsWith(late) || title.endsWith(dateTime(FIRST + 2 * HOUR))).toBe(true)
    expect(group.find('[data-deployment="camera"]').text()).toContain(`Ended ${dateTime(FIRST + HOUR)}`)
    expect(group.find('[data-deployment="radar"]').text()).not.toContain('Ended')
  })

  it('names no end in the title while a sensor still runs, and says when the other ended', () => {
    const [group] = panel([
      row('camera', FIRST, FIRST + HOUR, 'cameras', 'picam_h265'),
      row('radar', FIRST, null, 'radars', 'TM_RADAR_SERIAL_PORT_00'),
    ]).findAll('[data-deploy]')
    expect(group.find('[data-deploy-title]').text()).toBe(`Deployed ${dateTime(FIRST)}, running now`)
    expect(group.classes()).toContain('border-primary')
    expect(group.find('[data-deployment="camera"]').text()).toContain(`Ended ${dateTime(FIRST + HOUR)}`)
    expect(group.find('[data-deployment="radar"]').text()).not.toContain('Ended')
  })

  it('puts rows with no start in a group of their own, last', () => {
    const deploys = panel([
      row('unknown', null, FIRST, 'cameras', 'picam_h265'),
      row('known', FIRST, FIRST + HOUR, 'cameras', 'picam_h265'),
    ]).findAll('[data-deploy]')
    expect(deploys).toHaveLength(2)
    expect(deploys[1].find('[data-deploy-title]').text()).toBe('Unknown start')
    expect(deploys[1].find('[data-deployment="unknown"]').text()).toContain(`Ended ${dateTime(FIRST)}`)
  })

  it('asks for a bearing correction for the row chosen', async () => {
    const wrapper = panel(FOUR)
    const row = wrapper.find('[data-deployment="b-radar"]')
    await row.findAll('button').find((b) => b.text() === 'Correct bearing')!.trigger('click')
    expect((wrapper.emitted('correctBearing') as DeploymentOut[][])[0][0].id).toBe('b-radar')
    expect(row.text()).toContain('Facing NE')
  })
})
