// A place's panel: its deployments grouped by the deploy they came from, newest first, each sensor under its deploy.
import { describe, expect, it, beforeEach } from 'vitest'
import type { components } from '../src/api/schema'
import PlaceDetails from '../src/modules/location/PlaceDetails.vue'
import { pictureOut } from './fake-api'
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
  headings: [],
  timezone: null,
  stored_lat: 45.0,
  stored_lon: -122.0,
  first_used: FIRST,
  last_used: FIRST + HOUR,
  open_count: 2,
  deployment_count: 4,
  imported: false,
  pictures: 0,
}

function row(id: string, started: number | null, ended: number | null, type: string, name: string): DeploymentOut {
  return {
    id,
    started,
    ended,
    lat: 45.0,
    lon: -122.0,
    heading_deg: 45,
    pitch_deg: null,
    height_m: null,
    view_distance_m: null,
    mount: null,
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
    clockTimeZone: null,
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
  beforeEach(() => {
    document.body.replaceChildren()
    localStorage.clear()
  })

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

  it('asks for a heading correction for the row chosen', async () => {
    const wrapper = panel(FOUR)
    const row = wrapper.find('[data-deployment="a-radar"]')
    await row.findAll('button').find((b) => b.text() === 'Correct heading')!.trigger('click')
    expect((wrapper.emitted('correctHeading') as DeploymentOut[][])[0][0].id).toBe('a-radar')
    expect(row.text()).toContain('Facing NE (45°)')
  })

  it('offers Correct heading on an ended deployment, and Mounting on a running one at the place in use', () => {
    const wrapper = panel(FOUR)
    const actions = (id: string) =>
      wrapper
        .find(`[data-deployment="${id}"]`)
        .findAll('a, button')
        .map((b) => b.text().trim())
    expect(actions('a-camera')).toEqual(['Correct heading'])
    expect(actions('b-camera')).toEqual(['Mounting'])
    const link = wrapper.find('[data-deployment="b-camera"] a')
    expect(link.attributes('href')).toBe('/location/mounting')
  })

  it('keeps Correct heading on a running deployment whose sensor has no section on the Mounting page', () => {
    const wrapper = mountAlone(PlaceDetails, {
      place: PLACE,
      nodered: true,
      clockTimeZone: null,
      details: { events: { event_count: 0, first_event: null, last_event: null }, deployments: FOUR, error: '' },
      mountingSensors: [{ sensor_type: 'cameras', sensor_name: 'picam_h265' }], // the radar was disabled since
    })
    const actions = (id: string) =>
      wrapper
        .find(`[data-deployment="${id}"]`)
        .findAll('a, button')
        .map((b) => b.text().trim())
    expect(actions('b-camera')).toEqual(['Mounting'])
    expect(actions('b-radar')).toEqual(['Correct heading'])
  })

  it('says what is recorded for each deployment, in the unit the browser remembers', () => {
    const mounted = {
      ...row('mounted', FIRST, null, 'cameras', 'picam_h265'),
      heading_deg: 40,
      height_m: 2.13,
      pitch_deg: 15,
    }
    expect(panel([mounted]).find('[data-deployment="mounted"]').text()).toContain(
      'Facing NE (40°) · 7.0 ft up · tilted 15°',
    )
    localStorage.setItem('tm.mounting.unit', 'm')
    expect(panel([mounted]).find('[data-deployment="mounted"]').text()).toContain(
      'Facing NE (40°) · 2.13 m up · tilted 15°',
    )
    const bare = panel([{ ...mounted, heading_deg: null, height_m: null, pitch_deg: null }])
    expect(bare.find('[data-deployment="mounted"]').text()).toContain('No heading set')
    expect(bare.find('[data-deployment="mounted"]').text()).not.toContain('·')
  })

  it('says No heading set for a deployment with none, and shows a measured heading as it is', () => {
    const wrapper = panel([
      { ...row('none', FIRST, null, 'radars', 'TM_RADAR_SERIAL_PORT_00'), heading_deg: null },
      { ...row('measured', FIRST, null, 'cameras', 'picam_h265'), heading_deg: 40 },
      { ...row('north', FIRST, null, 'cameras', 'other'), heading_deg: 0 },
    ])
    expect(wrapper.find('[data-deployment="none"]').text()).toContain('No heading set')
    expect(wrapper.find('[data-deployment="measured"]').text()).toContain('Facing NE (40°)')
    expect(wrapper.find('[data-deployment="north"]').text()).toContain('Facing N (0°)')
    expect(wrapper.text()).not.toMatch(/bearing/i)
  })
})

