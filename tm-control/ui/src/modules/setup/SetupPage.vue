<!--
  First run, in four steps on one page: welcome, the license agreement, the administrator account (which claims the
  device with its setup code), and an optional new system password. The API checks everything; this page collects the
  answers, posts them, and shows the API's messages.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, api, messageOf } from '../../api/client'
import type { Eula, Job } from '../../api/types'
import EulaText from '../../components/EulaText.vue'
import { goNext } from '../../next'
import { useSession } from '../../stores/session'

const STEPS = ['Welcome', 'License agreement', 'Administrator account', 'System password']
const JOB_POLL_MS = 1000
const JOB_DEADLINE_MS = 120_000 // after this, stop waiting for the job and let setup go on

const session = useSession()
const router = useRouter()
const route = useRoute()

const step = ref(1)
const progress = computed(() => (step.value / STEPS.length) * 100)

// Each step's heading takes the keyboard focus, so a screen reader announces the new step
const heading = ref<HTMLElement | null>(null)
watch(step, async () => {
  await nextTick()
  heading.value?.focus()
})

const required = (value: string) => !!value || 'Fill this in.'

// Step 2: the license agreement
const eula = ref<Eula | null>(null)
const eulaError = ref('')
const accepted = ref(false)

async function loadEula() {
  eulaError.value = ''
  try {
    const { data } = await api.GET('/api/v1/setup/eula')
    eula.value = data as Eula
  } catch (error) {
    eulaError.value = messageOf(error)
  }
}

async function startSetup() {
  step.value = 2
  if (!eula.value) await loadEula()
}

// Step 3: the administrator account
const claimForm = ref<{ validate: () => Promise<{ valid: boolean }> } | null>(null)
const setupCode = ref('')
const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const claiming = ref(false)
const claimError = ref('')
const alreadyClaimed = ref(false)

// Typed or pasted as "abcd efgh", "ABCDEFGH", or "ABCD-EFGH": shown as the card prints it, ABCD-EFGH. Nothing is cut
// off: a longer paste ("Code: ABCD-EFGH") stays too long, and wholeCode refuses it, rather than becoming another code.
function formatSetupCode(text: string) {
  const chars = text.toUpperCase().replace(/[^A-Z0-9]/g, '')
  return chars.length > 4 ? `${chars.slice(0, 4)}-${chars.slice(4)}` : chars
}

// The raw text first, then the formatted code: when formatting gives the code the field already had (a pasted
// " ABCD-EFGH" over ABCD-EFGH), Vue would see no change and leave the raw text showing.
async function onSetupCodeInput(text: string) {
  setupCode.value = text
  await nextTick()
  setupCode.value = formatSetupCode(text)
}

const passwordsMatch = (value: string) => value === password.value || "The passwords don't match."
// Checked here so a mistyped code doesn't use up one of the device's limited tries
const wholeCode = (value: string) => value.replace('-', '').length === 8 || 'The setup code has 8 letters and digits.'

async function claim() {
  claimError.value = ''
  alreadyClaimed.value = false
  if (!(await claimForm.value?.validate())?.valid) return
  claiming.value = true
  try {
    await api.POST('/api/v1/setup/claim', {
      body: {
        setup_code: setupCode.value,
        username: username.value,
        password: password.value,
        eula_version: eula.value?.version ?? '',
      },
    })
    await session.refresh()
    step.value = 4
  } catch (error) {
    const wrongCode = error instanceof ApiError && error.code === 'invalid_setup_code'
    claimError.value = wrongCode
      ? `${messageOf(error)} Check the code on the card or in the installer's output and try again.`
      : messageOf(error)
    alreadyClaimed.value = error instanceof ApiError && error.code === 'already_claimed'
  } finally {
    claiming.value = false
  }
}

// Step 4: the system password, set by a root job that the page waits for
const systemForm = ref<{ validate: () => Promise<{ valid: boolean }> } | null>(null)
const samePassword = ref(false)
const systemPassword = ref('')
const confirmSystemPassword = ref('')
const systemError = ref('')
const job = ref<Job | null>(null)
const jobRunning = ref(false)
const jobTimedOut = ref(false) // the job never reported a result within JOB_DEADLINE_MS

const systemPasswordsMatch = (value: string) => value === systemPassword.value || "The passwords don't match."

