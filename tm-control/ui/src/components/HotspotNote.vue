<!--
  Shown on the login and setup pages when the phone is on the unit's own hotspot (GET /setup/status says so).
  The address is plain text, not a link: inside the phone's sign-in window a link would open in that window.
-->
<script setup lang="ts">
import { useSession } from '../stores/session'

const session = useSession()
</script>

<template>
  <v-alert v-if="session.status?.hotspot" type="info" variant="tonal" class="mb-6">
    You're on this unit's hotspot. It has no internet. On an iPhone, open http://{{ session.status.hotspot.local_name }}/
    in Safari to save downloaded files.
  </v-alert>
</template>
