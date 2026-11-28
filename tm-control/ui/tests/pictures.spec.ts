// The words and addresses of a stored reference picture: where its two frames are, why it was taken, what it was
// marked with, and the note on the first picture after a restart.
import { describe, expect, it } from 'vitest'
import { markLine, reasonWords, restartNote, storedUrl } from '../src/modules/location/pictures'
import { pictureOut } from './fake-api'

describe('stored pictures', () => {
  it("addresses each frame on the device by the picture's id", () => {
    expect(storedUrl('0123456789abcdef', 'clean.jpg')).toBe('/api/v1/pictures/0123456789abcdef/clean.jpg')
    expect(storedUrl('0123456789abcdef', 'zones.jpg')).toBe('/api/v1/pictures/0123456789abcdef/zones.jpg')
  })

  it('says why a picture was taken, for each of the six reasons', () => {
    expect(reasonWords('deployed')).toBe('The unit was deployed here')
    expect(reasonWords('opted_in')).toBe('Pictures were turned on for this place')
    expect(reasonWords('mounting')).toBe("The camera's mounting changed")
    expect(reasonWords('setup')).toBe("The camera's setup changed in Frigate")
    expect(reasonWords('daylight')).toBe('Taken again in daylight')
    expect(reasonWords('manual')).toBe('Kept by an administrator')
  })

  it('warns for a person, informs for an unchecked picture, and says nothing for a clear one', () => {
    expect(markLine(pictureOut({ mark: 'person' }))).toEqual({
      type: 'warning',
      text: 'Frigate was tracking a person. Blur them before you share it, or leave it out.',
    })
    expect(markLine(pictureOut({ mark: 'unchecked' }))).toEqual({
      type: 'info',
      text: "The device couldn't check for people. Look closely before you share it.",
    })
    expect(markLine(pictureOut({ mark: 'clear' }))).toBeNull()
  })

  it('has a note for a picture taken after a restart, and none for any other', () => {
    expect(restartNote(pictureOut({ after_restart: true }))).toBe(
      'The unit restarted before this picture, so it may not show this place.',
    )
    expect(restartNote(pictureOut({ after_restart: false }))).toBeNull()
  })

  it("never lets a restart change the mark's line", () => {
    for (const mark of ['clear', 'person', 'unchecked'] as const) {
      expect(markLine(pictureOut({ mark, after_restart: true }))).toEqual(
        markLine(pictureOut({ mark, after_restart: false })),
      )
    }
  })
})
