// The map library stays out of the page's first download: only PinMap.vue imports it, and the picker loads that file
// on demand. A second importer anywhere under src/ would pull MapLibre into the entry chunk.
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, it } from 'vitest'

const here = import.meta.url
const src = fileURLToPath(new URL('../src', here))

function files(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? files(join(directory, entry.name)) : [join(directory, entry.name)],
  )
}

it('only PinMap.vue imports maplibre-gl', () => {
  const all = files(src)
  expect(all.length).toBeGreaterThan(20) // the scan found the sources
  // Code only: the About page's credits.json names the package as the dependency it credits
  const code = all.filter((file) => /\.(ts|vue)$/.test(file))
  const naming = code.filter((file) => readFileSync(file, 'utf8').includes('maplibre-gl')).map((f) => relative(src, f))
  expect(naming).toEqual(['modules/location/PinMap.vue'])
})
