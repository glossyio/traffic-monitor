// The page's own head: the referrer policy that keeps the device's address out of the links the map shows.
import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

// Read through a variable: Vite rewrites `new URL(path, import.meta.url)` into a served asset's address
const here = import.meta.url

it('sets the referrer policy to same-origin, before the app loads', () => {
  const html = readFileSync(new URL('../index.html', here), 'utf8')
  const tags = [...html.matchAll(/<meta\b[^>]*\bname="referrer"[^>]*>/g)].map((m) => m[0])
  expect(tags).toHaveLength(1)
  // same-origin, not no-referrer: the device's own requests keep their Referer, which the CSRF check falls back on
  expect(tags[0]).toContain('content="same-origin"')
  expect(html.indexOf(tags[0])).toBeLessThan(html.indexOf('<script'))
  expect(html.indexOf(tags[0])).toBeLessThan(html.indexOf('</head>'))
})