watch(samePassword, (same) => {
  systemPassword.value = same ? password.value : ''
  confirmSystemPassword.value = same ? password.value : ''
})

// Leaving the page (Skip for now, or the browser's back button) stops the polling
let left = false
let pollTimer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => {
  left = true
  clearTimeout(pollTimer)
})

function pause(ms: number) {
  return new Promise((resolve) => {
    pollTimer = setTimeout(resolve, ms)
  })
}

async function setSystemPassword() {
  systemError.value = ''
  job.value = null
  jobTimedOut.value = false
  if (!(await systemForm.value?.validate())?.valid) return
  jobRunning.value = true
  try {
    const { data } = await api.POST('/api/v1/system/password', { body: { password: systemPassword.value } })
    const id = (data as { id: string }).id
    const deadline = Date.now() + JOB_DEADLINE_MS
    for (;;) {
      const answer = await api.GET('/api/v1/jobs/{job_id}', { params: { path: { job_id: id } } })
      if (left) return
      const current = answer.data as Job
      if (current.status === 'succeeded' || current.status === 'failed') {
        job.value = current
        return
      }
      // queued or running: the device may never say more, for example when tm-control can't read the journal
      if (Date.now() >= deadline) {
        jobTimedOut.value = true
        return
      }
      await pause(JOB_POLL_MS)
    }
  } catch (error) {
    systemError.value = messageOf(error)
  } finally {
    jobRunning.value = false
  }
}

function finish() {
  void goNext(router, route.query.next)
}
</script>

