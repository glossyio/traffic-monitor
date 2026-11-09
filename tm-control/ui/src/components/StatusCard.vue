<!-- A card that names a thing and lists facts about it, label above value: the home page's device card. -->
<script setup lang="ts">
defineProps<{
  title: string
  subtitle?: string
  items: { label: string; value: string }[]
}>()
</script>

<template>
  <v-card color="surface" variant="flat" rounded="lg" class="pa-2">
    <v-card-item>
      <h2 class="text-h5 text-sm-h4 font-weight-medium text-break">{{ title }}</h2>
      <p v-if="subtitle" class="text-body-1 text-secondary mt-1">{{ subtitle }}</p>
    </v-card-item>
    <v-card-text>
      <v-row dense>
        <v-col v-for="item in items" :key="item.label" cols="12" sm="6">
          <div class="text-body-2 text-secondary">{{ item.label }}</div>
          <div class="text-body-1 text-break">{{ item.value }}</div>
        </v-col>
      </v-row>
    </v-card-text>
  </v-card>
</template>
