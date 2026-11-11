<!--
  A line on the home page, for an admin, while the unit has a Wi-Fi join to show (a test, a countdown to the switch, or
  a result nobody has dismissed), with a link to the Network page, where it is handled. An admin who started a join may
  not have that page open when the countdown ends. It asks once when the home page loads, and shows nothing for a
  viewer, for no join, or when the answer can't be read: the home page works without it.
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { type JoinState, bannerLine, pending } from '../modules/network/join'
import { useSession } from '../stores/session'

const session = useSession()
const join = ref<JoinState | null>(null)

onMounted(async () => {
  if (!session.isAdmin) return
  try {
    const { data } = await api.GET('/api/v1/network/join')
    join.value = (data ?? null) as JoinState | null
  } catch {
    join.value = null
  }
})

const look = (state: JoinState): 'info' | 'success' | 'warning' =>
  pending(state) || state.stage === 'cancelled' ? 'info' : state.stage === 'joined' ? 'success' : 'warning'
</script>

<template>
  <v-alert v-if="join" :type="look(join)" class="mb-6">
    {{ bannerLine(join) }}
    <template #append>
      <v-btn variant="text" size="large" to="/network">See it</v-btn>
    </template>
  </v-alert>
</template>
