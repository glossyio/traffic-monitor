// The words and the asking for a Wi-Fi join (GET /network/join), shared by the Network page, the result card, and the
// home page's banner. The join's state lives on the device, so the page only asks; it never decides what happened.
import { getCurrentInstance, onBeforeUnmount, ref, type Ref } from 'vue'
import { api } from '../../api/client'
import type { components } from '../../api/schema'

export type JoinState = components['schemas']['JoinState']

export const JOIN_POLL_MS = 2000
const JOIN_ASK_TIMEOUT_MS = 8000 // one ask that gets no answer in this long fails like a network error
export const HOTSPOT_PROFILE = 'tm-hotspot' // `before` when the radio was on the unit's own hotspot

// Testing, counting down, or switching: the unit is still busy with it, and nothing else may change its Wi-Fi
export function pending(join: JoinState | null): boolean {
  return join !== null && (join.stage === 'testing' || join.stage === 'countdown' || join.stage === 'switching')
}

// "3:12". Never negative, and never seconds alone.
export function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

// One line for the home page
export function bannerLine(join: JoinState): string {
  const name = join.network
  switch (join.stage) {
    case 'testing':
      return `Testing ${name}.`
    case 'countdown':
      return `${name} works. The unit joins it in ${clock(join.seconds_left ?? 0)}.`
    case 'switching':
      return `The unit is joining ${name}.`
    case 'joined':
      return `The unit is on ${name}.`
    case 'cancelled':
      return `The join of ${name} was cancelled.`
    default:
      return `The unit couldn't join ${name}.` // failed, switch_failed, interrupted
  }
}

// The join the device reports, kept current. refresh() asks now; while the join is pending it asks again every
// JOIN_POLL_MS, and a request that fails (`lost`: the page can't reach the unit, which the test itself causes when
// the page is on the hotspot) leaves the last answer in place and keeps asking. Between answers the page counts
// `seconds_left` down by itself, so the clock moves every second. stop() ends the asking; leaving the page does too.
export function useJoin(): {
  join: Ref<JoinState | null>
  lost: Ref<boolean>
  refresh(): Promise<void>
  stop(): void
} {
  const join = ref<JoinState | null>(null)
  const lost = ref(false)
  let stopped = false
  let asked = 0 // counts the asks, so an answer that arrives after a newer ask is dropped
  let poll: ReturnType<typeof setTimeout> | undefined
  let tick: ReturnType<typeof setInterval> | undefined

  function counting() {
    const left = join.value?.seconds_left
    if (join.value?.stage === 'countdown' && left != null) {
      tick ??= setInterval(() => {
        const current = join.value
        if (current?.stage === 'countdown' && current.seconds_left != null) {
          join.value = { ...current, seconds_left: Math.max(0, current.seconds_left - 1) }
        }
      }, 1000)
    } else {
      clearInterval(tick)
      tick = undefined
    }
  }

  function next() {
    clearTimeout(poll)
    poll = undefined
    counting()
    if (!stopped && pending(join.value)) poll = setTimeout(() => void refresh(), JOIN_POLL_MS)
  }

  async function refresh() {
    clearTimeout(poll)
    const mine = ++asked
    const controller = new AbortController()
    const limit = setTimeout(() => controller.abort(), JOIN_ASK_TIMEOUT_MS)
    try {
      const { data } = await api.GET('/api/v1/network/join', { signal: controller.signal })
      if (stopped || mine !== asked) return
      join.value = (data ?? null) as JoinState | null
      lost.value = false
    } catch {
      if (stopped || mine !== asked) return
      lost.value = true
    } finally {
      clearTimeout(limit)
    }
    next()
  }

  function stop() {
    stopped = true
    clearTimeout(poll)
    clearInterval(tick)
    poll = undefined
    tick = undefined
  }

  if (getCurrentInstance()) onBeforeUnmount(stop)
  return { join, lost, refresh, stop }
}
