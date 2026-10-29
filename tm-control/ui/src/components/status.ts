// How the four check statuses look, and the one sentence that sums up a status report. Shape carries the status as
// well as color (a tick, a triangle, a cross, a question mark), so it reads in sunlight and for color-blind people.
import { mdiAlert, mdiCheckCircle, mdiCloseCircle, mdiHelpCircle } from '@mdi/js'
import type { components } from '../api/schema'

export type CheckStatus = components['schemas']['Check']['status']

export interface StatusMark {
  icon: string // an @mdi/js icon path
  color: string // a theme color: Vuetify's dark-theme success, warning, and error, and the secondary text color
  label: string // the status in words, for screen readers
}

export const MARKS: Record<CheckStatus, StatusMark> = {
  ok: { icon: mdiCheckCircle, color: 'success', label: 'OK' },
  warn: { icon: mdiAlert, color: 'warning', label: 'Warning' },
  error: { icon: mdiCloseCircle, color: 'error', label: 'Problem' },
  unknown: { icon: mdiHelpCircle, color: 'secondary', label: 'Unknown' },
}

// What a restart or re-scan said when it finished: a result, or the API's error. The Status page writes it under
// the button that was pressed.
export interface Note {
  text: string
  error: boolean
}

// The report's summary in words, with the status whose mark goes beside it: any error outranks warnings, and
// warnings outrank checks that couldn't run.
export function verdict(summary: Partial<Record<string, number>>): { status: CheckStatus; text: string } {
  const errors = summary.error ?? 0
  const warnings = summary.warn ?? 0
  if (errors === 1) return { status: 'error', text: '1 problem needs attention' }
  if (errors > 1) return { status: 'error', text: `${errors} problems need attention` }
  if (warnings === 1) return { status: 'warn', text: 'Working, with 1 thing to look at' }
  if (warnings > 1) return { status: 'warn', text: `Working, with ${warnings} things to look at` }
  if ((summary.unknown ?? 0) > 0) return { status: 'unknown', text: "Some checks couldn't run" }
  return { status: 'ok', text: 'Everything is working' }
}
