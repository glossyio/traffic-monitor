// Following an update (useUpdate in update.ts): when the page asks again, what a failed ask does, and when it stops.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, onMounted } from 'vue'
import { UPDATE_POLL_MS, useUpdate } from '../src/modules/update/update'
import { apiError, fakeApi, json, updateRun, updateState, type UpdateState } from './fake-api'
import { mountAlone } from './mount'

const UPDATE = 'GET /api/v1/update'

// A page of its own: useUpdate, asked once on mount as the Software update page asks it, and a line of what it holds
function host() {
  return defineComponent({
    setup() {
      const update = useUpdate()
      onMounted(() => void update.refresh())
      return update
    },
    render() {
      const run = this.state?.run
      return h('div', [
        h('p', { class: 'status' }, run ? run.status : 'none'),
        h('p', { class: 'stage' }, run?.stage ?? ''),
        h('p', { class: 'lost' }, this.lost ? 'lost' : ''),
        h('p', { class: 'error' }, this.loadError),
      ])
    },
  })
}

const asks = (api: { sent: { method: string; path: string }[] }) =>
  api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/update').length

const text = (wrapper: ReturnType<typeof mountAlone>, name: string) => wrapper.find(`.${name}`).text()

// An ask that gets no answer: it ends only when the page gives up on it
function silence(request: Request): Promise<Response> {
  return new Promise((_, reject) => {
    request.signal.addEventListener('abort', () => reject(new DOMException('The ask was given up', 'AbortError')))
  })
}

describe('following an update', () => {
  beforeEach(() => {
    document.body.replaceChildren()
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('asks again every 3 s only while a run is running or a start is pending', async () => {
    let answer: UpdateState = updateState()
    const api = fakeApi({ [UPDATE]: () => json(200, answer) })
    mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(0)
    expect(asks(api)).toBe(1)
    await vi.advanceTimersByTimeAsync(10 * UPDATE_POLL_MS)
    expect(asks(api)).toBe(1) // nothing running: one ask
    expect(UPDATE_POLL_MS).toBe(3000)

    // A start the device accepted, before the run's own state file is there
    const pending = useUpdateHost(() => json(200, updateState({ started: { run_id: 'r', status: 'starting', reason: null } })))
    await vi.advanceTimersByTimeAsync(0)
    expect(asks(pending.api)).toBe(1)
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(asks(pending.api)).toBe(2)
    pending.wrapper.unmount()

    // A running run, even one drawn from an older run's final file (no stages, everything else unknown)
    answer = updateState({ run: { status: 'running', readable: true, stages: [] } })
    const running = useUpdateHost(() => json(200, answer))
    await vi.advanceTimersByTimeAsync(0)
    expect(text(running.wrapper, 'status')).toBe('running')
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS - 1)
    expect(asks(running.api)).toBe(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(asks(running.api)).toBe(2)
  })

  it('keeps the last state and keeps asking when an ask fails, and says lost', async () => {
    let fail: 'no' | 'network' | 'bad gateway' | 'silence' = 'no'
    const api = fakeApi({
      [UPDATE]: (request) => {
        if (fail === 'network') return Promise.reject(new TypeError('Failed to fetch'))
        if (fail === 'bad gateway') return apiError(502, 'error', 'Bad gateway')
        if (fail === 'silence') return silence(request)
        return json(200, updateState({ run: updateRun({ stage: 'switch' }) }))
      },
    })
    const wrapper = mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(0)
    expect(text(wrapper, 'lost')).toBe('')

    for (const kind of ['network', 'bad gateway'] as const) {
      fail = kind
      await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
      expect(text(wrapper, 'lost'), kind).toBe('lost')
      expect(text(wrapper, 'stage'), kind).toBe('switch') // the last state stays
      expect(text(wrapper, 'error'), kind).toBe('') // not an error
      fail = 'no'
      await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
      expect(text(wrapper, 'lost'), kind).toBe('')
    }

    fail = 'silence'
    const before = asks(api)
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(asks(api)).toBe(before + 1)
    await vi.advanceTimersByTimeAsync(7999)
    expect(text(wrapper, 'lost')).toBe('') // still waiting for this ask's answer
    await vi.advanceTimersByTimeAsync(1)
    expect(text(wrapper, 'lost')).toBe('lost') // 8 s with no answer
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(asks(api)).toBe(before + 2) // and it asks again
    fail = 'no'
    await vi.advanceTimersByTimeAsync(8000 + UPDATE_POLL_MS)
    expect(text(wrapper, 'lost')).toBe('')
  })

  it('says the first load failed, rather than lost, when there is no state yet', async () => {
    const api = fakeApi({ [UPDATE]: () => Promise.reject(new TypeError('Failed to fetch')) })
    const wrapper = mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(0)
    expect(text(wrapper, 'error')).toContain("The device didn't answer.")
    expect(text(wrapper, 'lost')).toBe('')
    await vi.advanceTimersByTimeAsync(10 * UPDATE_POLL_MS)
    expect(asks(api)).toBe(1)
  })

  it('stops when the run ends, and on unmount', async () => {
    let answer = updateState({ run: updateRun() })
    const api = fakeApi({ [UPDATE]: () => json(200, answer) })
    const wrapper = mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(asks(api)).toBe(2)
    answer = updateState({ run: updateRun({ status: 'ok', stage: 'cleanup' }) })
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(asks(api)).toBe(3)
    expect(text(wrapper, 'status')).toBe('ok')
    await vi.advanceTimersByTimeAsync(10 * UPDATE_POLL_MS)
    expect(asks(api)).toBe(3)

    answer = updateState({ run: updateRun() })
    const other = useUpdateHost(() => json(200, answer))
    await vi.advanceTimersByTimeAsync(UPDATE_POLL_MS)
    expect(asks(other.api)).toBe(2)
    other.wrapper.unmount()
    await vi.advanceTimersByTimeAsync(10 * UPDATE_POLL_MS)
    expect(asks(other.api)).toBe(2)
  })

  it('drops an answer that arrives after a newer ask', async () => {
    let release: (response: Response) => void = () => {}
    let first = true
    fakeApi({
      [UPDATE]: () => {
        if (!first) return json(200, updateState({ run: updateRun({ status: 'ok', stage: 'cleanup' }) }))
        first = false
        return new Promise<Response>((resolve) => (release = resolve))
      },
    })
    const wrapper = mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(0) // the first ask is out, unanswered
    await (wrapper.vm as unknown as { refresh(): Promise<void> }).refresh() // a newer one, answered at once
    expect(text(wrapper, 'status')).toBe('ok')
    release(json(200, updateState({ run: updateRun({ stage: 'prepare' }) })))
    await vi.advanceTimersByTimeAsync(0)
    expect(text(wrapper, 'status')).toBe('ok')
  })
})

// A second host on its own fake API, for a test that needs a fresh one
function useUpdateHost(answer: (request: Request) => Response | Promise<Response>) {
  const api = fakeApi({ [UPDATE]: answer })
  const wrapper = mountAlone(host(), {})
  return { api, wrapper }
}
