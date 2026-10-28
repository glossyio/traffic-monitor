// The Vuetify theme comes from the device's home-page colors.
import { describe, expect, it } from 'vitest'
import { buildTheme, contrast } from '../src/theme'

describe('buildTheme', () => {
  it('uses the home-page defaults when the device sends no colors', () => {
    const colors = buildTheme(undefined).colors!
    expect(colors.background).toBe('#0C1120')
    expect(colors.primary).toBe('#3a82ff')
    expect(colors['on-background']).toBe('#f8fafc')
    expect(colors.secondary).toBe('#8895a7')
  })

  it('gives filled buttons whichever text color reads better on the primary color', () => {
    // White on the default blue is about 3.6:1; the navy is about 5.2:1
    expect(buildTheme(undefined).colors!['on-primary']).toBe('#0C1120')
    const dark = buildTheme({ background: '#000000', header_text: '#1a237e', body_text: '#ffffff' })
    expect(dark.colors!['on-primary']).toBe('#ffffff')
  })

  it('gives red buttons, such as "Remove viewer", text that passes WCAG AA', () => {
    const colors = buildTheme(undefined).colors!
    expect(contrast(colors.error!, colors['on-error']!)).toBeGreaterThanOrEqual(4.5)
  })

  it('ignores a color that is not #rrggbb', () => {
    expect(buildTheme({ header_text: 'red; background: url(x)' }).colors!.primary).toBe('#3a82ff')
  })

  it('makes cards slightly lighter than the page', () => {
    const { background, surface } = buildTheme(undefined).colors!
    expect(contrast(surface!, '#000000')).toBeGreaterThan(contrast(background!, '#000000'))
  })
})

describe('contrast', () => {
  it('matches the WCAG ratios', () => {
    expect(contrast('#ffffff', '#000000')).toBeCloseTo(21, 1)
    expect(contrast('#3a82ff', '#0C1120')).toBeCloseTo(5.2, 1)
  })
})
