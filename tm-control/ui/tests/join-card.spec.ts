// The join's result card, its words (join.ts), and the join state's polling and countdown (useJoin).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, onMounted } from 'vue'
import JoinCard from '../src/modules/network/JoinCard.vue'
import { JOIN_POLL_MS, bannerLine, clock, pending, useJoin } from '../src/modules/network/join'
import { JOIN_COUNTDOWN, NETWORK_STATE, apiError, fakeApi, joinState, json } from './fake-api'
import { click, mountAlone } from './mount'

const MAC = '2C:CF:67:00:AB:12'
const JOIN = 'GET /api/v1/network/join'
const SWITCH = 'POST /api/v1/network/wifi/join/switch'
const CANCEL = 'POST /api/v1/network/wifi/join/cancel'

function card(changes: Record<string, unknown> = {}) {
  return mountAlone(JoinCard, {
    join: JOIN_COUNTDOWN,
    lost: false,
    localName: 'tm-ab12.local',
    mac: MAC,
    hotspot: NETWORK_STATE.hotspot,
    admin: true,
    ...changes,
  })
}

const buttons = (wrapper: ReturnType<typeof card>) => wrapper.findAll('button').map((b) => b.text().trim())

// A page of its own: useJoin, asked once as the Network page asks it, and the card it feeds
function host() {
  return defineComponent({
    setup() {
      const state = useJoin()
      onMounted(() => void state.refresh())
      return { join: state.join, lost: state.lost }
    },
    render() {
      return this.join
        ? h(JoinCard, { join: this.join, lost: this.lost, localName: 'tm-ab12.local', mac: MAC, hotspot: null, admin: true })
        : h('div')
    },
  })
}

const asks = (api: { sent: { method: string; path: string }[] }) =>
  api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/network/join').length

describe('asking for the join', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('asks again every two seconds while the join is pending, and stops once it is over', async () => {
    vi.useFakeTimers()
    let answer = JOIN_COUNTDOWN
    const api = fakeApi({ [JOIN]: () => json(200, answer) })
    mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(0)
    expect(asks(api)).toBe(1)
    await vi.advanceTimersByTimeAsync(JOIN_POLL_MS)
    expect(asks(api)).toBe(2)
    answer = joinState({ stage: 'joined', seconds_left: null })
    await vi.advanceTimersByTimeAsync(JOIN_POLL_MS)
    expect(asks(api)).toBe(3)
    await vi.advanceTimersByTimeAsync(10 * JOIN_POLL_MS)
    expect(asks(api)).toBe(3)
  })

  it('asks no more when there is no join', async () => {
    vi.useFakeTimers()
    const api = fakeApi({ [JOIN]: json(200, null) })
    mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(10 * JOIN_POLL_MS)
    expect(asks(api)).toBe(1)
  })

  it('keeps asking, and says it lost the unit, while requests fail during a test', async () => {
    vi.useFakeTimers()
    let down = false
    const api = fakeApi({
      [JOIN]: () => (down ? Promise.reject(new TypeError('Failed to fetch')) : json(200, joinState({ stage: 'testing' }))),
    })
    const wrapper = mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.text()).not.toContain('lost the unit')
    down = true
    await vi.advanceTimersByTimeAsync(JOIN_POLL_MS)
    expect(wrapper.text()).toContain('This page lost the unit')
    expect(wrapper.text()).toContain('Testing Neighbour.') // the last answer stays
    await vi.advanceTimersByTimeAsync(3 * JOIN_POLL_MS)
    expect(asks(api)).toBeGreaterThanOrEqual(5)
    down = false
    await vi.advanceTimersByTimeAsync(JOIN_POLL_MS)
    expect(wrapper.text()).not.toContain('lost the unit')
  })

  it('stops asking when the page is left', async () => {
    vi.useFakeTimers()
    const api = fakeApi({ [JOIN]: JOIN_COUNTDOWN })
    const wrapper = mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(0)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(10 * JOIN_POLL_MS)
    expect(asks(api)).toBe(1)
  })
})

