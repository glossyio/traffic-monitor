// What a camera's row says and the radar choices: pure functions of the API's rows.
import { describe, expect, it } from 'vitest'
import {
  issueBoxes,
  otherZonesText,
  pointChoices,
  radarChoices,
  rowState,
  zoneNote,
  zonesText,
} from '../src/modules/cameras/rows'
import { MADE_UP_ZONE, RADARS, ZONE_NAMES, cameraRow, newRow, type CameraRadar } from './fake-api'

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
    expect(zonesText(cameraRow())).toBe('Recommended zones present: zone_capture, zone_near, zone_far, zone_radar')
  })

  it('lists the zones Frigate lacks', () => {
    expect(zonesText(cameraRow({ zones_missing: ['zone_near', 'zone_far'] }))).toBe(
      'Recommended zones missing in Frigate: zone_near, zone_far',
    )
  })

  it('lists the zones Frigate has turned off, and both kinds together', () => {
    expect(zonesText(cameraRow({ zones_off: ['zone_capture'] }))).toBe(
      'Recommended zones turned off in Frigate: zone_capture',
    )
    expect(zonesText(cameraRow({ zones_missing: ['zone_radar'], zones_off: ['zone_near'] }))).toBe(
      'Recommended zones missing in Frigate: zone_radar; turned off in Frigate: zone_near',
    )
  })

  it("says nothing for a camera that isn't in Frigate", () => {
    expect(zonesText(cameraRow({ in_frigate: 'absent', zones_missing: null, zones_off: null }))).toBe('')
  })
})

