<!-- A viewer's page while a new license agreement waits for an admin to accept it. -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSession } from '../../stores/session'

const session = useSession()
const router = useRouter()
const stillWaiting = ref(false)

async function checkAgain() {
  await session.refresh()
  if (session.eulaAccepted) await router.push('/')
  else stillWaiting.value = true
}
</script>

<template>
  <section>
    <h1 class="text-h5 text-primary mb-4">Waiting for an administrator</h1>
    <p class="text-body-1 mb-6">
      The license agreement has changed. An administrator of this device must accept the new version before you can
      open the apps.
    </p>
    <v-alert v-if="stillWaiting" type="info" class="mb-6">An administrator hasn't accepted it yet.</v-alert>
    <div class="d-flex ga-3 flex-wrap">
      <v-btn variant="text" size="large" href="/logout">Log out</v-btn>
      <v-spacer />
      <v-btn color="primary" size="large" @click="checkAgain">Check again</v-btn>
    </div>
  </section>
</template>