describe('the join words', () => {
  it('writes a time as m:ss', () => {
    expect(clock(192)).toBe('3:12')
    expect(clock(300)).toBe('5:00')
    expect(clock(59)).toBe('0:59')
    expect(clock(0)).toBe('0:00')
    expect(clock(-3)).toBe('0:00')
  })

  it('is pending while it tests, counts down, or switches', () => {
    expect(pending(null)).toBe(false)
    for (const stage of ['testing', 'countdown', 'switching'] as const) expect(pending(joinState({ stage }))).toBe(true)
    for (const stage of ['joined', 'failed', 'cancelled', 'switch_failed', 'interrupted'] as const) {
      expect(pending(joinState({ stage }))).toBe(false)
    }
  })

  it('sums each stage up in a line for the home page', () => {
    const line = (changes: Parameters<typeof joinState>[0]) => bannerLine(joinState(changes))
    expect(line({ stage: 'testing' })).toBe('Testing Neighbour.')
    expect(line({ stage: 'countdown' })).toBe('Neighbour works. The unit joins it in 3:12.')
    expect(line({ stage: 'switching' })).toBe('The unit is joining Neighbour.')
    expect(line({ stage: 'joined' })).toBe('The unit is on Neighbour.')
    for (const stage of ['failed', 'switch_failed', 'interrupted'] as const) {
      expect(line({ stage })).toBe("The unit couldn't join Neighbour.")
    }
    expect(line({ stage: 'cancelled' })).toBe('The join of Neighbour was cancelled.')
  })
})

