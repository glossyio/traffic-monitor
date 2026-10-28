<!-- One's own account: who you are, a new password (POST /account/password), and logging out everywhere. -->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, messageOf } from '../../api/client'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { useSession } from '../../stores/session'

const session = useSession()
const router = useRouter()

const roleName = computed(() => (session.isAdmin ? 'Administrator' : 'Viewer'))

const passwordForm = ref<{ validate: () => Promise<{ valid: boolean }>; reset: () => void } | null>(null)
const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const changing = ref(false)
const changed = ref(false)
const passwordError = ref('')

const required = (value: string) => !!value || 'Fill this in.'
const passwordsMatch = (value: string) => value === newPassword.value || "The passwords don't match."

async function changePassword() {
  passwordError.value = ''
  changed.value = false
  if (!(await passwordForm.value?.validate())?.valid) return
  changing.value = true
  try {
    await api.POST('/api/v1/account/password', {
      body: { current_password: currentPassword.value, new_password: newPassword.value },
    })
    passwordForm.value?.reset()
    changed.value = true
  } catch (error) {
    // A wrong current password is a 401 that leaves the session alone (the client knows this path)
    passwordError.value = messageOf(error)
  } finally {
    changing.value = false
  }
}

const confirmingLogout = ref(false)
const logoutError = ref('')

async function logOutEverywhere() {
  logoutError.value = ''
  try {
    await api.POST('/api/v1/auth/logout-everywhere')
    session.sessionEnded()
    await router.push('/login')
  } catch (error) {
    logoutError.value = messageOf(error)
  }
}
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Your account</h1>
    <v-row dense class="mb-10">
      <v-col cols="12" sm="6">
        <div class="text-body-2 text-secondary">Username</div>
        <div class="text-body-1">{{ session.user?.username }}</div>
      </v-col>
      <v-col cols="12" sm="6">
        <div class="text-body-2 text-secondary">Role</div>
        <div class="text-body-1">{{ roleName }}</div>
      </v-col>
    </v-row>

    <section class="mb-10">
      <h2 class="text-h6 mb-2">Change your password</h2>
      <p class="text-body-1 mb-6">Changing it logs you out of every other browser and phone.</p>
      <v-form ref="passwordForm" @submit.prevent="changePassword">
        <v-text-field
          v-model="currentPassword"
          label="Current password"
          type="password"
          autocomplete="current-password"
          class="mb-4"
          :rules="[required]"
        />
        <v-text-field
          v-model="newPassword"
          label="New password"
          type="password"
          hint="At least 10 characters"
          persistent-hint
          autocomplete="new-password"
          class="mb-4"
          :rules="[required]"
        />
        <v-text-field
          v-model="confirmPassword"
          label="Confirm new password"
          type="password"
          autocomplete="new-password"
          class="mb-2"
          :rules="[required, passwordsMatch]"
        />
        <v-alert v-if="passwordError" type="error" class="mb-6">{{ passwordError }}</v-alert>
        <v-alert v-if="changed" type="success" class="mb-6">
          Password changed. Other browsers and phones where you were logged in are logged out.
        </v-alert>
        <v-btn type="submit" color="primary" size="large" :loading="changing">Change password</v-btn>
      </v-form>
    </section>

    <section>
      <h2 class="text-h6 mb-2">Log out everywhere</h2>
      <p class="text-body-1 mb-6">
        Ends your sessions in every browser and on every phone, including this one. Use it if you logged in on a
        device that isn't yours.
      </p>
      <v-alert v-if="logoutError" type="error" class="mb-6">{{ logoutError }}</v-alert>
      <v-btn variant="outlined" size="large" @click="confirmingLogout = true">Log out everywhere</v-btn>
    </section>

    <ConfirmDialog
      v-model="confirmingLogout"
      title="Log out everywhere?"
      text="You'll be logged out of every browser and phone, including this one."
      confirm-text="Log out everywhere"
      @confirm="logOutEverywhere"
    />
  </div>
</template>
