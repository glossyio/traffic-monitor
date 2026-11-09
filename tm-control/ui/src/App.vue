<!--
  The frame around every page. Before login (and while a new license waits for an admin) a page stands alone in a
  narrow column. After login, pages get the app bar and the menu, which stays open on wide screens and slides in from
  the menu button below Vuetify's md breakpoint (960 px).
-->
<script setup lang="ts">
import { mdiAccountOutline, mdiLogout } from '@mdi/js'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useDisplay } from 'vuetify'
import { MODULES } from './modules'
import { useSession } from './stores/session'

const session = useSession()
const route = useRoute()
const { smAndDown } = useDisplay()

const drawer = ref<boolean | null>(null) // null: open on wide screens, closed on narrow ones
const navItems = computed(() =>
  MODULES.flatMap((module) => module.nav).filter((item) => !item.adminOnly || session.isAdmin),
)
const roleName = computed(() => (session.isAdmin ? 'Administrator' : 'Viewer'))
const unreachable = computed(() => !session.loaded && session.loadError !== '')

function logOut() {
  // The server ends the session and redirects to /login; the full page load starts the app afresh.
  window.location.assign('/logout')
}

function reload() {
  window.location.reload()
}
</script>

<template>
  <v-app>
    <template v-if="unreachable || route.meta.bare">
      <v-main>
        <v-container class="py-8 py-sm-12">
          <v-sheet max-width="480" color="transparent" class="mx-auto">
            <p class="text-subtitle-1 font-weight-bold text-primary mb-8">Traffic Monitor</p>
            <template v-if="unreachable">
              <h1 class="text-h5 text-primary mb-4">The control app isn't answering</h1>
              <v-alert type="error" class="mb-6">{{ session.loadError }}</v-alert>
              <v-btn color="primary" size="large" @click="reload">Try again</v-btn>
            </template>
            <router-view v-else />
          </v-sheet>
        </v-container>
      </v-main>
    </template>

    <template v-else>
      <v-app-bar flat color="background" border="b">
        <v-app-bar-nav-icon v-if="smAndDown" aria-label="Menu" @click="drawer = !drawer" />
        <v-app-bar-title class="text-primary font-weight-bold">Traffic Monitor</v-app-bar-title>
      </v-app-bar>

      <v-navigation-drawer v-model="drawer" mobile-breakpoint="md" color="background">
        <!-- Not a "nav" list: that shrinks the item text to 13 px -->
        <v-list>
          <v-list-item
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            :prepend-icon="item.icon"
            :title="item.title"
            color="primary"
            exact
          />
        </v-list>
        <template #append>
          <v-divider />
          <v-list>
            <v-list-item :prepend-icon="mdiAccountOutline" :title="session.user?.username" :subtitle="roleName" />
            <v-list-item :prepend-icon="mdiLogout" title="Log out" @click="logOut" />
          </v-list>
        </template>
      </v-navigation-drawer>

      <v-main>
        <v-container class="py-6 py-md-8 px-4 px-md-8">
          <v-sheet max-width="760" color="transparent">
            <router-view />
          </v-sheet>
        </v-container>
      </v-main>
    </template>
  </v-app>
</template>