describe('the join card', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    Reflect.deleteProperty(document, 'execCommand')
  })

  it('shows the address, the MAC address, the .local name, and the internet line after a test that passed', () => {
    const wrapper = card()
    const text = wrapper.text()
    expect(text).toContain('Neighbour works')
    expect(text).toContain("The unit's address there: 192.168.1.80")
    expect(text).toContain(`Wi-Fi MAC address: ${MAC}`)
    expect(text).toContain('Or open: http://tm-ab12.local/')
    expect(text).toContain('Internet: reachable')
    expect(text).toContain('Joining Neighbour in 3:12')
    expect(text).toContain(
      'When the unit joins Neighbour, its hotspot stops. Join Neighbour with your phone or computer too, then open one of the addresses above.',
    )
    expect(wrapper.find('button[aria-label="Copy the unit\'s address on Neighbour"]').exists()).toBe(true)
    expect(wrapper.find('a').exists()).toBe(false)
    expect(buttons(wrapper)).toEqual(expect.arrayContaining(['Cancel', 'Switch now']))
  })

  it('leaves out the hotspot sentence when the unit was not on its hotspot', () => {
    const text = card({ join: joinState({ before: 'HomeNet' }) }).text()
    expect(text).not.toContain('its hotspot stops')
    expect(text).toContain('Join Neighbour with your phone or computer too, then open one of the addresses above.')
  })

  it("says the internet is not reachable, or needs a sign-in page in the design's words", () => {
    expect(card({ join: joinState({ internet: 'not_reachable' }) }).text()).toContain('Internet: not reachable')
    document.body.replaceChildren()
    const text = card({ join: joinState({ internet: 'sign_in_page' }) }).text()
    expect(text).toContain('Joined, but this network needs a sign-in page, so the unit has no internet there.')
    expect(text).not.toContain('Internet: ')
  })

  it('counts down between answers and shows the time as m:ss', async () => {
    vi.useFakeTimers()
    fakeApi({ [JOIN]: JOIN_COUNTDOWN })
    const wrapper = mountAlone(host(), {})
    await vi.advanceTimersByTimeAsync(0)
    expect(wrapper.text()).toContain('Joining Neighbour in 3:12')
    await vi.advanceTimersByTimeAsync(1000)
    expect(wrapper.text()).toContain('Joining Neighbour in 3:11')
    expect(wrapper.text()).not.toContain('3:12')
  })

  it('ends the countdown on Switch now and says to join the network yourself', async () => {
    const api = fakeApi({ [SWITCH]: json(202, { id: 'job1' }) })
    const wrapper = card()
    await click(wrapper, 'Switch now')
    expect(api.sent.filter((r) => r.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/v1/network/wifi/join/switch', body: {} },
    ])
    expect(wrapper.text()).toContain(
      'The unit is joining Neighbour now. Join Neighbour yourself, then open http://tm-ab12.local/ or http://192.168.1.80/.',
    )
    expect(wrapper.emitted('changed')).toHaveLength(1)
    expect(buttons(wrapper)).not.toContain('Switch now')
  })

  it('cancels on Cancel', async () => {
    const api = fakeApi({ [CANCEL]: json(202, { id: 'job1' }) })
    const wrapper = card()
    await click(wrapper, 'Cancel')
    expect(api.sent.filter((r) => r.method === 'POST')).toEqual([
      { method: 'POST', path: '/api/v1/network/wifi/join/cancel', body: {} },
    ])
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('shows the device\'s refusal, and asks the page to reload, when a button is refused', async () => {
    fakeApi({ [SWITCH]: apiError(409, 'no_countdown', 'The unit is not counting down.') })
    const wrapper = card()
    await click(wrapper, 'Switch now')
    expect(wrapper.text()).toContain('The unit is not counting down.')
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('says the unit is testing, and to rejoin when the page loses the unit during a test', () => {
    const testing = joinState({ stage: 'testing', address: null, internet: null, seconds_left: null })
    let wrapper = card({ join: testing })
    expect(wrapper.text()).toContain('Testing Neighbour. This takes up to a minute.')
    expect(wrapper.text()).not.toContain('lost the unit')

    document.body.replaceChildren()
    wrapper = card({ join: testing, lost: true })
    expect(wrapper.text()).toContain('Testing Neighbour. This takes up to a minute.')
    expect(wrapper.text()).toContain(
      'This page lost the unit, which is expected during the test. When TM-AB12 reappears, join it again. This page then shows the result.',
    )
    expect(wrapper.find('[role="alert"].v-alert--variant-flat, .v-alert[type="error"]').exists()).toBe(false)
  })

  it('says the unit goes back by itself when a test that started from a Wi-Fi network loses the page', () => {
    const testing = joinState({ stage: 'testing', before: 'Home', address: null, internet: null, seconds_left: null })
    const text = card({ join: testing, lost: true }).text()
    expect(text).toContain(
      'This page lost the unit, which is expected during the test if you reach it over Wi-Fi. When the test ends the unit goes back to where it was, and this page then shows the result.',
    )
    expect(text).not.toContain('TM-AB12')
    expect(text).not.toContain('join it again')
  })

  it('says why a test failed, with the MAC address for a network that lists its devices', () => {
    const failed = joinState({ stage: 'failed', joined: false, reason: 'not_joined', address: null, internet: null, seconds_left: null })
    const text = card({ join: failed }).text()
    expect(text).toContain(
      `The unit couldn't join Neighbour. The usual cause is a wrong password. If the network only admits listed devices, add the unit's Wi-Fi MAC address, ${MAC}, to its list.`,
    )
    expect(text).toContain('Nothing was saved.')
  })

  it('has a Copy button on the MAC address of a failed test, for a viewer too, and none without one', async () => {
    const failed = joinState({ stage: 'failed', joined: false, reason: 'not_joined', address: null, internet: null, seconds_left: null })
    const copied: string[] = []
    Object.defineProperty(document, 'execCommand', {
      value: vi.fn((command: string) => {
        const area = document.activeElement as HTMLTextAreaElement
        if (command === 'copy') copied.push(area.value.slice(area.selectionStart, area.selectionEnd))
        return true
      }),
      configurable: true,
    })
    vi.spyOn(HTMLTextAreaElement.prototype, 'select').mockImplementation(() => {})
    const copy = 'button[aria-label="Copy Wi-Fi MAC address"]'

    const wrapper = card({ join: failed, admin: false })
    expect(wrapper.findAll(copy)).toHaveLength(1)
    await wrapper.find(copy).trigger('click')
    await vi.waitFor(() => expect(copied).toEqual([MAC]))
    expect(wrapper.text()).toContain(`add the unit's Wi-Fi MAC address, ${MAC}, to its list. Nothing was saved.`)

    document.body.replaceChildren()
    const unknown = card({ join: failed, mac: null })
    expect(unknown.find(copy).exists()).toBe(false)
    expect(unknown.text()).toContain("add the unit's Wi-Fi MAC address to its list. Nothing was saved.")
  })

  it('lets the line about a refused copy wrap, outside the no-wrap MAC address', async () => {
    const failed = joinState({ stage: 'failed', joined: false, reason: 'not_joined', address: null, internet: null, seconds_left: null })
    Object.defineProperty(document, 'execCommand', { value: vi.fn(() => false), configurable: true })
    const wrapper = card({ join: failed })
    await wrapper.find('button[aria-label="Copy Wi-Fi MAC address"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Select the text to copy it.'))
    const line = wrapper.findAll('span').find((span) => span.text() === 'Select the text to copy it.')!
    expect(line.element.closest('.text-no-wrap')).toBeNull()
  })

  it('says the network gave no address', () => {
    const failed = joinState({ stage: 'failed', joined: false, reason: 'no_address', address: null, internet: null, seconds_left: null })
    let text = card({ join: failed }).text()
    expect(text).toContain('Neighbour let the unit in but gave it no address.')
    expect(text).toContain('Nothing was saved.')
    document.body.replaceChildren()
    text = card({ join: { ...failed, saved: true } }).text()
    expect(text).toContain('The saved network is kept.')
  })

  it('says nothing was tried for a network that is not in range', () => {
    const failed = joinState({ stage: 'failed', joined: false, reason: 'not_in_range', address: null, internet: null, seconds_left: null })
    expect(card({ join: failed }).text()).toContain("Neighbour isn't in range right now, so nothing was tried.")
  })

  it('says a saved network is kept when its test fails', () => {
    const failed = joinState({ stage: 'failed', saved: true, joined: false, reason: 'not_joined', address: null, internet: null, seconds_left: null })
    const text = card({ join: failed }).text()
    expect(text).toContain('The saved network is kept.')
    expect(text).not.toContain('Nothing was saved.')
  })

  it('says the unit was busy, or that the test could not run', () => {
    const failed = joinState({ stage: 'failed', joined: false, address: null, internet: null, seconds_left: null })
    expect(card({ join: { ...failed, reason: 'busy' } }).text()).toContain(
      'The unit was busy with its Wi-Fi. Try again in a minute.',
    )
    document.body.replaceChildren()
    expect(card({ join: { ...failed, reason: 'error' } }).text()).toContain(
      "The test couldn't run. The unit is back where it was.",
    )
  })

  it('says the unit is on the network, or that it was cancelled', () => {
    expect(card({ join: joinState({ stage: 'joined', seconds_left: null }) }).text()).toContain(
      'The unit is on Neighbour. Its address there is 192.168.1.80.',
    )
    document.body.replaceChildren()
    expect(card({ join: joinState({ stage: 'cancelled', seconds_left: null }) }).text()).toContain(
      "Cancelled. The unit didn't join Neighbour.",
    )
  })

  it('says the switch failed and the network stays saved', () => {
    expect(card({ join: joinState({ stage: 'switch_failed', seconds_left: null }) }).text()).toContain(
      "The test passed, but the unit couldn't join Neighbour when the countdown ended. It is back where it was. Neighbour stays saved, and the unit tries it again by itself.",
    )
  })

  it('says the test was interrupted', () => {
    expect(card({ join: joinState({ stage: 'interrupted', seconds_left: null }) }).text()).toContain(
      'The test of Neighbour was interrupted. The unit goes back to where it was within a minute and a half.',
    )
  })

  it('dismisses a finished result', async () => {
    const api = fakeApi({ [CANCEL]: json(202, { id: 'job1' }) })
    const wrapper = card({ join: joinState({ stage: 'cancelled', seconds_left: null }) })
    expect(buttons(wrapper)).toEqual(expect.arrayContaining(['Dismiss']))
    await click(wrapper, 'Dismiss')
    expect(api.sent.filter((r) => r.method === 'POST').map((r) => [r.path, r.body])).toEqual([
      ['/api/v1/network/wifi/join/cancel', {}],
    ])
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('shows a viewer the countdown with no buttons', () => {
    const wrapper = card({ admin: false })
    expect(wrapper.text()).toContain('Joining Neighbour in 3:12')
    expect(wrapper.findAll('button').filter((b) => !b.attributes('aria-label')?.startsWith('Copy '))).toEqual([])
    document.body.replaceChildren()
    const done = card({ admin: false, join: joinState({ stage: 'cancelled', seconds_left: null }) })
    expect(buttons(done)).not.toContain('Dismiss')
  })

  it('says the unit is joining now, whatever else it knows, once the stage is switching', () => {
    const text = card({ join: joinState({ stage: 'switching', seconds_left: null }), lost: true }).text()
    expect(text).toContain('The unit is joining Neighbour now. Join Neighbour yourself, then open http://tm-ab12.local/ or http://192.168.1.80/.')
  })
})

