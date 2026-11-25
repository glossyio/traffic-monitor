// The Mounting page: how the unit is mounted at the place in use, one section per sensor, checked with the API's dry
// run after each change and saved with PUT /surveys/{id}/mounting.
import { flushPromises, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { OFFLINE_MESSAGE } from '../src/api/client'
import type { components } from '../src/api/schema'
import { ADMIN, apiError, json, signedIn, type Sent } from './fake-api'
import { mountApp } from './mount'

type PlacesState = components['schemas']['PlacesState']
type SurveyOut = components['schemas']['SurveyOut']
type MountingState = components['schemas']['MountingState']
type SensorMounting = components['schemas']['SensorMounting']
type MountingOut = components['schemas']['MountingOut']
type MountingIn = components['schemas']['MountingIn']

const IN_USE: SurveyOut = {
  id: 'a1b2c3d4-si',
  description: 'Front of the school',
  lat: 45.0,
  lon: -122.0,
  status: 'in_use',
  source: 'ui',
  created_at: '2026-10-01T12:00:00+00:00',
  updated_at: '2026-10-01T12:00:00+00:00',
  headings: [],
  stored_lat: 45.0,
  stored_lon: -122.0,
  first_used: null,
  last_used: null,
  open_count: 2,
  deployment_count: 2,
  imported: false,
}

const PLACES: PlacesState = {
  precision: '1',
  in_use: IN_USE.id,
  sensors: [
    { sensor_type: 'cameras', sensor_name: 'picam_h265', heading_deg: 40 },
    { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00', heading_deg: 40 },
  ],
  sharing: 'none',
  surveys: [IN_USE],
  unassigned: null,
  reconcile: 'done',
  nodered: true,
  map: { style_url: null },
}

const SURVEYS = 'GET /api/v1/surveys'
const MOUNTING = 'GET /api/v1/surveys/a1b2c3d4-si/mounting'
const SAVE = 'PUT /api/v1/surveys/a1b2c3d4-si/mounting'

const MOUNTS = [
  { key: 'tripod', title: 'Tripod beside the road', height_m: 2.13, pitch_deg: 15 },
  { key: 'pole', title: 'Pole or sign post', height_m: 3.66, pitch_deg: 15 },
  { key: 'window', title: 'Upstairs window over an intersection', height_m: 4.88, pitch_deg: 15 },
]

// A camera on a pole, 12 ft up, tilted 15°, facing NE (40°)
function sensor(changes: Partial<SensorMounting> = {}): SensorMounting {
  return {
    sensor_type: 'cameras',
    sensor_name: 'picam_h265',
    heading_deg: 40,
    pitch_deg: 15,
    height_m: 3.66,
    view_distance_m: 13.66,
    measured: 'pitch',
    mount: 'pole',
    camera: null,
    same_as_camera: false,
    deployment_id: '1790000000000-0a1b2c3d-d',
    recorded: true,
    previous: null,
    ...changes,
  }
}

const CAMERA = sensor()
// Its radar, mounted as the camera is
const RADAR = sensor({
  sensor_type: 'radars',
  sensor_name: 'TM_RADAR_SERIAL_PORT_00',
  camera: 'picam_h265',
  same_as_camera: true,
  deployment_id: '1790000000000-4567cdef-d',
})
// The same radar, turned and lower than the camera
const OWN_RADAR = { ...RADAR, heading_deg: 90, height_m: 2.13, view_distance_m: 7.95, same_as_camera: false }
const AIR = sensor({
  sensor_type: 'airquality_monitors',
  sensor_name: 'sensorname01',
  heading_deg: null,
  pitch_deg: null,
  height_m: null,
  view_distance_m: null,
  measured: null,
  mount: null,
})
// A camera with nothing recorded but its heading
const BARE = sensor({ pitch_deg: null, height_m: null, view_distance_m: null, measured: null, mount: null })

function mounting(sensors: SensorMounting[], changes: Partial<MountingState> = {}): MountingState {
  return { sensors, mounts: MOUNTS, nodered: true, ...changes }
}

// A dry run's or a save's answer
function out(sensors: SensorMounting[], changes: Partial<MountingOut> = {}): MountingOut {
  return {
    saved: false,
    sensors,
    changes: [],
    ask: false,
    suggested: null,
    new_deployments: [],
    reloaded: null,
    ...changes,
  }
}

// Answers PUT with `dry` for a dry run and `save` for a save
type Answer = Response | object | Promise<Response>

function puts(dry: (body: MountingIn) => Answer, save: (body: MountingIn) => Answer = dry) {
  return async (request: Request) => {
    const body = (await request.clone().json()) as MountingIn
    const answer = await (body.dry_run === false ? save(body) : dry(body))
    return answer instanceof Response ? answer : json(200, answer)
  }
}

function refused(field: string, index: number, message: string) {
  return json(422, { error: { code: 'validation', message, detail: { field, index } } })
}

async function open(state: MountingState | Response, answers: Record<string, unknown> = {}) {
  const api = signedIn(ADMIN, { [SURVEYS]: PLACES, [MOUNTING]: state, ...answers })
  const app = await mountApp('/location/mounting')
  return { api, ...app }
}

// The wait after a change, and what it sends
async function pause() {
  await vi.advanceTimersByTimeAsync(400)
  await flushPromises()
}

function dryRuns(sent: Sent[]) {
  return sent.filter((r) => r.method === 'PUT' && (r.body as MountingIn).dry_run !== false)
}

function saves(sent: Sent[]) {
  return sent.filter((r) => r.method === 'PUT' && (r.body as MountingIn).dry_run === false)
}

function section(wrapper: VueWrapper, name: string): DOMWrapper<Element> {
  const found = wrapper.findAll('[data-sensor]').filter((s) => s.attributes('data-sensor') === name)
  expect(found.length, `one section for ${name}`).toBe(1)
  return found[0]
}

// The input inside `root` whose <label for=...> reads `label`
function fieldOf(root: DOMWrapper<Element> | VueWrapper, label: string): DOMWrapper<HTMLInputElement> {
  const ids = new Set(
    root
      .findAll('label')
      .filter((l) => l.text().trim() === label && l.attributes('for'))
      .map((l) => l.attributes('for')),
  )
  expect([...ids].length, `one field labelled "${label}"`).toBe(1)
  return root.find<HTMLInputElement>(`[id="${[...ids][0]}"]`)
}

function hasField(root: DOMWrapper<Element>, label: string) {
  return root.findAll('label').some((l) => l.text().trim() === label)
}

function buttonOf(root: DOMWrapper<Element> | VueWrapper, text: string) {
  const found = root.findAll('button').filter((b) => b.text().trim() === text)
  expect(found.length, `one button reading "${text}"`).toBe(1)
  return found[0]
}

async function type(root: DOMWrapper<Element>, label: string, text: string) {
  await fieldOf(root, label).setValue(text)
  await flushPromises()
}

async function pick(root: DOMWrapper<Element> | VueWrapper, label: string) {
  await fieldOf(root, label).setValue(true)
  await flushPromises()
}

async function press(root: DOMWrapper<Element> | VueWrapper, text: string) {
  await buttonOf(root, text).trigger('click')
  await flushPromises()
}

const HEIGHT = 'Height above the road'
const TILT = 'Tilt below level'
const DISTANCE = 'Distance to the centre of the view'
const HEADING = 'Degrees from north'
const MEASURED_TILT = 'I measured the tilt'
const MEASURED_DISTANCE = 'I measured the distance'
const SAME = 'Same as picam_h265'
const STAYED = 'No, it is where it was. I measured it better.'
const MOVED = 'Yes, it was moved or turned.'

describe('the Mounting page', () => {
  beforeEach(() => {
    document.body.replaceChildren()
    localStorage.clear()
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  })
  afterEach(() => vi.useRealTimers())

  it('it lists a section for each sensor, the radar after its camera', async () => {
    const { wrapper } = await open(mounting([CAMERA, OWN_RADAR, AIR]))
    expect(wrapper.find('h1').text()).toBe('Mounting')
    expect(wrapper.text()).toContain('Front of the school')
    expect(wrapper.text()).toContain('a1b2c3d4-si')
    expect(wrapper.text()).toContain(
      'How the unit is mounted at this place. The numbers are stored with each deployment and help place the ' +
        'recorded paths on a street plan.',
    )
    const back = wrapper.find('main').findAll('a').filter((a) => a.text().trim() === 'Location')
    expect(back.map((a) => a.attributes('href'))).toEqual(['/location'])
    expect(wrapper.findAll('[data-sensor]').map((s) => s.attributes('data-sensor'))).toEqual([
      'picam_h265',
      'TM_RADAR_SERIAL_PORT_00',
      'sensorname01',
    ])
    expect(section(wrapper, 'picam_h265').find('h2').text()).toBe('picam_h265')
    expect(section(wrapper, 'TM_RADAR_SERIAL_PORT_00').find('h2').text()).toBe('TM_RADAR_SERIAL_PORT_00')
    expect(section(wrapper, 'picam_h265').text()).toContain('Which way it faces')
    expect(section(wrapper, 'picam_h265').find('svg[aria-label^="Side view"]').exists()).toBe(true)
  })

  it('a place that is not in use shows the reason and no form', async () => {
    const reason = 'Only the place in use has a mounting to read or save. Deploy it first.'
    const { wrapper } = await open(apiError(409, 'not_in_use', reason))
    expect(wrapper.text()).toContain(reason)
    expect(wrapper.findAll('[data-sensor]')).toHaveLength(0)
    expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Save')).toBe(false)

    wrapper.unmount()
    signedIn(ADMIN, { [SURVEYS]: { ...PLACES, in_use: null } })
    const none = await mountApp('/location/mounting')
    expect(none.wrapper.text()).toContain('No place is in use.')
    expect(none.wrapper.findAll('[data-sensor]')).toHaveLength(0)
  })

  it('feet are shown by default, and metres after the switch, which is remembered', async () => {
    const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]))
    const camera = section(wrapper, 'picam_h265')
    expect(fieldOf(camera, HEIGHT).element.value).toBe('12.0')
    expect(camera.text()).toContain('12.0 ft (3.66 m)')
    await pick(wrapper, 'Metres')
    expect(fieldOf(section(wrapper, 'picam_h265'), HEIGHT).element.value).toBe('3.66')
    expect(section(wrapper, 'picam_h265').text()).toContain('3.66 m (12.0 ft)')
    expect(localStorage.getItem('tm.mounting.unit')).toBe('m')
    await pause()
    expect(dryRuns(api.sent)).toHaveLength(0) // the values didn't change, only how they're shown

    wrapper.unmount()
    const again = await open(mounting([CAMERA, OWN_RADAR]))
    expect(fieldOf(section(again.wrapper, 'picam_h265'), HEIGHT).element.value).toBe('3.66')
  })

  it('picking a usual mount fills the height and the tilt and sends its key', async () => {
    const { wrapper, api } = await open(mounting([BARE, { ...OWN_RADAR, mount: null }]), {
      [SAVE]: puts(() => out([CAMERA, OWN_RADAR])),
    })
    await pick(wrapper, 'Tripod beside the road')
    const camera = section(wrapper, 'picam_h265')
    expect(fieldOf(camera, HEIGHT).element.value).toBe('7.0')
    expect(fieldOf(camera, TILT).element.value).toBe('15')
    expect(fieldOf(camera, MEASURED_TILT).element.checked).toBe(true)
    await pause()
    const [{ body }] = dryRuns(api.sent)
    const sent = (body as MountingIn).sensors
    expect(sent[0]).toMatchObject({ height_m: 2.13, pitch_deg: 15, measured: 'pitch', mount: 'tripod' })
    expect(sent[1]).toMatchObject({ height_m: 2.13, pitch_deg: 15, measured: 'pitch', mount: 'tripod' })
  })

  it('my own measurements clears the key and keeps the numbers', async () => {
    const { wrapper, api } = await open(mounting([CAMERA, AIR]), { [SAVE]: puts(() => out([CAMERA, AIR])) })
    expect(fieldOf(wrapper, 'Pole or sign post').element.checked).toBe(true)
    await pick(wrapper, 'My own measurements')
    await pause()
    const sent = (dryRuns(api.sent)[0].body as MountingIn).sensors
    expect(sent[0]).toMatchObject({ height_m: 3.66, pitch_deg: 15, measured: 'pitch', mount: null })
  })

  it('a field typed back to what it showed keeps the value it had', async () => {
    const { wrapper, api } = await open(mounting([{ ...CAMERA, height_m: 3.0, view_distance_m: 11.2 }]), {
      [SAVE]: puts(() => out([{ ...CAMERA, height_m: 2.99, view_distance_m: 11.16 }])),
    })
    const camera = () => section(wrapper, 'picam_h265')
    expect(fieldOf(camera(), HEIGHT).element.value).toBe('9.8') // 3.00 m
    await type(camera(), HEIGHT, '9.81')
    await type(camera(), HEIGHT, '9.8')
    await pause()
    expect(dryRuns(api.sent)).toHaveLength(0) // 3.00 m, as loaded, not 9.8 ft's 2.99 m
    expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeDefined()
  })

  it('a length typed after the unit changes under unreadable text is read in the new unit', async () => {
    const { wrapper, api } = await open(mounting([{ ...CAMERA, height_m: 3.0, view_distance_m: 11.2 }]), {
      [SAVE]: puts(() => out([{ ...CAMERA, height_m: 9.8, view_distance_m: 36.57 }])),
    })
    const camera = () => section(wrapper, 'picam_h265')
    expect(fieldOf(camera(), HEIGHT).element.value).toBe('9.8') // 3.00 m
    await type(camera(), HEIGHT, 'abc')
    await pick(wrapper, 'Metres')
    await type(camera(), HEIGHT, '9.8')
    await pause()
    expect(dryRuns(api.sent).map((r) => (r.body as MountingIn).sensors[0].height_m)).toEqual([9.8]) // not 3.00 m
  })

  it('a change sends one dry run after the pause, in metres', async () => {
    const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]), {
      [SAVE]: puts(() => out([CAMERA, OWN_RADAR])),
    })
    await type(section(wrapper, 'picam_h265'), HEIGHT, '12')
    await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
    await vi.advanceTimersByTimeAsync(399)
    expect(dryRuns(api.sent)).toHaveLength(0)
    await pause()
    const runs = dryRuns(api.sent)
    expect(runs).toHaveLength(1)
    expect(runs[0].path).toBe('/api/v1/surveys/a1b2c3d4-si/mounting')
    expect(runs[0].body).toEqual({
      dry_run: true,
      sensors: [
        {
          sensor_type: 'cameras',
          sensor_name: 'picam_h265',
          heading_deg: 40,
          height_m: 3.96,
          pitch_deg: 15,
          view_distance_m: null,
          measured: 'pitch',
          mount: 'pole',
          same_as_camera: false,
        },
        {
          sensor_type: 'radars',
          sensor_name: 'TM_RADAR_SERIAL_PORT_00',
          heading_deg: 90,
          height_m: 2.13,
          pitch_deg: 15,
          view_distance_m: null,
          measured: 'pitch',
          mount: 'pole',
          same_as_camera: false,
        },
      ],
    })
  })

  it('an older answer that arrives late is ignored', async () => {
    let first: (response: Response) => void = () => {}
    let calls = 0
    const { wrapper } = await open(mounting([CAMERA, OWN_RADAR]), {
      [SAVE]: () => {
        calls += 1
        if (calls === 1) return new Promise<Response>((resolve) => (first = resolve))
        return json(200, out([{ ...CAMERA, height_m: 4.88, view_distance_m: 18.21 }, OWN_RADAR]))
      },
    })
    const camera = () => section(wrapper, 'picam_h265')
    await type(camera(), HEIGHT, '13')
    await pause()
    await type(camera(), HEIGHT, '16')
    await pause()
    expect(fieldOf(camera(), DISTANCE).element.value).toBe('59.7')
    first(json(200, out([{ ...CAMERA, height_m: 3.96, view_distance_m: 14.78 }, OWN_RADAR])))
    await flushPromises()
    expect(fieldOf(camera(), DISTANCE).element.value).toBe('59.7')
  })

  it("the value not measured is greyed and shows the dry run's", async () => {
    const { wrapper } = await open(mounting([CAMERA, OWN_RADAR]), {
      [SAVE]: puts(() => out([{ ...CAMERA, height_m: 4.08, view_distance_m: 15.24 }, OWN_RADAR])),
    })
    const camera = () => section(wrapper, 'picam_h265')
    expect(fieldOf(camera(), DISTANCE).attributes('disabled')).toBeDefined()
    expect(fieldOf(camera(), TILT).attributes('disabled')).toBeUndefined()
    await type(camera(), HEIGHT, '13.4')
    await pause()
    expect(fieldOf(camera(), DISTANCE).element.value).toBe('50.0')
    expect(camera().text()).toContain('50.0 ft (15.24 m)')

    await pick(camera(), MEASURED_DISTANCE)
    expect(fieldOf(camera(), TILT).attributes('disabled')).toBeDefined()
    expect(fieldOf(camera(), DISTANCE).attributes('disabled')).toBeUndefined()
    expect(fieldOf(camera(), DISTANCE).element.value).toBe('50.0') // starts from the value it showed
  })

  describe('switching which one is measured', () => {
    // The API keeps the measured one and works the other out only with a height: 12 ft or 16 ft at 15°, both ways
    function worked(body: MountingIn) {
      const [sent] = body.sensors
      const height = sent.height_m ?? null
      const known: Record<string, [number, number]> = { '3.66': [15, 13.66], '4.88': [15, 18.21], '6.1': [15, 22.77] }
      const [tilt, distance] = (height !== null && known[String(height)]) || [null, null]
      const fromDistance = height === null ? null : sent.view_distance_m === distance ? tilt : 19.7
      const fromTilt = height === null ? null : sent.pitch_deg === tilt ? distance : null
      const values =
        sent.measured === 'distance'
          ? { pitch_deg: fromDistance, view_distance_m: sent.view_distance_m }
          : { pitch_deg: sent.pitch_deg, view_distance_m: fromTilt }
      return out([{ ...CAMERA, height_m: height, measured: sent.measured ?? null, ...values }])
    }

    it('a tilt typed with no height is still there after switching to the distance and back', async () => {
      const { wrapper, api } = await open(mounting([BARE]), { [SAVE]: puts(worked) })
      const camera = () => section(wrapper, 'picam_h265')
      await type(camera(), TILT, '15')
      await pause()
      await pick(camera(), MEASURED_DISTANCE)
      await pause()
      expect(fieldOf(camera(), DISTANCE).element.value).toBe('')
      await pick(camera(), MEASURED_TILT)
      await pause()
      expect(fieldOf(camera(), TILT).element.value).toBe('15')
      const [sent] = (dryRuns(api.sent).at(-1)!.body as MountingIn).sensors
      expect(sent).toMatchObject({ pitch_deg: 15, measured: 'pitch' })
    })

    it('a switch made during the pause starts from the answer for the form as typed', async () => {
      const { wrapper, api } = await open(mounting([CAMERA]), { [SAVE]: puts(worked) })
      const camera = () => section(wrapper, 'picam_h265')
      await type(camera(), HEIGHT, '16')
      await pick(camera(), MEASURED_DISTANCE) // inside the 400 ms
      expect(fieldOf(camera(), DISTANCE).element.value).toBe('59.7') // 18.21 m, the new height's distance
      await pause()
      expect((dryRuns(api.sent).at(-1)!.body as MountingIn).sensors[0]).toMatchObject({
        height_m: 4.88,
        view_distance_m: 18.21,
        measured: 'distance',
      })
      expect(fieldOf(camera(), TILT).element.value).toBe('15')
    })

    it('a field typed while the switch waits for an answer starts it from the newest answer', async () => {
      let held: (response: Response) => void = () => {}
      let runs = 0
      const { wrapper, api } = await open(mounting([CAMERA]), {
        [SAVE]: puts((body) => {
          runs += 1
          return runs === 1 ? new Promise<Response>((resolve) => (held = resolve)) : worked(body)
        }),
      })
      const camera = () => section(wrapper, 'picam_h265')
      await type(camera(), HEIGHT, '16')
      await pause() // the dry run for 16 ft is on its way
      await pick(camera(), MEASURED_DISTANCE)
      await type(camera(), HEIGHT, '20')
      held(json(200, worked(dryRuns(api.sent)[0].body as MountingIn)))
      await pause()
      expect(fieldOf(camera(), DISTANCE).element.value).toBe('74.7') // 22.77 m for 20 ft, not 44.8 ft for 12 ft
      await pause()
      expect(fieldOf(camera(), TILT).element.value).toBe('15')
    })

    it('a switch after a dry run that got no answer asks again first', async () => {
      let runs = 0
      const { wrapper } = await open(mounting([CAMERA]), {
        [SAVE]: puts((body) => {
          runs += 1
          if (runs === 1) throw new TypeError('Failed to fetch')
          return worked(body)
        }),
      })
      const camera = () => section(wrapper, 'picam_h265')
      await type(camera(), HEIGHT, '16')
      await pause()
      expect(wrapper.text()).toContain(OFFLINE_MESSAGE)
      await pick(camera(), MEASURED_DISTANCE)
      await pause()
      expect(fieldOf(camera(), DISTANCE).element.value).toBe('59.7') // 18.21 m for 16 ft, not 44.8 ft for 12 ft
      await pause()
      expect(fieldOf(camera(), TILT).element.value).toBe('15')
    })

    it('a usual mount forgets a distance measured before it', async () => {
      const measured = { ...CAMERA, pitch_deg: 14.9, view_distance_m: 13.72, measured: 'distance' as const }
      const { wrapper } = await open(mounting([measured]), {
        [SAVE]: puts(() => out([{ ...CAMERA, height_m: 2.13, pitch_deg: 0, view_distance_m: null, mount: 'tripod' }])),
      })
      const camera = () => section(wrapper, 'picam_h265')
      await pick(wrapper, 'Tripod beside the road')
      await type(camera(), TILT, '0')
      await pause()
      await pick(camera(), MEASURED_DISTANCE)
      expect(fieldOf(camera(), DISTANCE).element.value).toBe('') // not the 45.0 ft from before the mount
    })

    it('a value the API could not work out stays empty when switched to', async () => {
      const { wrapper } = await open(mounting([CAMERA]), {
        [SAVE]: puts(() => out([{ ...CAMERA, pitch_deg: 0, view_distance_m: null }])),
      })
      const camera = () => section(wrapper, 'picam_h265')
      await type(camera(), TILT, '0')
      await pause()
      await pick(camera(), MEASURED_DISTANCE)
      expect(fieldOf(camera(), DISTANCE).element.value).toBe('') // not the 44.8 ft loaded with the old tilt
    })
  })

  it('a tilt of zero shows no distance', async () => {
    const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]), {
      [SAVE]: puts(() => out([{ ...CAMERA, pitch_deg: 0, view_distance_m: null }, OWN_RADAR])),
    })
    await type(section(wrapper, 'picam_h265'), TILT, '0')
    await pause()
    expect((dryRuns(api.sent)[0].body as MountingIn).sensors[0]).toMatchObject({ pitch_deg: 0, measured: 'pitch' })
    expect(fieldOf(section(wrapper, 'picam_h265'), DISTANCE).element.value).toBe('')
  })

  it("a refused field shows the API's sentence under it, and Save is off", async () => {
    const sentence = "height_m isn't a number above 0 and at most 100."
    const { wrapper } = await open(mounting([CAMERA, OWN_RADAR]), {
      [SAVE]: puts(() => refused('height_m', 1, sentence)),
    })
    await type(section(wrapper, 'TM_RADAR_SERIAL_PORT_00'), HEIGHT, '-3')
    await pause()
    const radar = section(wrapper, 'TM_RADAR_SERIAL_PORT_00')
    const messages = fieldOf(radar, HEIGHT).element.closest('.v-input')?.textContent ?? ''
    expect(messages).toContain(sentence)
    expect(section(wrapper, 'picam_h265').text()).not.toContain(sentence)
    expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeDefined()
  })

  it('a comma is read as the decimal mark in a length and in the tilt', async () => {
    const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]), {
      [SAVE]: puts(() => out([CAMERA, OWN_RADAR])),
    })
    await type(section(wrapper, 'picam_h265'), HEIGHT, '7,5')
    await type(section(wrapper, 'picam_h265'), TILT, '12,5')
    await pause()
    expect(section(wrapper, 'picam_h265').text()).not.toContain('Enter a number')
    expect((dryRuns(api.sent)[0].body as MountingIn).sensors[0]).toMatchObject({ height_m: 2.29, pitch_deg: 12.5 })
  })

  it('text that is not a number says so, is not sent, and keeps Save off', async () => {
    const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]), {
      [SAVE]: puts(() => out([CAMERA, OWN_RADAR])),
    })
    await type(section(wrapper, 'picam_h265'), HEIGHT, '1,000')
    await pause()
    expect(section(wrapper, 'picam_h265').text()).toContain('Enter a number, such as 12 or 12.5.')
    expect(dryRuns(api.sent)).toHaveLength(0)
    expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeDefined()

    await type(section(wrapper, 'picam_h265'), HEIGHT, '')
    await pause()
    expect(section(wrapper, 'picam_h265').text()).not.toContain('Enter a number')
    expect((dryRuns(api.sent)[0].body as MountingIn).sensors[0]).toMatchObject({ height_m: null })
  })

  describe('the question', () => {
    const TURNED = { ...CAMERA, heading_deg: 62 }
    const ASKS = out([{ ...TURNED, mount: 'tripod' }, OWN_RADAR], {
      changes: [
        { sensor_type: 'cameras', sensor_name: 'picam_h265', field: 'heading_deg', counts: true },
        { sensor_type: 'cameras', sensor_name: 'picam_h265', field: 'mount', counts: false },
      ],
      ask: true,
      suggested: 'moved',
    })

    async function turned(save: (body: MountingIn) => Response | object = () => ASKS) {
      const opened = await open(mounting([CAMERA, OWN_RADAR]), { [SAVE]: puts(() => ASKS, save) })
      await type(section(opened.wrapper, 'picam_h265'), HEADING, '62')
      await pause()
      return opened
    }

    it('the question shows when the dry run asks, with its answer already chosen', async () => {
      const { wrapper } = await turned()
      expect(wrapper.text()).toContain('Did the unit move or turn?')
      expect(fieldOf(wrapper, MOVED).element.checked).toBe(true)
      expect(fieldOf(wrapper, STAYED).element.checked).toBe(false)
      expect(wrapper.text()).toContain(
        'A new deployment starts now for picam_h265. Traffic already recorded keeps the old values.',
      )
    })

    it('it lists what changed', async () => {
      const { wrapper } = await turned()
      expect(wrapper.text()).toContain('picam_h265: heading 40° to 62°')
      expect(wrapper.text()).not.toContain('picam_h265: usual mount') // it doesn't count, so it isn't asked about
    })

    it('a different turn chooses the suggested answer again', async () => {
      let heading = 62
      const opened = await open(mounting([CAMERA, OWN_RADAR]), {
        [SAVE]: puts((body) => {
          const sent = body.sensors[0]
          heading = sent.heading_deg ?? heading
          const changes = [{ sensor_type: 'cameras', sensor_name: 'picam_h265', field: 'heading_deg', counts: true }]
          if (sent.mount === null) changes.push({ ...changes[0], field: 'mount', counts: false })
          return out([{ ...CAMERA, heading_deg: heading, mount: sent.mount ?? null }, OWN_RADAR], {
            changes,
            ask: true,
            suggested: heading === 62 ? 'measured' : 'moved',
          })
        }),
      })
      const { wrapper } = opened
      await type(section(wrapper, 'picam_h265'), HEADING, '62')
      await pause()
      expect(fieldOf(wrapper, STAYED).element.checked).toBe(true)
      await pick(wrapper, MOVED)
      await pick(wrapper, 'My own measurements') // a change that doesn't count keeps the person's answer
      await pause()
      expect(fieldOf(wrapper, MOVED).element.checked).toBe(true)

      await pick(wrapper, STAYED)
      await type(section(wrapper, 'picam_h265'), HEADING, '130')
      await pause()
      expect(fieldOf(wrapper, MOVED).element.checked).toBe(true) // a new turn: the API's answer again
    })

    it('the other answer can be chosen, and Save sends it', async () => {
      const { wrapper, api } = await turned(() => out([TURNED, OWN_RADAR], { saved: true }))
      await pick(wrapper, STAYED)
      expect(wrapper.text()).toContain('The record of the running deployment is corrected.')
      expect(wrapper.text()).not.toContain('A new deployment starts now')
      await press(wrapper, 'Save')
      const [save] = saves(api.sent)
      expect(save.body).toMatchObject({ dry_run: false, moved: false })
    })

    it('no question is shown when the dry run does not ask', async () => {
      const { wrapper } = await open(mounting([CAMERA, OWN_RADAR]), {
        [SAVE]: puts(() =>
          out([{ ...CAMERA, heading_deg: 62 }, OWN_RADAR], {
            changes: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', field: 'heading_deg', counts: true }],
          }),
        ),
      })
      await type(section(wrapper, 'picam_h265'), HEADING, '62')
      await pause()
      expect(wrapper.text()).not.toContain('Did the unit move or turn?')
      expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeUndefined()
    })
  })

  it('unreadable text in the field that stops being measured no longer holds the form back', async () => {
    const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]), {
      [SAVE]: puts(() => out([{ ...CAMERA, measured: 'distance' }, OWN_RADAR])),
    })
    await type(section(wrapper, 'picam_h265'), TILT, 'abc')
    expect(section(wrapper, 'picam_h265').text()).toContain('Enter a number, such as 12 or 12.5.')
    await pick(section(wrapper, 'picam_h265'), MEASURED_DISTANCE)
    await pause()
    expect(section(wrapper, 'picam_h265').text()).not.toContain('Enter a number')
    const [run] = dryRuns(api.sent)
    expect((run.body as MountingIn).sensors[0]).toMatchObject({ measured: 'distance', pitch_deg: null })
    expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeUndefined()
  })

  describe('saving', () => {
    const HIGHER = { ...CAMERA, height_m: 3.96, view_distance_m: 14.78 }

    it('Save sends nothing while a dry run is waiting or on its way', async () => {
      let answer: (response: Response) => void = () => {}
      const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]), {
        [SAVE]: puts(
          () => new Promise<Response>((resolve) => (answer = resolve)),
          () => out([HIGHER, OWN_RADAR], { saved: true }),
        ),
      })
      await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
      await press(wrapper, 'Save') // waiting for the pause
      await pause()
      expect(dryRuns(api.sent)).toHaveLength(1)
      await press(wrapper, 'Save') // the dry run is on its way
      expect(saves(api.sent)).toHaveLength(0)
      expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeDefined()
      answer(json(200, out([HIGHER, OWN_RADAR])))
      await flushPromises()
      expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeUndefined()
    })

    it('the controls are off while a save is on its way', async () => {
      const previous = { pitch_deg: 15, height_m: 3.66, view_distance_m: 13.66, measured: 'pitch' as const, mount: 'pole' }
      let answer: (response: Response) => void = () => {}
      const { wrapper } = await open(mounting([{ ...BARE, previous }, { ...RADAR, same_as_camera: false }]), {
        [SAVE]: puts(
          () => out([CAMERA, RADAR]),
          () => new Promise<Response>((resolve) => (answer = resolve)),
        ),
      })
      await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
      await pause()
      await press(wrapper, 'Save')
      for (const label of ['Metres', 'Tripod beside the road', 'My own measurements']) {
        expect(fieldOf(wrapper, label).attributes('disabled'), label).toBeDefined()
      }
      expect(fieldOf(section(wrapper, 'TM_RADAR_SERIAL_PORT_00'), SAME).attributes('disabled')).toBeDefined()
      expect(buttonOf(section(wrapper, 'picam_h265'), 'Use these values').attributes('disabled')).toBeDefined()
      answer(json(200, out([CAMERA, RADAR], { saved: true })))
      await flushPromises()
    })

    it('a dry run that gets no answer can be sent again, and Save waits for it', async () => {
      let runs = 0
      const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]), {
        [SAVE]: puts(() => {
          runs += 1
          if (runs === 1) throw new TypeError('Failed to fetch') // the phone dropped off the hotspot
          return out([HIGHER, OWN_RADAR])
        }),
      })
      await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
      await pause()
      expect(wrapper.text()).toContain(OFFLINE_MESSAGE)
      expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeDefined()
      await vi.advanceTimersByTimeAsync(5000)
      expect(dryRuns(api.sent)).toHaveLength(1) // nothing is sent again on its own
      await press(wrapper, 'Try again')
      expect(dryRuns(api.sent)).toHaveLength(2)
      expect(dryRuns(api.sent)[1].body).toEqual(dryRuns(api.sent)[0].body)
      expect(wrapper.text()).not.toContain(OFFLINE_MESSAGE)
      expect(wrapper.findAll('button').some((b) => b.text().trim() === 'Try again')).toBe(false)
      expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeUndefined()
    })

    it('a change after a save clears what the save said', async () => {
      const { wrapper } = await changed(() => out([HIGHER, OWN_RADAR], { saved: true }))
      await press(wrapper, 'Save')
      expect(wrapper.text()).toContain('Saved.')
      await type(section(wrapper, 'picam_h265'), HEIGHT, '14')
      expect(wrapper.text()).not.toContain('Saved.')
    })

    it("a refused save shows the API's sentence once, under its field when it has one", async () => {
      const sentence = "height_m isn't a number above 0 and at most 100."
      const count = (text: string) => text.split(sentence).length - 1
      const first = await changed(() => refused('height_m', 0, sentence))
      await press(first.wrapper, 'Save')
      expect(count(first.wrapper.text())).toBe(1)
      const field = fieldOf(section(first.wrapper, 'picam_h265'), HEIGHT).element.closest('.v-input')
      expect(field?.textContent).toContain(sentence)
      first.wrapper.unmount()

      const other = "mount isn't one of the usual mounts."
      const second = await changed(() => refused('mount', 0, other))
      await press(second.wrapper, 'Save')
      expect(second.wrapper.text().split(other).length - 1).toBe(1)
    })

    async function changed(save: (body: MountingIn) => Response | object) {
      const opened = await open(mounting([CAMERA, OWN_RADAR]), {
        [SAVE]: puts(() => out([HIGHER, OWN_RADAR]), save),
      })
      expect(buttonOf(opened.wrapper, 'Save').attributes('disabled')).toBeDefined() // nothing differs yet
      await type(section(opened.wrapper, 'picam_h265'), HEIGHT, '13')
      await pause()
      return opened
    }

    it('Save sends the form with dry_run false', async () => {
      const { wrapper, api } = await changed(() => out([HIGHER, OWN_RADAR], { saved: true }))
      await press(wrapper, 'Save')
      const dry = dryRuns(api.sent)[0].body as MountingIn
      const [save] = saves(api.sent)
      expect(save.body).toEqual({ ...dry, dry_run: false })
      expect(wrapper.text()).toContain('Saved.')
      expect(api.sent.filter((r) => r.method === 'GET' && r.path.endsWith('/mounting'))).toHaveLength(2)
    })

    it('the result says which sensors started a new deployment', async () => {
      const { wrapper } = await changed(() =>
        out([HIGHER, OWN_RADAR], {
          saved: true,
          reloaded: true,
          new_deployments: [
            { sensor_type: 'cameras', sensor_name: 'picam_h265' },
            { sensor_type: 'radars', sensor_name: 'TM_RADAR_SERIAL_PORT_00' },
          ],
        }),
      )
      await press(wrapper, 'Save')
      expect(wrapper.text()).toContain(
        'Saved. A new deployment started for picam_h265 and TM_RADAR_SERIAL_PORT_00.',
      )
    })

    it('a slow Node-RED says not to save again', async () => {
      const { wrapper } = await changed(() =>
        out([HIGHER, OWN_RADAR], {
          saved: true,
          reloaded: false,
          new_deployments: [{ sensor_type: 'cameras', sensor_name: 'picam_h265' }],
        }),
      )
      await press(wrapper, 'Save')
      expect(wrapper.text()).toContain(
        "Saved. Node-RED hasn't loaded the settings yet; the new deployment appears once it does. Don't save again.",
      )
    })

    it('answer_needed from a save shows the question', async () => {
      const message = 'Say whether the unit moved or turned, or was measured better, and save again.'
      let runs = 0
      const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]), {
        [SAVE]: puts(
          () => {
            runs += 1
            return runs === 1
              ? out([HIGHER, OWN_RADAR])
              : out([HIGHER, OWN_RADAR], {
                  changes: [{ sensor_type: 'cameras', sensor_name: 'picam_h265', field: 'height_m', counts: true }],
                  ask: true,
                  suggested: 'measured',
                })
          },
          () => apiError(409, 'answer_needed', message),
        ),
      })
      await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
      await pause()
      expect(wrapper.text()).not.toContain('Did the unit move or turn?')
      await press(wrapper, 'Save')
      expect(wrapper.text()).toContain(message)
      await flushPromises()
      expect(wrapper.text()).toContain('Did the unit move or turn?')
      expect(fieldOf(wrapper, STAYED).element.checked).toBe(true)
      expect(wrapper.text()).toContain('picam_h265: height 12.0 ft (3.66 m) to 13.0 ft (3.96 m)')
      expect(dryRuns(api.sent)).toHaveLength(2)
    })

    it('Use these values fills the section and Save sends them', async () => {
      const previous = { pitch_deg: 15, height_m: 3.66, view_distance_m: 13.66, measured: 'pitch' as const, mount: 'pole' }
      const waiting = { ...BARE, previous }
      const { wrapper, api } = await open(mounting([waiting, AIR]), {
        [SAVE]: puts(
          () => out([{ ...CAMERA, previous }, AIR]),
          () => out([CAMERA, AIR], { saved: true }),
        ),
      })
      const camera = () => section(wrapper, 'picam_h265')
      expect(camera().text()).toContain('From last time: 12.0 ft up, tilted 15°, pole or sign post')
      await press(camera(), 'Use these values')
      expect(fieldOf(camera(), HEIGHT).element.value).toBe('12.0')
      expect(fieldOf(camera(), TILT).element.value).toBe('15')
      expect(fieldOf(camera(), MEASURED_TILT).element.checked).toBe(true)
      expect(saves(api.sent)).toHaveLength(0) // nothing is recorded until Save
      await pause()
      expect(wrapper.text()).not.toContain('Did the unit move or turn?')
      await press(wrapper, 'Save')
      expect((saves(api.sent)[0].body as MountingIn).sensors[0]).toMatchObject({
        height_m: 3.66,
        pitch_deg: 15,
        measured: 'pitch',
        mount: 'pole',
      })
    })

    it('last time with only a measured distance offers the distance', async () => {
      const previous = {
        pitch_deg: null,
        height_m: null,
        view_distance_m: 13.66,
        measured: 'distance' as const,
        mount: null,
      }
      const { wrapper } = await open(mounting([{ ...BARE, previous }]))
      expect(section(wrapper, 'picam_h265').text()).toContain('From last time: 44.8 ft to the centre of the view')
    })

    it('the usual mount follows Use these values and the tick', async () => {
      const previous = { pitch_deg: 15, height_m: 3.66, view_distance_m: 13.66, measured: 'pitch' as const }
      const pole = { ...previous, mount: 'pole' }
      const { wrapper } = await open(mounting([{ ...BARE, previous: pole }]), {
        [SAVE]: puts(() => out([CAMERA])),
      })
      await pick(wrapper, 'Tripod beside the road')
      await press(section(wrapper, 'picam_h265'), 'Use these values')
      expect(fieldOf(wrapper, 'Pole or sign post').element.checked).toBe(true)
      expect(fieldOf(wrapper, 'Tripod beside the road').element.checked).toBe(false)
      wrapper.unmount()

      const other = await open(mounting([CAMERA, { ...OWN_RADAR, mount: 'tripod' }]))
      expect(fieldOf(other.wrapper, 'Pole or sign post').element.checked).toBe(false) // the two differ
      await pick(section(other.wrapper, 'TM_RADAR_SERIAL_PORT_00'), SAME)
      expect(fieldOf(other.wrapper, 'Pole or sign post').element.checked).toBe(true) // only the camera's is left
    })

    it('a save that Node-RED does not answer shows the sentence and leaves Save on', async () => {
      const sentence = "Node-RED didn't answer, so nothing was saved. Try again in a minute."
      const { wrapper, api } = await changed(() => apiError(502, 'nodered', sentence))
      await press(wrapper, 'Save')
      expect(wrapper.text()).toContain(sentence)
      expect(api.sent.filter((r) => r.method === 'GET' && r.path.endsWith('/mounting'))).toHaveLength(1)
      expect(fieldOf(section(wrapper, 'picam_h265'), HEIGHT).element.value).toBe('13')
      expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeUndefined()
    })

    it('a save or a dry run refused because config.yml changed loads the page again', async () => {
      const sentence = 'config.yml changed since it was read. Reload the page and try again.'
      const mountingLoads = (sent: Sent[]) => sent.filter((r) => r.method === 'GET' && r.path.endsWith('/mounting'))
      const saved = await changed(() => apiError(409, 'config_changed', sentence))
      await press(saved.wrapper, 'Save')
      expect(mountingLoads(saved.api.sent)).toHaveLength(2)
      expect(saved.wrapper.text()).toContain(sentence)
      expect(fieldOf(section(saved.wrapper, 'picam_h265'), HEIGHT).element.value).toBe('12.0') // the edit is gone
      saved.wrapper.unmount()

      const checked = await open(mounting([CAMERA, OWN_RADAR]), {
        [SAVE]: puts(() => apiError(409, 'config_changed', sentence)),
      })
      await type(section(checked.wrapper, 'picam_h265'), HEIGHT, '13')
      await pause()
      expect(mountingLoads(checked.api.sent)).toHaveLength(2)
      expect(checked.wrapper.text()).toContain(sentence)
      expect(fieldOf(section(checked.wrapper, 'picam_h265'), HEIGHT).element.value).toBe('12.0')
    })

    it('the notice goes once the sensor is saved', async () => {
      const previous = { pitch_deg: 15, height_m: 3.66, view_distance_m: 13.66, measured: 'pitch' as const, mount: 'pole' }
      let gets = 0
      const { wrapper } = await open(mounting([BARE]), {
        [MOUNTING]: () => {
          gets += 1
          return json(200, mounting([gets === 1 ? { ...BARE, previous } : CAMERA]))
        },
        [SAVE]: puts(
          () => out([{ ...CAMERA, previous }]),
          () => out([CAMERA], { saved: true }),
        ),
      })
      expect(wrapper.text()).toContain('From last time')
      await press(section(wrapper, 'picam_h265'), 'Use these values')
      await pause()
      await press(wrapper, 'Save')
      expect(wrapper.text()).not.toContain('From last time')
      expect(wrapper.text()).toContain('Saved.')
    })
  })

  describe('a radar and its camera', () => {
    it('a radar that follows its camera sends same_as_camera and hides its fields', async () => {
      const { wrapper, api } = await open(mounting([CAMERA, RADAR]), {
        [SAVE]: puts(() => out([CAMERA, RADAR])),
      })
      const radar = section(wrapper, 'TM_RADAR_SERIAL_PORT_00')
      expect(radar.text()).toContain("Takes picam_h265's heading, height, and tilt.")
      expect(hasField(radar, HEIGHT)).toBe(false)
      expect(hasField(radar, HEADING)).toBe(false)
      expect(radar.text()).not.toContain('Which way it faces')
      expect(radar.find('svg[aria-label^="Side view"]').exists()).toBe(false)
      await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
      await pause()
      expect((dryRuns(api.sent)[0].body as MountingIn).sensors[1]).toEqual({
        sensor_type: 'radars',
        sensor_name: 'TM_RADAR_SERIAL_PORT_00',
        same_as_camera: true,
      })
    })

    it("unticking shows them with the camera's values", async () => {
      const { wrapper } = await open(mounting([CAMERA, RADAR]), { [SAVE]: puts(() => out([CAMERA, RADAR])) })
      await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
      await fieldOf(section(wrapper, 'TM_RADAR_SERIAL_PORT_00'), SAME).setValue(false)
      await flushPromises()
      const radar = section(wrapper, 'TM_RADAR_SERIAL_PORT_00')
      expect(radar.text()).not.toContain("Takes picam_h265's heading")
      expect(fieldOf(radar, HEIGHT).element.value).toBe('13.0')
      expect(fieldOf(radar, TILT).element.value).toBe('15')
      expect(fieldOf(radar, HEADING).element.value).toBe('40')
    })

    it("a following radar offers its own values from last time when they aren't its camera's", async () => {
      const own = { pitch_deg: 20, height_m: 2.13, view_distance_m: 5.85, measured: 'pitch' as const, mount: null }
      const { wrapper, api } = await open(mounting([CAMERA, { ...RADAR, previous: own }]), {
        [SAVE]: puts(() => out([CAMERA, { ...RADAR, same_as_camera: false, previous: own }])),
      })
      const radar = () => section(wrapper, 'TM_RADAR_SERIAL_PORT_00')
      expect(fieldOf(radar(), SAME).element.checked).toBe(true)
      expect(radar().text()).toContain('From last time: 7.0 ft up, tilted 20°')
      await press(radar(), 'Use these values')
      expect(fieldOf(radar(), SAME).element.checked).toBe(false)
      expect(fieldOf(radar(), HEIGHT).element.value).toBe('7.0')
      expect(fieldOf(radar(), TILT).element.value).toBe('20')
      expect(fieldOf(radar(), HEADING).element.value).toBe('40') // the heading stays its camera's
      await pause()
      expect((dryRuns(api.sent)[0].body as MountingIn).sensors[1]).toMatchObject({
        same_as_camera: false,
        heading_deg: 40,
        height_m: 2.13,
        pitch_deg: 20,
        measured: 'pitch',
        mount: null,
      })
      wrapper.unmount()

      const alike = await open(mounting([{ ...CAMERA, previous: own }, { ...RADAR, previous: own }]))
      expect(section(alike.wrapper, 'picam_h265').text()).toContain('From last time')
      expect(section(alike.wrapper, 'TM_RADAR_SERIAL_PORT_00').text()).not.toContain('From last time')
    })

    it('the tick starts as the API reports same_as_camera', async () => {
      const { wrapper } = await open(mounting([CAMERA, RADAR]))
      expect(fieldOf(section(wrapper, 'TM_RADAR_SERIAL_PORT_00'), SAME).element.checked).toBe(true)
      wrapper.unmount()
      const other = await open(mounting([CAMERA, OWN_RADAR]))
      expect(fieldOf(section(other.wrapper, 'TM_RADAR_SERIAL_PORT_00'), SAME).element.checked).toBe(false)
    })

    it("a radar whose values differ from its camera's starts unticked and is sent as loaded", async () => {
      const { wrapper, api } = await open(mounting([CAMERA, OWN_RADAR]), {
        [SAVE]: puts(() => out([CAMERA, OWN_RADAR])),
      })
      await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
      await pause()
      expect((dryRuns(api.sent)[0].body as MountingIn).sensors[1]).toEqual({
        sensor_type: 'radars',
        sensor_name: 'TM_RADAR_SERIAL_PORT_00',
        heading_deg: 90,
        height_m: 2.13,
        pitch_deg: 15,
        view_distance_m: null,
        measured: 'pitch',
        mount: 'pole',
        same_as_camera: false,
      })
    })
  })

  it('an air-quality monitor has the dial only', async () => {
    const { wrapper, api } = await open(mounting([CAMERA, AIR]), { [SAVE]: puts(() => out([CAMERA, AIR])) })
    const air = section(wrapper, 'sensorname01')
    expect(air.text()).toContain('Which way it faces')
    expect(hasField(air, HEIGHT)).toBe(false)
    expect(hasField(air, TILT)).toBe(false)
    expect(air.text()).not.toContain('I measured')
    await type(air, HEADING, '180')
    await pause()
    expect((dryRuns(api.sent)[0].body as MountingIn).sensors[1]).toEqual({
      sensor_type: 'airquality_monitors',
      sensor_name: 'sensorname01',
      heading_deg: 180,
      same_as_camera: false,
    })
  })

  it('without Node-RED the page warns and Save is off', async () => {
    const { wrapper } = await open(mounting([CAMERA, OWN_RADAR], { nodered: false }), {
      [SAVE]: puts(() => out([{ ...CAMERA, height_m: 3.96 }, OWN_RADAR])),
    })
    expect(wrapper.text()).toContain("Node-RED didn't answer, so changes can't be saved now.")
    await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
    await pause()
    expect(buttonOf(wrapper, 'Save').attributes('disabled')).toBeDefined()
  })

  describe('on the Location page', () => {
    const WAITING_WORDS =
      "This place has mounting values from the last time the unit was here. They aren't recorded until you confirm " +
      'them.'
    const PREVIOUS = { pitch_deg: 15, height_m: 3.66, view_distance_m: 13.66, measured: 'pitch' as const, mount: 'pole' }
    const USED: SurveyOut = { ...IN_USE, id: 'c0ffee01-si', description: 'Corner by the park', status: 'used' }

    it('the deploy result says the last values wait to be confirmed', async () => {
      const { wrapper, router } = await open(mounting([BARE]), {
        [SURVEYS]: { ...PLACES, surveys: [IN_USE, USED] },
        'GET /api/v1/surveys/c0ffee01-si/events': { event_count: 0, first_event: null, last_event: null },
        'GET /api/v1/surveys/c0ffee01-si/deployments': { deployments: [] },
        'POST /api/v1/surveys/c0ffee01-si/deploy': {
          deployed_at: 1762000000000,
          reloaded: true,
          deployments: [],
          previous: [{ sensor_type: 'cameras', sensor_name: 'picam_h265' }],
        },
      })
      await router.push('/location')
      await flushPromises()
      const title = wrapper.findAll('.v-expansion-panel-title').find((t) => t.text().startsWith('Corner by the park'))
      await title!.trigger('click')
      await flushPromises()
      await press(wrapper, 'Re-deploy here')
      const dialog = () => document.querySelector('.v-overlay-container .v-dialog')
      ;[...(dialog()?.querySelectorAll('button') ?? [])].find((b) => b.textContent?.trim() === 'Re-deploy')!.click()
      await flushPromises()
      expect(dialog()?.textContent).toContain(WAITING_WORDS)
      const link = [...(dialog()?.querySelectorAll('a') ?? [])].find((a) => a.textContent?.trim() === 'Mounting')
      expect(link?.getAttribute('href')).toBe('/location/mounting')
    })

    it('the Location page warns while values wait', async () => {
      const { wrapper, router } = await open(mounting([{ ...BARE, previous: PREVIOUS }]))
      await router.push('/location')
      await flushPromises()
      const card = wrapper.find('.v-card')
      expect(card.text()).toContain(WAITING_WORDS)
      const link = card.findAll('a').filter((a) => a.text().trim() === 'Mounting')
      expect(link.map((a) => a.attributes('href'))).toEqual(['/location/mounting'])

      wrapper.unmount()
      const saved = await open(mounting([CAMERA]))
      await saved.router.push('/location')
      await flushPromises()
      expect(saved.wrapper.text()).not.toContain(WAITING_WORDS)
    })
  })

  it('Cancel goes back to Location without saving', async () => {
    const { wrapper, api, router } = await open(mounting([CAMERA, OWN_RADAR]), {
      [SAVE]: puts(() => out([CAMERA, OWN_RADAR])),
    })
    await type(section(wrapper, 'picam_h265'), HEIGHT, '13')
    await pause()
    await press(wrapper, 'Cancel')
    expect(router.currentRoute.value.path).toBe('/location')
    expect(saves(api.sent)).toHaveLength(0)
  })
})
