// @vitest-environment node
// The home button's build limit: it is on the file's size in bytes, which is what nginx sends, not its length in characters.
import type { Plugin } from 'vite'
import { expect, it } from 'vitest'
import config from '../vite.home-button.config'

const LIMIT = 10240

function build(code: string): void {
  const plugin = (config.plugins as Plugin[]).find((p) => p.name === 'home-button-size-limit')!
  const generate = plugin.generateBundle as (this: unknown, options: unknown, bundle: unknown) => void
  generate.call({}, {}, { 'home-button.js': { type: 'chunk', code } })
}

it('accepts a file of exactly the limit', () => {
  expect(() => build('a'.repeat(LIMIT))).not.toThrow()
})

it('refuses a file one byte over the limit', () => {
  expect(() => build('a'.repeat(LIMIT + 1))).toThrow(`home-button.js is ${LIMIT + 1} bytes; the limit is ${LIMIT}`)
})

it('counts bytes, not characters', () => {
  // 5 121 two-byte characters: 5 121 long, 10 242 bytes
  expect(() => build('é'.repeat(5121))).toThrow(`home-button.js is 10242 bytes; the limit is ${LIMIT}`)
})