// The place's time zone: a fact beside First used and Last used, and two lines that only the place in use gets
describe("a place's time zone on its panel", () => {
  beforeEach(() => document.body.replaceChildren())

  const CLOCK = 'America/New_York'
  const NO_TIME_ZONE = 'This place has no time zone. Set one so its data can be read in local time.'

  function mountFacts(changes: Partial<SurveyOut>, props: Record<string, unknown> = {}) {
    return mountAlone(PlaceDetails, {
      place: { ...PLACE, ...changes },
      nodered: true,
      clockTimeZone: CLOCK,
      details: undefined,
      ...props,
    })
  }

  function fact(wrapper: ReturnType<typeof mountFacts>, label: string) {
    return wrapper
      .findAll('.v-row > div')
      .find((col) => col.find('.text-secondary').text() === label)
      ?.find('.text-body-1')
      .text()
  }

  it('shows the time zone', () => {
    const wrapper = mountFacts({ timezone: 'Asia/Tokyo' })
    expect(fact(wrapper, 'Time zone')).toBe('Asia/Tokyo')
    expect(fact(wrapper, 'First used')).toBeDefined() // in the same row
  })

  it('gives the time zone the full width on a phone, and keeps First used and Last used side by side', () => {
    const wrapper = mountFacts({ timezone: 'America/Argentina/Buenos_Aires' })
    const col = (label: string) =>
      wrapper.findAll('.v-row > div').find((c) => c.find('.text-secondary').text() === label)!
    expect(col('Time zone').classes()).toContain('v-col-12')
    expect(col('Time zone').classes()).toContain('v-col-sm-4')
    expect(col('Time zone').classes()).not.toContain('v-col-6')
    expect(col('First used').classes()).toContain('v-col-6')
    expect(col('Last used').classes()).toContain('v-col-6')
  })

  it('shows Not set', () => {
    expect(fact(mountFacts({ timezone: null }), 'Time zone')).toBe('Not set')
  })

  it("shows the time zone when Node-RED didn't answer", () => {
    const wrapper = mountFacts({ timezone: 'Asia/Tokyo' }, { nodered: false })
    expect(fact(wrapper, 'Time zone')).toBe('Asia/Tokyo')
    expect(fact(wrapper, 'First used')).toBeUndefined()
  })

  it('shows it in a row of its own when nothing is counted', () => {
    const wrapper = mountFacts({ timezone: 'Asia/Tokyo', deployment_count: 0 })
    expect(wrapper.text()).toContain('Not used yet.')
    expect(fact(wrapper, 'Time zone')).toBe('Asia/Tokyo')
  })

  it('shows it for a used place too', () => {
    expect(fact(mountFacts({ status: 'used', timezone: 'Asia/Tokyo' }), 'Time zone')).toBe('Asia/Tokyo')
  })

  it('a planned place shows no time zone', () => {
    const wrapper = mountFacts({ status: 'planned', timezone: 'Asia/Tokyo', deployment_count: 0 })
    expect(wrapper.text()).not.toContain('Time zone')
    expect(wrapper.text()).not.toContain('Asia/Tokyo')
  })

  it('the place in use with no time zone is asked for one', () => {
    expect(mountFacts({ timezone: null }).text()).toContain(NO_TIME_ZONE)
  })

  it("a place that isn't in use is not", () => {
    const wrapper = mountFacts({ status: 'used', timezone: null })
    expect(wrapper.text()).not.toContain(NO_TIME_ZONE)
  })

  it("says when the clock's time zone differs, with a link to Date and time", () => {
    const wrapper = mountFacts({ timezone: 'Asia/Tokyo' })
    expect(wrapper.text()).toContain("The unit's clock is set to America/New_York. Change it on Date and time.")
    const link = wrapper.find('a[href="/time"]')
    expect(link.text()).toBe('Date and time')
    expect(link.classes()).toContain('text-primary')
    expect(wrapper.text()).not.toContain(NO_TIME_ZONE)
  })

  it("says that only for the place in use", () => {
    const wrapper = mountFacts({ status: 'used', timezone: 'Asia/Tokyo' })
    expect(wrapper.text()).not.toContain("The unit's clock is set to")
    expect(wrapper.find('a[href="/time"]').exists()).toBe(false)
  })

  it('says nothing when they are the same', () => {
    const wrapper = mountFacts({ timezone: CLOCK })
    expect(wrapper.text()).not.toContain("The unit's clock is set to")
    expect(wrapper.text()).not.toContain(NO_TIME_ZONE)
  })

  it("says nothing when the clock's time zone is unknown", () => {
    const wrapper = mountFacts({ timezone: 'Asia/Tokyo' }, { clockTimeZone: null })
    expect(wrapper.text()).not.toContain("The unit's clock is set to")
    expect(wrapper.text()).not.toContain(NO_TIME_ZONE)
  })
})

describe('the reference pictures in a place panel', () => {
  beforeEach(() => document.body.replaceChildren())

  const mountPictures = (props: Record<string, unknown>) =>
    mountAlone(PlaceDetails, { place: PLACE, nodered: true, clockTimeZone: null, details: undefined, ...props })

  it('counts them in the heading and lists them', () => {
    const wrapper = mountPictures({ pictures: [pictureOut(), pictureOut({ id: 'fedcba9876543210' })] })
    expect(wrapper.find('[data-pictures]').text()).toBe('Reference pictures (2)')
    expect(wrapper.findAll('[data-picture]')).toHaveLength(2)
  })

  it("counts the place's own number until its list is loaded", () => {
    const wrapper = mountPictures({ place: { ...PLACE, pictures: 4 } })
    expect(wrapper.find('[data-pictures]').text()).toBe('Reference pictures (4)')
  })

  it('says none is stored for a place with none, with no Node-RED answer', () => {
    const wrapper = mountPictures({ nodered: false, pictures: [] })
    expect(wrapper.find('[data-pictures]').text()).toBe('Reference pictures (0)')
    expect(wrapper.text()).toContain('No reference picture is stored for this place.')
  })

  it('passes the page the changes and the retry', async () => {
    const wrapper = mountPictures({ pictures: undefined, picturesError: 'Nope.' })
    await wrapper.findAll('button').find((b) => b.text() === 'Try again')!.trigger('click')
    expect(wrapper.emitted('retryPictures')).toHaveLength(1)
  })
})
