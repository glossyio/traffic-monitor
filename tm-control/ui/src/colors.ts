// The home page's colors and how a device's own are chosen. No imports: the home button's script uses this file too, and
// it must not pull in Vuetify.

// The role's defaults, for a device that sends none
export const DEFAULT_COLORS = {
  background: '#0C1120',
  header_text: '#3a82ff',
  body_text: '#f8fafc',
  link_hover_text: '#8895a7',
}

export type ColorName = keyof typeof DEFAULT_COLORS

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/

// The device's color when it is #rrggbb, else the default
export function colorOf(colors: Partial<Record<string, string>> | undefined, name: ColorName): string {
  const value = colors?.[name]
  return value && HEX_COLOR.test(value) ? value : DEFAULT_COLORS[name]
}
