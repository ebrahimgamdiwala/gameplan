<template>
  <Alert
    :title="title"
    :icon="false"
    :description="
      signupEnabled()
        ? 'Log in or create an account to reply, react and follow along.'
        : 'Log in to reply, react and follow along.'
    "
  >
    <template #actions><PublicLoginButtons size="md" /></template>
  </Alert>
</template>

<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { signupEnabled } from '@/utils/publicAccess'
import PublicLoginButtons from './PublicLoginButtons.vue'

withDefaults(defineProps<{ title?: string }>(), { title: 'Join the conversation' })
</script>
