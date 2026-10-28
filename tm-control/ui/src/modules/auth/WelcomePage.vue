<!-- An admin accepts a new version of the license agreement (POST /setup/eula/accept), which reopens the apps. -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, messageOf } from '../../api/client'
import type { Eula } from '../../api/types'
import EulaText from '../../components/EulaText.vue'
import { useSession } from '../../stores/session'

const session = useSession()
const router = useRouter()

const eula = ref<Eula | null>(null)
const accepted = ref(false)
const accepting = ref(false)
const error = ref('')

async function loadEula() {
  error.value = ''
  try {
    const { data } = await api.GET('/api/v1/setup/eula')
    eula.value = data as Eula
  } catch (caught) {
    error.value = messageOf(caught)
  }
}

async function accept() {
  if (!eula.value) return
  error.value = ''
  accepting.value = true
  try {
    await api.POST('/api/v1/setup/eula/accept', { body: { version: eula.value.version } })
    await session.refresh()
    await router.push('/')
  } catch (caught) {
    error.value = messageOf(caught)
  } finally {
    accepting.value = false
  }
}

onMounted(loadEula)
</script>

<template>
  <section>
    <h1 class="text-h5 text-primary mb-4">Accept the new license agreement</h1>
    <p class="text-body-1 mb-6">
      The license agreement has changed. The device's apps stay closed to everyone until you accept the new version.
    </p>
    <v-progress-linear v-if="!eula && !error" indeterminate color="primary" class="mb-4" />
    <EulaText v-if="eula" :markdown="eula.markdown" />
    <v-checkbox
      v-model="accepted"
      :disabled="!eula"
      label="I accept the license agreement"
      hide-details
      class="mt-4 mb-4 ms-n2"
    />
    <v-alert v-if="error" type="error" class="mb-6">{{ error }}</v-alert>
    <div class="d-flex ga-3 flex-wrap">
      <v-btn variant="text" size="large" href="/logout">Log out</v-btn>
      <v-spacer />
      <v-btn color="primary" size="large" :disabled="!accepted" :loading="accepting" @click="accept">
        Accept and continue
      </v-btn>
    </div>
  </section>
</template>
