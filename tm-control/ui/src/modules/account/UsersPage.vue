<!--
  The admin's list of accounts (GET /users). The admin adds viewers (POST /users), sets a viewer's password
  (POST /users/{id}/password), and removes viewers (DELETE /users/{id}). The API refuses these for the admin's own
  account, so its row has no menu; the admin changes their own password on the account page.
-->
<script setup lang="ts">
import { mdiDotsVertical } from '@mdi/js'
import { computed, onMounted, ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { User } from '../../api/types'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { useSession } from '../../stores/session'

type FormRef = { validate: () => Promise<{ valid: boolean }>; reset: () => void } | null

const session = useSession()

const users = ref<User[] | null>(null)
const loadError = ref('')
const notice = ref('') // what the last change did, shown above the list
const viewers = computed(() => (users.value ?? []).filter((user) => user.role === 'viewer'))

const required = (value: string) => !!value || 'Fill this in.'

async function load() {
  loadError.value = ''
  try {
    const { data } = await api.GET('/api/v1/users')
    users.value = (data as { users: User[] }).users
  } catch (error) {
    loadError.value = messageOf(error)
  }
}

function added(created: string) {
  const date = new Date(created)
  if (Number.isNaN(date.getTime())) return ''
  return `added ${date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}`
}

function describe(user: User) {
  if (user.id === session.user?.id) return 'Administrator (you)'
  const role = user.role === 'admin' ? 'Administrator' : 'Viewer'
  const date = added(user.created_at)
  return date ? `${role}, ${date}` : role
}

// Adding a viewer
const addForm = ref<FormRef>(null)
const newUsername = ref('')
const newPassword = ref('')
const adding = ref(false)
const addError = ref('')

async function addViewer() {
  addError.value = ''
  notice.value = ''
  if (!(await addForm.value?.validate())?.valid) return
  adding.value = true
  try {
    const { data } = await api.POST('/api/v1/users', {
      body: { username: newUsername.value, password: newPassword.value },
    })
    const user = (data as { user: User }).user
    addForm.value?.reset()
    notice.value = `Added ${user.username}. Give them their username and password; they can change the password on their account page.`
    await load()
  } catch (error) {
    addError.value = messageOf(error)
  } finally {
    adding.value = false
  }
}

// Setting a viewer's password
const passwordFor = ref<User | null>(null)
const passwordForm = ref<FormRef>(null)
const resetPassword = ref('')
const resetting = ref(false)
const resetError = ref('')

function openPasswordDialog(user: User) {
  passwordFor.value = user
  resetPassword.value = ''
  resetError.value = ''
}

async function setPassword() {
  const user = passwordFor.value
  if (!user || !(await passwordForm.value?.validate())?.valid) return
  resetError.value = ''
  resetting.value = true
  try {
    await api.POST('/api/v1/users/{user_id}/password', {
      params: { path: { user_id: user.id } },
      body: { new_password: resetPassword.value },
    })
    passwordFor.value = null
    notice.value = `New password set for ${user.username}. They're logged out everywhere and must use the new password.`
  } catch (error) {
    resetError.value = messageOf(error)
  } finally {
    resetting.value = false
  }
}

// Removing a viewer
const removing = ref<User | null>(null)
const confirmingRemove = computed({
  get: () => removing.value !== null,
  set: (open: boolean) => {
    if (!open) removing.value = null
  },
})
const removeError = ref('')

async function remove(user: User) {
  removeError.value = ''
  notice.value = ''
  try {
    await api.DELETE('/api/v1/users/{user_id}', { params: { path: { user_id: user.id } } })
    notice.value = `Removed ${user.username}.`
    await load()
  } catch (error) {
    removeError.value = messageOf(error)
  }
}

function confirmRemove() {
  const user = removing.value
  if (user) void remove(user)
}

onMounted(load)
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-4">Users</h1>
    <p class="text-body-1 mb-10">
      Viewers can open the dashboards and Frigate. They can't open the Node-RED editor, the camera feeds, or Cockpit,
      and can't change settings.
    </p>

    <section class="mb-10">
      <h2 class="text-h6 mb-4">Add a viewer</h2>
      <v-form ref="addForm" @submit.prevent="addViewer">
        <v-text-field
          v-model="newUsername"
          label="Username"
          hint="3 to 32 characters: lowercase letters, digits, dots, dashes, or underscores"
          persistent-hint
          autocomplete="off"
          autocapitalize="none"
          spellcheck="false"
          class="mb-4"
          :rules="[required]"
        />
        <v-text-field
          v-model="newPassword"
          label="Password"
          type="password"
          hint="At least 10 characters"
          persistent-hint
          autocomplete="new-password"
          class="mb-4"
          :rules="[required]"
        />
        <v-alert v-if="addError" type="error" class="mb-6">{{ addError }}</v-alert>
        <v-btn type="submit" color="primary" size="large" :loading="adding">Add viewer</v-btn>
      </v-form>
    </section>

    <section>
      <h2 class="text-h6 mb-4">Accounts</h2>
      <v-alert v-if="notice" type="success" class="mb-4" closable @click:close="notice = ''">{{ notice }}</v-alert>
      <v-alert v-if="removeError" type="error" class="mb-4">{{ removeError }}</v-alert>
      <v-alert v-if="loadError" type="error" class="mb-4">
        {{ loadError }}
        <template #append>
          <v-btn variant="text" @click="load">Try again</v-btn>
        </template>
      </v-alert>
      <v-progress-linear v-else-if="!users" indeterminate color="primary" />

      <v-list v-if="users" bg-color="surface" rounded="lg" lines="two">
        <v-list-item v-for="user in users" :key="user.id" :title="user.username" :subtitle="describe(user)">
          <template v-if="user.id !== session.user?.id" #append>
            <v-menu location="bottom end">
              <template #activator="{ props }">
                <v-btn v-bind="props" :icon="mdiDotsVertical" variant="text" :aria-label="`Actions for ${user.username}`" />
              </template>
              <v-list>
                <v-list-item title="Set a new password" @click="openPasswordDialog(user)" />
                <v-list-item title="Remove" base-color="error" @click="removing = user" />
              </v-list>
            </v-menu>
          </template>
        </v-list-item>
      </v-list>
      <p v-if="users && viewers.length === 0" class="text-body-1 text-secondary mt-4">
        No viewers yet. Add one for each person who should see the data without changing anything.
      </p>
    </section>

    <v-dialog :model-value="passwordFor !== null" max-width="440" @update:model-value="passwordFor = null">
      <v-card v-if="passwordFor" color="surface" rounded="lg">
        <v-card-title class="text-h6 text-wrap pt-4">Set a new password for {{ passwordFor.username }}</v-card-title>
        <v-form ref="passwordForm" @submit.prevent="setPassword">
          <v-card-text>
            <p class="text-body-1 mb-4">They're logged out everywhere and must use the new password.</p>
            <v-text-field
              v-model="resetPassword"
              label="New password"
              type="password"
              hint="At least 10 characters"
              persistent-hint
              autocomplete="new-password"
              :rules="[required]"
            />
            <v-alert v-if="resetError" type="error" class="mt-4">{{ resetError }}</v-alert>
          </v-card-text>
          <v-card-actions class="px-4 pb-4">
            <v-spacer />
            <v-btn variant="text" @click="passwordFor = null">Cancel</v-btn>
            <v-btn type="submit" color="primary" variant="flat" :loading="resetting">Set password</v-btn>
          </v-card-actions>
        </v-form>
      </v-card>
    </v-dialog>

    <ConfirmDialog
      v-model="confirmingRemove"
      :title="`Remove ${removing?.username ?? ''}?`"
      text="They're logged out at once and can't log in again."
      confirm-text="Remove viewer"
      @confirm="confirmRemove"
    />
  </div>
</template>