describe('radarChoices', () => {
  it('starts with No radar, then the radars in order', () => {
    const titles = radarChoices(cameraRow(), RADARS).map((choice) => choice.title)
    expect(titles).toEqual(['No radar', 'TM_RADAR_SERIAL_PORT_00', 'TM_RADAR_SERIAL_PORT_01'])
    expect(radarChoices(cameraRow(), RADARS)[0].value).toBeNull()
  })

  it("marks a radar that's off in config.yml and one whose port is closed, and leaves both choosable", () => {
    const radars: CameraRadar[] = [
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
    const radars: CameraRadar[] = [{ name: 'R0', in_config: true, enabled: false, port_open: false }]
    expect(radarChoices(cameraRow(), radars)[1].subtitle).toBe('off in config.yml, port closed')
  })

  it("can't choose a radar that config.yml doesn't set up", () => {
    const radars: CameraRadar[] = [{ name: 'R0', in_config: false, enabled: false, port_open: null }]
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

  it("doesn't offer an entry whose Frigate camera is only off: that is a second camera, not a rename", () => {
    const off = cameraRow({ name: 'camera_5_dd33ee', in_frigate: 'off' })
    expect(pointChoices(fresh, [off, fresh])).toEqual([])
  })

  it("offers nothing for an entry's own row", () => {
    expect(pointChoices(wide, [gone, wide])).toEqual([])
  })

  it("offers an entry that repeats another when its Frigate camera is gone, as the API allows", () => {
    expect(pointChoices(fresh, [duplicate, fresh])).toEqual([duplicate])
  })
})

describe('issueBoxes', () => {
  const warn = (code: string) => ({ level: 'warn' as const, code: code as never })

  it("words each issue for this page, in the check's color", () => {
    const cases: [Parameters<typeof issueBoxes>[0], string, string][] = [
      [
        newRow(),
        'error',
        "oak_ave_tele is new in Frigate and isn't recorded. Point an entry at it, or choose Add as new.",
      ],
      [
        cameraRow({
          name: 'camera_2_9d41e0',
          duplicate_of: 'camera_1_3fa9c2',
          issues: [{ level: 'error', code: 'duplicate' }],
        }),
        'error',
        'camera_1_3fa9c2 already records this Frigate camera. This entry is unused: Remove it.',
      ],
      [
        cameraRow({ in_frigate: 'absent', issues: [warn('gone')] }),
        'warning',
        'Frigate no longer has oak_ave_wide. If you renamed it there, choose Point on its new row; ' +
          'if not, Remove this entry.',
      ],
      [
        cameraRow({ in_frigate: 'off', issues: [warn('camera_off')] }),
        'warning',
        'Not recorded: oak_ave_wide is turned off in Frigate. Turn it on in Frigate, or turn Database capture off ' +
          'in Settings.',
      ],
      [
        cameraRow({ enabled: false, issues: [warn('capture_off')] }),
        'warning',
        'Not recorded: Database capture is off. Turn it on in Settings if you want these events.',
      ],
      [
        cameraRow({ detect: false, issues: [warn('detect_off')] }),
        'warning',
        "Not recorded: Frigate's detection is off. Turn it on in Settings.",
      ],
      [
        cameraRow({ camera_radar: 'TM_RADAR_SERIAL_PORT_01', issues: [warn('radar')] }),
        'warning',
        "Radar TM_RADAR_SERIAL_PORT_01 isn't turned on in config.yml, so this camera gets no speed or direction. " +
          'Choose another radar in Settings.',
      ],
    ]
    for (const [row, level, text] of cases) {
      expect(issueBoxes(row)).toEqual([{ level, text }])
    }
  })

  it("links a zones issue to the camera's zones in Frigate, with the direction note when it applies", () => {
    const row = cameraRow({ zones_missing: ['zone_radar'], zones_off: ['zone_near'], issues: [warn('zones')] })
    expect(issueBoxes(row)).toEqual([
      {
        level: 'warning',
        text:
          'Recommended zones missing in Frigate: zone_radar; turned off in Frigate: zone_near. Without zone_near ' +
          'and zone_far, the direction comes only from the radar.',
        link: { href: '/frigate/settings?page=masksAndZones&camera=oak_ave_wide', text: 'Edit its zones in Frigate' },
      },
    ])
    const capture = cameraRow({ frigate_camera: 'oak ave', zones_missing: ['zone_capture'], issues: [warn('zones')] })
    expect(issueBoxes(capture)[0].text).toBe('Recommended zones missing in Frigate: zone_capture.')
    expect(issueBoxes(capture)[0].link?.href).toBe('/frigate/settings?page=masksAndZones&camera=oak%20ave')
  })

  it('gives a row in step no boxes, and each of several issues its own', () => {
    expect(issueBoxes(cameraRow())).toEqual([])
    // a new Frigate camera whose detection is off drops nothing, so the API reports no issue for it
    expect(issueBoxes(newRow('main_st', { detect: false, issues: [] }))).toEqual([])
    const two = cameraRow({ zones_missing: ['zone_far'], issues: [warn('detect_off'), warn('zones')] })
    expect(issueBoxes(two).map((box) => box.level)).toEqual(['warning', 'warning'])
  })
})

describe('otherZonesText', () => {
  it('is empty without other zones', () => {
    expect(otherZonesText(cameraRow())).toBe('')
    expect(otherZonesText(cameraRow({ zone_names: null }))).toBe('')
  })

  it('lists every other zone', () => {
    expect(otherZonesText(cameraRow({ zone_names: ZONE_NAMES }))).toBe(
      'Other zones enabled: zone_lane_bus, zone_maple, zone_nord, zone_1420_oak_st',
    )
  })

  it("shows Frigate's name beside a key Frigate made up, and no note for it", () => {
    const row = cameraRow({ zone_names: [ZONE_NAMES[0], MADE_UP_ZONE] })
    expect(otherZonesText(row)).toBe(
      'Other zones enabled: zone_lane_bus, zone_a9bacc03 ("Bus lane (north)" in Frigate)',
    )
    expect(zoneNote(row)).toBeNull()
  })
})

describe('zoneNote', () => {
  it('is null when every word is known', () => {
    expect(zoneNote(cameraRow({ zone_names: [ZONE_NAMES[0], ZONE_NAMES[3]] }))).toBeNull()
  })

  it('names the zones with unknown words and links to Frigate', () => {
    const note = zoneNote(cameraRow({ zone_names: ZONE_NAMES }))
    expect(note?.text).toBe(
      "Review the zone names with words the Traffic Monitor doesn't recognize: zone_maple, zone_nord. Like camera " +
        'names, zone names are saved with every event, so a name that points to a street, an address, or a person ' +
        'adds personal information to your de-identified data.',
    )
    expect(note?.link).toEqual({
      href: '/frigate/settings?page=masksAndZones&camera=oak_ave_wide',
      text: 'Edit its zones in Frigate',
    })
  })
})

describe('zoneNote, one name', () => {
  it('speaks of one zone', () => {
    expect(zoneNote(cameraRow({ zone_names: [ZONE_NAMES[1]] }))?.text).toMatch(
      /^Review the zone name with a word the Traffic Monitor doesn't recognize: zone_maple\. /,
    )
  })
})

describe('issueBoxes, zone names', () => {
  it('speaks of several zones', () => {
    const zone_names = [...ZONE_NAMES, { name: 'zone_main_st', check: 'pattern' as const, friendly_name: null }]
    const [box] = issueBoxes(cameraRow({ zone_names, issues: [{ level: 'warn', code: 'zone_names' }] }))
    expect(box.text).toMatch(
      /^Review the zone names that look like an address or a person's name: zone_1420_oak_st, zone_main_st\. /,
    )
    expect(box.text).toContain('so these add personal information')
    expect(box.text).toContain('Rename them in Frigate')
  })

  it('names the zones that look like an address, as a warning with the link', () => {
    const row = cameraRow({ zone_names: ZONE_NAMES, issues: [{ level: 'warn', code: 'zone_names' }] })
    expect(issueBoxes(row)).toEqual([
      {
        level: 'warning',
        text:
          "Review the zone name that looks like an address or a person's name: zone_1420_oak_st. Like camera " +
          'names, zone names are saved with every event, so this one adds personal information to your ' +
          'de-identified data. Rename it in Frigate, for example by compass direction (zone_north).',
        link: { href: '/frigate/settings?page=masksAndZones&camera=oak_ave_wide', text: 'Edit its zones in Frigate' },
      },
    ])
  })
})
