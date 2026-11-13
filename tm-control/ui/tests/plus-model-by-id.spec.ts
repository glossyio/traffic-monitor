// The form on the Detection page that uses a Frigate+ model by its ID: the field, the button, and the line that says
// Frigate is downloading. The page keeps the actions; the form only emits the id it cleaned.
import type { VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import PlusModelById, { cleanId } from '../src/modules/detection/PlusModelById.vue'
import { button, field, mountAlone, typeInto } from './mount'

const ID = '0123456789abcdef0123456789abcdef'
const WRONG = 'A model ID is 32 characters, each 0-9 or a-f.'

it.each([
  [ID, ID],
  [`  ${ID}\n`, ID],
  [`plus://${ID}`, ID],
  ['0123456789ABCDEF0123456789ABCDEF', null],
  ['0123', null],
  ['', null],
])('cleanId(%j) is %j', (typed, id) => expect(cleanId(typed)).toBe(id))

describe('PlusModelById', () => {
  beforeEach(() => document.body.replaceChildren())

  function mountForm(props: Partial<{ disabled: boolean; downloading: boolean; result: object | null }> = {}) {
    return mountAlone(PlusModelById, { disabled: false, downloading: false, result: null, ...props })
  }
  const typed = (wrapper: VueWrapper, text: string) => typeInto(field(wrapper, 'Model ID').element, text)

  it('emits the cleaned id, and only for an id', async () => {
    const wrapper = mountForm()
    const use = button(wrapper, 'Download and use')
    expect(use.attributes('disabled')).toBeDefined()
    await typed(wrapper, '0123')
    expect(use.attributes('disabled')).toBeDefined()
    await wrapper.find('form').trigger('submit') // Enter in the field
    expect(wrapper.emitted('use')).toBeUndefined()

    await typed(wrapper, `  plus://${ID}\n`)
    expect(use.attributes('disabled')).toBeUndefined()
    await wrapper.find('form').trigger('submit')
    expect(wrapper.emitted('use')).toEqual([[ID]])
  })

  it('says what an ID looks like once something that is not one is typed', async () => {
    const wrapper = mountForm()
    expect(wrapper.text()).not.toContain(WRONG)
    await typed(wrapper, '0123')
    expect(wrapper.text()).toContain(WRONG)
    await typed(wrapper, ID)
    expect(wrapper.text()).not.toContain(WRONG)
    await typed(wrapper, '')
    expect(wrapper.text()).not.toContain(WRONG)
  })

  it('leaves the field plain: shown, not capitalised, not spell-checked', () => {
    const input = field(mountForm(), 'Model ID')
    expect(input.attributes('type')).toBe('text')
    expect(input.attributes('autocapitalize')).toBe('off')
    expect(input.attributes('spellcheck')).toBe('false')
  })

  it.each([
    ['downloading', { downloading: true }],
    ['disabled', { disabled: true }],
  ])('disables the field and the button while %s', async (_, props) => {
    const wrapper = mountForm(props)
    await typed(wrapper, ID)
    expect(field(wrapper, 'Model ID').attributes('disabled')).toBeDefined()
    expect(button(wrapper, 'Download and use').attributes('disabled')).toBeDefined()
  })

  it('says it is downloading, and only then', () => {
    const line = 'Frigate is downloading the model. This can take a few minutes. You can leave this page.'
    expect(mountForm({ downloading: true }).text()).toContain(line)
    expect(mountForm().text()).not.toContain(line)
  })

  it('explains where the ID comes from, and shows its result', () => {
    const wrapper = mountForm({ result: { type: 'error', text: 'Set the Frigate+ API key first.' } })
    expect(wrapper.text()).toContain(
      "Copy the model's ID from your models on the Frigate+ website. Frigate downloads the model with the API key, then restarts.",
    )
    expect(wrapper.find('.v-alert').text()).toContain('Set the Frigate+ API key first.')
  })
})
