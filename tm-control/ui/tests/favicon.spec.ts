// The control app's favicon: the page links it, and the file stays small, plain, and free of editor leftovers.
import { readFileSync, statSync } from 'node:fs'
import { expect, it } from 'vitest'

// Read through a variable: Vite rewrites `new URL(path, import.meta.url)` into a served asset's address
const here = import.meta.url

it('links the favicon from the page as an SVG', () => {
  const html = readFileSync(new URL('../index.html', here), 'utf8')
  const icons = [...html.matchAll(/<link\b[^>]*\brel="icon"[^>]*>/g)].map((m) => m[0])
  expect(icons.length).toBe(1)
  expect(icons[0]).toContain('href="/favicon.svg"')
  expect(icons[0]).toContain('type="image/svg+xml"')
})

it('ships a small, plain SVG with a viewBox', () => {
  const file = new URL('../public/favicon.svg', here)
  const svg = readFileSync(file, 'utf8')
  expect(svg).toMatch(/^<svg\b/)
  expect(svg).toMatch(/\sviewBox="/)
  expect(svg).not.toMatch(/inkscape|sodipodi/i)
  expect(svg).not.toMatch(/<script/i)
  expect(statSync(file).size).toBeLessThan(4096)
})
