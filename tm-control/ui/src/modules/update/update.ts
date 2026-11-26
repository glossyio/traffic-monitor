// The Software update's state (GET /update), kept current while an update runs. The run's state lives on the device,
// so the page only asks; it never decides what happened. Built like the Wi-Fi join's useJoin (network/join.ts).
import { getCurrentInstance, onBeforeUnmount, ref, type Ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'

export type UpdateState = components['schemas']['UpdateState']
export type Offer = components['schemas']['Offer']
export type Run = components['schemas']['Run']

export const UPDATE_POLL_MS = 3000
const UPDATE_ASK_TIMEOUT_MS = 8000 // one ask that gets no answer in this long fails like a network error

// A run under way, or a start the device accepted before the run's own state file is there
export function following(state: UpdateState | null): boolean {
  return state?.run?.status === 'running' || state?.started?.status === 'starting'
}

// refresh() asks now; while following() it asks again every UPDATE_POLL_MS. An ask that fails while the page follows a
// run (`lost`: the device stops answering while it switches or restarts) leaves the last state in place and keeps
// asking. A failed first load is `loadError`. show() puts in an answer the page got itself (a check's, a start's) and
// asks on from there. stop() ends the asking; leaving the page does too.
export function useUpdate(): {
  state: Ref<UpdateState | null>
  lost: Ref<boolean>
  loadError: Ref<string>
  refresh(): Promise<void>
  show(next: UpdateState): void
  stop(): void
} {
  const state = ref<UpdateState | null>(null)
  const lost = ref(false)
  const loadError = ref('')
  let stopped = false
  let asked = 0 // counts the asks and the answers put in, so an answer that arrives after a newer one is dropped
  let poll: ReturnType<typeof setTimeout> | undefined

  function next() {
    clearTimeout(poll)
    poll = undefined
    if (!stopped && following(state.value)) poll = setTimeout(() => void refresh(), UPDATE_POLL_MS)
  }

  function show(answer: UpdateState) {
    asked += 1
    state.value = answer
    lost.value = false
    loadError.value = ''
    next()
  }

  async function refresh() {
    clearTimeout(poll)
    const mine = ++asked
    const controller = new AbortController()
    const limit = setTimeout(() => controller.abort(), UPDATE_ASK_TIMEOUT_MS)
    try {
      const { data } = await api.GET('/api/v1/update', { signal: controller.signal })
      if (stopped || mine !== asked) return
      state.value = data as UpdateState
      lost.value = false
      loadError.value = ''
    } catch (error) {
      if (stopped || mine !== asked) return
      if (state.value === null) loadError.value = messageOf(error)
      else if (following(state.value)) lost.value = true
    } finally {
      clearTimeout(limit)
    }
    next()
  }

  function stop() {
    stopped = true
    clearTimeout(poll)
    poll = undefined
  }

  if (getCurrentInstance()) onBeforeUnmount(stop)
  return { state, lost, loadError, refresh, show, stop }
}
