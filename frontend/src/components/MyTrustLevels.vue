<template>
  <section v-if="levels.length" class="mb-5 mt-5" data-testid="my-trust-levels">
    <h2 class="text-base font-medium text-ink-gray-9">Your level</h2>
    <div class="mt-2 divide-y divide-outline-gray-1 rounded-5 border border-outline-gray-1">
      <div v-for="item in levels" :key="item.community" class="px-4 py-3">
        <div class="flex items-center justify-between gap-3">
          <p class="truncate text-base text-ink-gray-9">{{ item.title }}</p>
          <Badge :label="item.level" />
        </div>
        <p class="mt-1 text-p-sm text-ink-gray-6">{{ levelDescriptions[item.level] }}</p>
        <ul v-if="nextSteps(item.level, item.requirements).length" class="mt-2 space-y-1">
          <li
            v-for="step in nextSteps(item.level, item.requirements)"
            :key="step.label"
            class="flex items-start gap-2 text-p-sm text-ink-gray-7"
          >
            <span
              :class="[
                step.met ? 'lucide-circle-check text-ink-gray-7' : 'lucide-circle text-ink-gray-4',
                'mt-0.5 size-4 shrink-0',
              ]"
              aria-hidden="true"
            />
            <span>{{ step.label }}</span>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { Badge, useCall } from 'frappe-ui'
import { computed } from 'vue'
import { levelDescriptions, nextSteps, type MyLevel } from '@/data/trustLevels'

// POST: the first read can store the member's level, and a GET would discard it.
const request = useCall<MyLevel[]>({
  url: '/api/v2/method/gameplan.trust_levels.my_levels',
  method: 'POST',
  immediate: true,
  initialData: [],
})
const levels = computed(() => request.data || [])
</script>
