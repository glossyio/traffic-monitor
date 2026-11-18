<!-- A viewer's page after nginx turns them away from an app that needs the device's administrator. -->
<script setup lang="ts">
import { useSession } from '../../stores/session'

const session = useSession()
</script>

<template>
  <section>
    <h1 class="text-h5 text-primary mb-4">This app is for administrators</h1>
    <p class="text-body-1 mb-6">
      You're logged in as {{ session.user?.username }}, a viewer. The app you opened needs this device's administrator.
    </p>
    <div class="d-flex ga-3 flex-wrap">
      <v-btn variant="text" size="large" href="/logout">Log out</v-btn>
      <v-spacer />
      <v-btn color="primary" size="large" to="/">Home</v-btn>
    </div>
  </section>
</template>
