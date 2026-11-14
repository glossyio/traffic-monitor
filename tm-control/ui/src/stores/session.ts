// The app's only store: whether the device is claimed, the license state, and who is logged in. The router loads it
// once; pages refresh it after they log in, claim, or accept the license.
import { defineStore } from 'pinia'
import { api, messageOf } from '../api/client'
import type { Session, SetupStatus, User } from '../api/types'

export const useSession = defineStore('session', {
  state: () => ({
    status: null as SetupStatus | null,
    user: null as User | null,
    loaded: false,
    loadError: '', // why the last load failed, such as the device not answering
    hostname: '', // the unit's name for the tab and the bar; '' until known, or when it couldn't be read
  }),
  getters: {
    claimed: (state) => state.status?.claimed ?? false,
    eulaAccepted: (state) => state.status?.eula.accepted ?? false,
    eulaVersion: (state) => state.status?.eula.version ?? '',
    isAdmin: (state) => state.user?.role === 'admin',
  },
  actions: {
    async load() {
      if (!this.loaded) await this.refresh()
    },
    async refresh() {
      try {
        const [status, session] = await Promise.all([
          api.GET('/api/v1/setup/status'),
          api.GET('/api/v1/auth/session'),
        ])
        this.status = status.data as SetupStatus
        this.user = (session.data as Session).user
        this.loaded = true
        this.loadError = ''
        if (this.user) void this.loadName()
      } catch (error) {
        this.loadError = messageOf(error)
      }
    },
    // The name is a nicety: any failure leaves it empty, and the tab and the bar say just "Traffic Monitor"
    async loadName() {
      try {
        const { data } = await api.GET('/api/v1/system/device')
        const name = (data as { hostname?: unknown } | undefined)?.hostname
        this.hostname = typeof name === 'string' ? name : ''
      } catch {
        this.hostname = ''
      }
    },
    sessionEnded() {
      this.user = null
      this.hostname = ''
    },
  },
})
