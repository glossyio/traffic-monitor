// jsdom lacks ResizeObserver, which Vuetify's layout uses to measure the app bar and drawer, and visualViewport,
// which its dialogs read to place themselves (null takes Vuetify's own fallback for browsers without it).
import { vi } from 'vitest'

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverStub)
vi.stubGlobal('visualViewport', null)
