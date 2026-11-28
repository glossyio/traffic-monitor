// The app's Vuetify instance and its one theme, built from the device's home-page colors (tmsetup_homepage_colors in
// the tmsetup role), which GET /api/v1/setup/status returns. Fonts and button text are set in styles/settings.scss.
import { createVuetify, type ThemeDefinition } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi-svg'
import 'vuetify/styles'
import { colorOf, DEFAULT_COLORS, type ColorName } from './colors'

export { DEFAULT_COLORS }

// Vuetify's dark-theme error and warning colors, set here so the text on each can be chosen to match
const ERROR = '#CF6679'
const WARNING = '#FB8C00'

function channels(hex: string): number[] {
  return [1, 3, 5].map((start) => parseInt(hex.slice(start, start + 2), 16))
}

// WCAG relative luminance
function luminance(hex: string): number {
  const [r, g, b] = channels(hex).map((value) => {
    const c = value / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

// WCAG contrast ratio, from 1 (none) to 21 (black on white)
export function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (light + 0.05) / (dark + 0.05)
}

// `base` moved `amount` (0 to 1) of the way towards `other`
function mix(base: string, other: string, amount: number): string {
  const target = channels(other)
  const mixed = channels(base).map((value, i) => Math.round(value + (target[i] - value) * amount))
  return `#${mixed.map((value) => value.toString(16).padStart(2, '0')).join('')}`
}

export function buildTheme(colors: Partial<Record<string, string>> | undefined): ThemeDefinition {
  const color = (name: ColorName) => colorOf(colors, name)
  const background = color('background')
  const primary = color('header_text')
  const text = color('body_text')
  // Text on a filled button or a solid alert: whichever of the page's two colors reads better on its color
  const textOn = (fill: string) => (contrast(fill, background) >= contrast(fill, text) ? background : text)
  return {
    dark: true,
    colors: {
      background,
      surface: mix(background, text, 0.05),
      primary,
      secondary: color('link_hover_text'),
      error: ERROR,
      warning: WARNING,
      'on-background': text,
      'on-surface': text,
      'on-primary': textOn(primary),
      'on-secondary': background,
      'on-error': textOn(ERROR),
      'on-warning': textOn(WARNING),
    },
  }
}

export function createAppVuetify(colors: Partial<Record<string, string>> | undefined) {
  return createVuetify({
    theme: { defaultTheme: 'device', themes: { device: buildTheme(colors) } },
    icons: { defaultSet: 'mdi', aliases, sets: { mdi } },
    defaults: {
      VTextField: { variant: 'outlined', color: 'primary' },
      VCheckbox: { color: 'primary' },
      VAlert: { variant: 'tonal' },
    },
  })
}