<template>
  <div>
    <p class="text-body-2 text-secondary mb-2">Step {{ step }} of {{ STEPS.length }}: {{ STEPS[step - 1] }}</p>
    <v-progress-linear :model-value="progress" color="primary" rounded height="4" class="mb-8" />

    <section v-if="step === 1">
      <h1 ref="heading" tabindex="-1" class="text-h5 text-primary mb-4">Set up this Traffic Monitor</h1>
      <p class="text-body-1 mb-4">
        Setup takes a few minutes. You'll accept the license agreement, create the administrator account for this
        device, and can give the device a new system password.
      </p>
      <p class="text-body-1 mb-8">
        You need the setup code. It's printed on the card that came with the device, or at the end of the installer's
        output if you installed Traffic Monitor yourself.
      </p>
      <v-btn color="primary" size="large" block @click="startSetup">Start setup</v-btn>
    </section>

    <section v-else-if="step === 2">
      <h1 ref="heading" tabindex="-1" class="text-h5 text-primary mb-4">Read the license agreement</h1>
      <v-alert v-if="eulaError" type="error" class="mb-4">
        {{ eulaError }}
        <template #append>
          <v-btn variant="text" @click="loadEula">Try again</v-btn>
        </template>
      </v-alert>
      <v-progress-linear v-else-if="!eula" indeterminate color="primary" class="mb-4" />
      <EulaText v-else :markdown="eula.markdown" />
      <v-checkbox
        v-model="accepted"
        :disabled="!eula"
        label="I accept the license agreement"
        hide-details
        class="mt-4 mb-6 ms-n2"
      />
      <div class="d-flex ga-3">
        <v-btn variant="text" size="large" @click="step = 1">Back</v-btn>
        <v-spacer />
        <v-btn color="primary" size="large" :disabled="!accepted" @click="step = 3">Continue</v-btn>
      </div>
    </section>

    <section v-else-if="step === 3">
      <h1 ref="heading" tabindex="-1" class="text-h5 text-primary mb-4">Create the administrator account</h1>
      <p class="text-body-1 mb-6">
        The administrator can change settings and add accounts for other people. Choose a password you don't use
        anywhere else.
      </p>
      <v-form ref="claimForm" @submit.prevent="claim">
        <v-text-field
          :model-value="setupCode"
          label="Setup code"
          placeholder="XXXX-XXXX"
          hint="8 letters and digits, from the card that came with the device or the end of the installer's output"
          persistent-hint
          autocomplete="off"
          autocapitalize="characters"
          spellcheck="false"
          class="setup-code mb-4"
          :rules="[required, wholeCode]"
          @update:model-value="onSetupCodeInput"
        />
        <v-text-field
          v-model="username"
          label="Username"
          hint="3 to 32 characters: lowercase letters, digits, dots, dashes, or underscores"
          persistent-hint
          autocomplete="username"
          autocapitalize="none"
          spellcheck="false"
          class="mb-4"
          :rules="[required]"
        />
        <v-text-field
          v-model="password"
          label="Password"
          type="password"
          hint="At least 10 characters"
          persistent-hint
          autocomplete="new-password"
          class="mb-4"
          :rules="[required]"
        />
        <v-text-field
          v-model="confirmPassword"
          label="Confirm password"
          type="password"
          autocomplete="new-password"
          class="mb-2"
          :rules="[required, passwordsMatch]"
        />
        <v-alert v-if="claimError" type="error" class="mb-6">
          {{ claimError }}
          <div v-if="alreadyClaimed" class="mt-3">
            <v-btn color="primary" variant="flat" to="/login">Log in</v-btn>
          </div>
        </v-alert>
        <div class="d-flex ga-3">
          <v-btn variant="text" size="large" @click="step = 2">Back</v-btn>
          <v-spacer />
          <v-btn type="submit" color="primary" size="large" :loading="claiming">Claim this device</v-btn>
        </div>
      </v-form>
    </section>

    <section v-else>
      <h1 ref="heading" tabindex="-1" class="text-h5 text-primary mb-4">Set the system password</h1>
      <template v-if="job?.status === 'succeeded'">
        <v-alert type="success" class="mb-6">
          System password set. Use it from now on to log in to Cockpit (the device's system tools) and over SSH.
        </v-alert>
        <v-btn color="primary" size="large" block @click="finish">Go to the home page</v-btn>
      </template>
      <template v-else-if="jobTimedOut">
        <v-alert type="warning" class="mb-6">
          The device hasn't reported whether the system password changed. It may still change in a moment, and you
          can go on with setup. Later, log in to Cockpit with the new password. If it doesn't work, use the old one,
          and change it on Cockpit's Accounts page.
        </v-alert>
        <v-btn color="primary" size="large" block @click="finish">Go to the home page</v-btn>
      </template>
      <template v-else>
        <p class="text-body-1 mb-6">
          The device also has a system account, for Cockpit (the device's system tools) and SSH. Give it a new
          password now, or skip this and keep the password it has.
        </p>
        <v-form ref="systemForm" :disabled="jobRunning" @submit.prevent="setSystemPassword">
          <v-checkbox
            v-model="samePassword"
            label="Use the same password as my account"
            hide-details
            class="mb-4 ms-n2"
          />
          <v-text-field
            v-model="systemPassword"
            label="System password"
            type="password"
            hint="At least 10 characters"
            persistent-hint
            autocomplete="new-password"
            class="mb-4"
            :rules="[required]"
          />
          <v-text-field
            v-model="confirmSystemPassword"
            label="Confirm system password"
            type="password"
            autocomplete="new-password"
            class="mb-2"
            :rules="[required, systemPasswordsMatch]"
          />
          <v-alert v-if="jobRunning" type="info" class="mb-6">
            Setting the system password. This usually takes a few seconds; you can skip ahead without waiting.
          </v-alert>
          <v-alert v-if="systemError" type="error" class="mb-6">{{ systemError }}</v-alert>
          <v-alert v-if="job?.status === 'failed'" type="error" class="mb-6">
            The system password wasn't changed. The device's log says:
            <pre v-if="job.log.length" class="text-body-2 mt-2 text-wrap">{{ job.log.join('\n') }}</pre>
          </v-alert>
          <div class="d-flex ga-3 flex-wrap">
            <v-btn variant="text" size="large" @click="finish">Skip for now</v-btn>
            <v-spacer />
            <v-btn type="submit" color="primary" size="large" :loading="jobRunning">Set system password</v-btn>
          </div>
        </v-form>
      </template>
    </section>
  </div>
</template>

<style scoped>
/* The setup code reads like the card it's printed on: monospace, larger, spaced out */
.setup-code :deep(input) {
  font-family: ui-monospace, 'SF Mono', 'Cascadia Mono', 'Roboto Mono', Menlo, Consolas, monospace;
  font-size: 1.375rem;
  letter-spacing: 0.15em;
}
</style>
