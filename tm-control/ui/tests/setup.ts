// jsdom lacks ResizeObserver, which Vuetify's layout uses to measure the app bar and drawer.
import { vi } from 'vitest'

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverStub)
