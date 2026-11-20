<!--
  Shown on the login and setup pages when the phone is on the unit's own hotspot (GET /setup/status says so): the
  steps from the phone's sign-in window, which can't save every download, to a browser, which can. Copy comes first,
  because keeping the network closes the sign-in window and this note with it. The address is plain text, not a link:
  inside the sign-in window a link would open in that window.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { useSession } from '../stores/session'
import CopyButton from './CopyButton.vue'

const session = useSession()
const address = computed(() => `http://${session.status?.hotspot?.local_name}/`)
</script>

<template>
  <v-alert v-if="session.status?.hotspot" type="info" variant="tonal" class="mb-6">
    You're on this unit's hotspot. It has no internet. To save downloads, open the unit in a browser:
    <ol class="pl-6 mt-2">
      <li>
        Copy this address:
        <div class="d-flex align-center">
          <span class="text-break">{{ address }}</span>
          <CopyButton :text="address" label="the address" />
        </div>
      </li>
      <li>
        Keep this network. On Android, open this window's menu and choose Use this network as is. On an iPhone, tap
        Cancel, then Use Without Internet.
      </li>
      <li>Open the address in a browser. On Android 17, allow Nearby devices for the browser.</li>
    </ol>
  </v-alert>
</template>
