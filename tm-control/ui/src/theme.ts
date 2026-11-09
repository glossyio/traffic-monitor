// The app's Vuetify instance and its one theme, built from the device's home-page colors (tmsetup_homepage_colors in
// the tmsetup role), which GET /api/v1/setup/status returns. Fonts and button text are set in styles/settings.scss.
import { createVuetify, type ThemeDefinition } from 'vuetify'
import { aliases, mdi } from 'vuetify/iconsets/mdi-svg'
import 'vuetify/styles'

// The role's defaults, for a device that sends none
export const DEFAULT_COLORS = {
  background: '#0C1120',
  header_text: '#3a82ff',
  body_text: '#f8fafc',
  link_hover_text: '#8895a7',
}

type ColorName = keyof typeof DEFAULT_COLORS

// Vuetify's dark-theme error color, set here so its button text can be chosen to match
const ERROR = '#CF6679'

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/

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
  const color = (name: ColorName) => {
    const value = colors?.[name]
    return value && HEX_COLOR.test(value) ? value : DEFAULT_COLORS[name]
  }
  const background = color('background')
  const primary = color('header_text')
  const text = color('body_text')
  // Text on a filled button: whichever of the page's two colors reads better on the button's color
  const textOn = (fill: string) => (contrast(fill, background) >= contrast(fill, text) ? background : text)
  return {
    dark: true,
    colors: {
      background,
      surface: mix(background, text, 0.05),
      primary,
      secondary: color('link_hover_text'),
      error: ERROR,
      'on-background': text,
      'on-surface': text,
      'on-primary': textOn(primary),
      'on-secondary': background,
      'on-error': textOn(ERROR),
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
