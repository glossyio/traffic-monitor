<!-- Log in (POST /auth/login), then go back to the page that asked for it (?next=), if it's on this device. -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, api, messageOf } from '../../api/client'
import { goNext } from '../../next'
import { useSession } from '../../stores/session'

const session = useSession()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const loggingIn = ref(false)
const error = ref('')

async function logIn() {
  error.value = ''
  loggingIn.value = true
  try {
    await api.POST('/api/v1/auth/login', { body: { username: username.value, password: password.value } })
    await session.refresh()
    await goNext(router, route.query.next)
  } catch (caught) {
    if (caught instanceof ApiError && caught.code === 'not_claimed') {
      await session.refresh()
      await router.push('/setup')
      return
    }
    error.value = messageOf(caught)
  } finally {
    loggingIn.value = false
  }
}
</script>

<template>
  <section>
    <h1 class="text-h5 text-primary mb-6">Log in</h1>
    <v-form @submit.prevent="logIn">
      <v-text-field
        v-model="username"
        label="Username"
        autocomplete="username"
        autocapitalize="none"
        spellcheck="false"
        class="mb-2"
      />
      <v-text-field v-model="password" label="Password" type="password" autocomplete="current-password" class="mb-2" />
      <v-alert v-if="error" type="error" class="mb-6">{{ error }}</v-alert>
      <v-btn type="submit" color="primary" size="large" block :loading="loggingIn" :disabled="!username || !password">
        Log in
      </v-btn>
    </v-form>
    <p class="text-body-2 text-secondary mt-8">
      Forgot your password? An administrator can set a new one on the Users page. If the administrator's password is
      lost, someone with access to the device can run <code>sudo tm-control reset-admin</code> to set it up again. That
      removes every account.
    </p>
  </section>
</template>
