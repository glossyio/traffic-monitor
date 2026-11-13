<!--
  A line on the home page, for an admin, while the unit has a Wi-Fi join to show (a test, a countdown to the switch, or
  a result nobody has dismissed), with a link to the Network page, where it is handled. An admin who started a join may
  not have that page open when the countdown ends. It asks when the home page loads and keeps asking while the join is
  pending (useJoin), so the time moves and the line follows the join to its end. It shows nothing for a viewer, for no
  join, or when the first answer can't be read: the home page works without it.
-->
<script setup lang="ts">
import { onMounted } from 'vue'
import { type JoinState, bannerLine, pending, useJoin } from '../modules/network/join'
import { useSession } from '../stores/session'

const session = useSession()
const { join, refresh } = useJoin()

onMounted(() => {
  if (session.isAdmin) void refresh()
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
