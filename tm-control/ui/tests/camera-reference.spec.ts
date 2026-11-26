// The reference picture's rules on the Cameras page: which rows offer it, the pictures' addresses, and the legend.
// Pure functions of the API's answers.
import { describe, expect, it } from 'vitest'
import { canTake, legendRows, peopleLine, pictureUrl } from '../src/modules/cameras/reference'
import { cameraRow, newRow, referenceOut, zoneFacts } from './fake-api'

describe('canTake', () => {
  it('offers a picture of an entry whose camera is on in Frigate', () => {
    expect(canTake(cameraRow())).toBe(true)
  })

  it.each([
    ['a new Frigate camera', newRow()],
    ['an entry whose camera is off', cameraRow({ in_frigate: 'off' })],
    ['an entry whose camera is gone', cameraRow({ in_frigate: 'absent' })],
    ['an entry while Frigate is unknown', cameraRow({ in_frigate: 'unknown' })],
    ['a duplicate entry', cameraRow({ name: 'camera_2_9d41e0', duplicate_of: 'camera_1_3fa9c2' })],
  ])('offers none for %s', (_, row) => {
    expect(canTake(row)).toBe(false)
  })
})

describe('pictureUrl', () => {
  it('addresses a held picture by the camera key and the ticket', () => {
    expect(pictureUrl('oak ave', 'tk', 'clean.jpg')).toBe('/api/v1/cameras/oak%20ave/reference/tk/clean.jpg')
    expect(pictureUrl('camera_1_3fa9c2', 'a/b', 'zones.jpg')).toBe(
      '/api/v1/cameras/camera_1_3fa9c2/reference/a%2Fb/zones.jpg',
    )
  })
})

describe('legendRows', () => {
  it("lists every zone with its colour and what the drawing shows of it", () => {
    expect(legendRows(referenceOut())).toEqual([
      { key: 'zone_radar', color: '#40a05c', detail: 'A–B 12 m, B–C 7.3 m, C–D 12 m, D–A 7.3 m' },
      { key: 'zone_capture', color: '#7035b0', detail: '' },
      { key: 'zone_far', color: '#be8f28', detail: 'off in Frigate, not drawn' },
      { key: 'zone_lane_bus', color: '#888888', detail: 'no outline' },
    ])
  })

  it('writes the lengths in feet when Frigate uses imperial units', () => {
    expect(legendRows(referenceOut({ unit: 'ft', zones: [zoneFacts()] }))[0].detail).toBe(
      'A–B 12 ft, B–C 7.3 ft, C–D 12 ft, D–A 7.3 ft',
    )
  })

  it('says a zone that is off is off, even with side lengths', () => {
    const off = zoneFacts({ enabled: false, drawn: false })
    expect(legendRows(referenceOut({ zones: [off] }))[0].detail).toBe('off in Frigate, not drawn')
  })
})

describe('peopleLine', () => {
  it('warns when Frigate was tracking a person', () => {
    expect(peopleLine('seen')).toEqual({
      type: 'warning',
      text:
        'Frigate was tracking a person on this camera when the pictures were taken. Wait until nobody is in view, ' +
        'then take them again.',
    })
  })

  it("informs when Frigate wasn't tracking a person, and when the device couldn't check", () => {
    expect(peopleLine('none')).toEqual({
      type: 'info',
      text:
        "Frigate wasn't tracking a person when the pictures were taken. It can miss people, so look at both " +
        'pictures yourself.',
    })
    expect(peopleLine('unchecked')).toEqual({
      type: 'info',
      text:
        "The device couldn't check for people, because Frigate's detection is off for this camera or Frigate " +
        "didn't answer. Look at both pictures yourself.",
    })
  })
})
