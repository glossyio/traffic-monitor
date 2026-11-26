// The database's size in words, counted in powers of 1024 as the Device page counts storage.
import { describe, expect, it } from 'vitest'
import { sizeWords } from '../src/modules/sharing/size'

describe('sizeWords', () => {
  it.each([
    [0, 'less than 1 MB'],
    [1_048_575, 'less than 1 MB'],
    [1_048_576, '1 MB'],
    [734_003_200, '700 MB'],
    [1_047_527_424, '999 MB'],
    [1_048_576_000, '1.0 GB'],
    [1_503_238_554, '1.4 GB'],
    [3_221_225_472, '3.0 GB'],
  ])('says %i bytes as "%s"', (bytes, words) => {
    expect(sizeWords(bytes)).toBe(words)
  })
})
