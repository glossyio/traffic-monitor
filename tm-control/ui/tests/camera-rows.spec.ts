// What a camera's row says and the radar choices: pure functions of the API's rows.
import { describe, expect, it } from 'vitest'
import { pointChoices, radarChoices, rowState, zonesText } from '../src/modules/cameras/rows'
import { RADARS, cameraRow, newRow, type RadarOut } from './fake-api'

describe('rowState', () => {
  it('says in step for an entry whose Frigate camera is on', () => {
    expect(rowState(cameraRow())).toBe('in-step')
  })

  it('says off for an entry whose Frigate camera is switched off there', () => {
    expect(rowState(cameraRow({ in_frigate: 'off' }))).toBe('off')
  })

  it('says new for a Frigate camera no entry points at, on or off', () => {
    const unpointed = { name: null, neutral: null, enabled: null, zones_missing: [] }
    expect(rowState(cameraRow({ ...unpointed, in_frigate: 'on' }))).toBe('new')
    expect(rowState(cameraRow({ ...unpointed, in_frigate: 'off' }))).toBe('new')
  })

  it('says gone for an entry whose Frigate camera is absent', () => {
    expect(rowState(cameraRow({ in_frigate: 'absent', zones_missing: null }))).toBe('gone')
  })

  it('says duplicate for a second entry naming the same Frigate camera', () => {
    expect(rowState(cameraRow({ name: 'camera_2_aa00bb', duplicate_of: 'camera_1_3fa9c2' }))).toBe('duplicate')
  })

  it("says unknown while Frigate can't be compared", () => {
    expect(rowState(cameraRow({ in_frigate: 'unknown', zones_missing: null }))).toBe('unknown')
  })
})

describe('zonesText', () => {
  it('says all four when none is missing', () => {
    expect(zonesText(cameraRow())).toBe('Zones: all four')
  })

  it('lists the zones Frigate lacks', () => {
    expect(zonesText(cameraRow({ zones_missing: ['zone_near', 'zone_far'] }))).toBe(
      'Missing in Frigate: zone_near, zone_far',
    )
  })

  it("says nothing for a camera that isn't in Frigate", () => {
    expect(zonesText(cameraRow({ in_frigate: 'absent', zones_missing: null }))).toBe('')
  })
})

describe('radarChoices', () => {
  it('starts with No radar, then the radars in order', () => {
    const titles = radarChoices(cameraRow(), RADARS).map((choice) => choice.title)
    expect(titles).toEqual(['No radar', 'TM_RADAR_SERIAL_PORT_00', 'TM_RADAR_SERIAL_PORT_01'])
    expect(radarChoices(cameraRow(), RADARS)[0].value).toBeNull()
  })

  it("marks a radar that's off in config.yml and one whose port is closed, and leaves both choosable", () => {
    const radars: RadarOut[] = [
      { name: 'R0', in_config: true, enabled: false, port_open: true },
      { name: 'R1', in_config: true, enabled: true, port_open: false },
      { name: 'R2', in_config: true, enabled: true, port_open: null },
    ]
    const [, off, closed, fine] = radarChoices(cameraRow(), radars)
    expect(off).toMatchObject({ value: 'R0', subtitle: 'off in config.yml' })
    expect(off.disabled).toBeFalsy()
    expect(closed).toMatchObject({ value: 'R1', subtitle: 'port closed' })
    expect(closed.disabled).toBeFalsy()
    expect(fine.subtitle).toBeUndefined()
  })

  it('joins both marks for a radar that is off and has no open port', () => {
    const radars: RadarOut[] = [{ name: 'R0', in_config: true, enabled: false, port_open: false }]
    expect(radarChoices(cameraRow(), radars)[1].subtitle).toBe('off in config.yml, port closed')
  })

  it("can't choose a radar that config.yml doesn't set up", () => {
    const radars: RadarOut[] = [{ name: 'R0', in_config: false, enabled: false, port_open: null }]
    expect(radarChoices(cameraRow(), radars)[1]).toMatchObject({
      value: 'R0',
      subtitle: 'not set up in config.yml',
      disabled: true,
    })
  })

  it('adds the current radar as missing when it is none of the unit radars', () => {
    const choices = radarChoices(cameraRow({ camera_radar: 'TM_RADAR_SERIAL_PORT_07' }), RADARS)
    expect(choices.at(-1)).toMatchObject({
      title: 'TM_RADAR_SERIAL_PORT_07 (missing)',
      value: 'TM_RADAR_SERIAL_PORT_07',
    })
    expect(choices).toHaveLength(RADARS.length + 2)
  })

  it('adds nothing for a current radar that is listed', () => {
    const choices = radarChoices(cameraRow({ camera_radar: 'TM_RADAR_SERIAL_PORT_00' }), RADARS)
    expect(choices).toHaveLength(RADARS.length + 1)
  })
})

describe('pointChoices', () => {
  const gone = cameraRow({ in_frigate: 'absent', zones_missing: null })
  const wide = cameraRow({ name: 'camera_2_aa00bb', frigate_camera: 'oak_ave_wide' })
  const duplicate = cameraRow({ name: 'camera_3_bb11cc', duplicate_of: 'camera_2_aa00bb', in_frigate: 'absent' })
  const fresh = newRow()

  it('offers a new row each entry whose Frigate camera is gone', () => {
    expect(pointChoices(fresh, [wide, gone, fresh])).toEqual([gone])
  })

  it('offers both entries to each of two new rows', () => {
    const second = cameraRow({ name: 'camera_4_cc22dd', frigate_camera: 'main_st', in_frigate: 'absent' })
    const other = newRow('oak_ave_new')
    expect(pointChoices(fresh, [gone, second, fresh, other])).toEqual([gone, second])
    expect(pointChoices(other, [gone, second, fresh, other])).toEqual([gone, second])
  })

  it("offers nothing for an entry's own row", () => {
    expect(pointChoices(wide, [gone, wide])).toEqual([])
  })

  it("offers an entry that repeats another when its Frigate camera is gone, as the API allows", () => {
    expect(pointChoices(fresh, [duplicate, fresh])).toEqual([duplicate])
  })
})
