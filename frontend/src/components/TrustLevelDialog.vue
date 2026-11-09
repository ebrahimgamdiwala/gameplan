<template>
  <Dialog v-model:open="open" :title="title" :dismissible="!saving">
    <p class="mb-4 text-base text-ink-gray-6">
      {{ member.full_name || member.user }} · currently {{ member.level }}
      <span v-if="member.locked"> (locked)</span>
    </p>
    <template v-if="mode === 'level'">
      <Select v-model="level" label="Level" :options="levelOptions" :disabled="saving" />
      <p class="mt-2 text-p-sm text-ink-gray-6">{{ levelDescriptions[level] }}</p>
      <p v-if="!member.locked" class="mt-2 text-p-sm text-ink-gray-6">
        The rules can still raise this level later. Lock it to keep it as set.
      </p>
    </template>
    <p v-else class="text-p-sm text-ink-gray-6">
      {{
        member.locked
          ? 'Unlocking lets the rules raise this level again as the member contributes.'
          : 'Locking keeps this level as it is. The rules stop changing it until it is unlocked.'
      }}
    </p>
    <Textarea
      v-model="reason"
      class="mt-4"
      label="Reason (seen by moderators only)"
      :maxlength="500"
      :disabled="saving"
      required
    />
    <ErrorMessage
      v-if="error"
      class="mt-3"
      :message="extractServerMessage(error) || 'Could not change the level'"
    />
    <template #actions>
      <Button
        variant="solid"
        :disabled="!reason.trim() || (mode === 'level' && level === member.level)"
        :loading="saving"
        @click="save"
        >{{ confirmLabel }}</Button
      >
    </template>
  </Dialog>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, Dialog, ErrorMessage, Select, Textarea, call, toast } from 'frappe-ui'
import { extractServerMessage } from '@/utils'
import {
  TRUST_LEVELS,
  levelDescriptions,
  type MemberLevel,
  type TrustLevel,
} from '@/data/trustLevels'

const props = defineProps<{ member: MemberLevel; community: string; mode: 'level' | 'lock' }>()
const emit = defineEmits<{ saved: [] }>()
const open = defineModel<boolean>('open', { default: false })
const level = ref<TrustLevel>(props.member.level)
const reason = ref('')
const saving = ref(false)
const error = ref<unknown>(null)
const levelOptions = TRUST_LEVELS.map((value) => ({ label: value, value }))
const title = computed(() =>
  props.mode === 'level' ? 'Change level' : props.member.locked ? 'Unlock level' : 'Lock level',
)
const confirmLabel = computed(() =>
  props.mode === 'level' ? 'Change level' : props.member.locked ? 'Unlock' : 'Lock',
)

async function save() {
  saving.value = true
  error.value = null
  try {
    if (props.mode === 'level') {
      await call('gameplan.trust_levels.set_member_level', {
        community: props.community,
        user: props.member.user,
        level: level.value,
        reason: reason.value,
      })
      toast.success(`Level changed to ${level.value}.`)
    } else {
      await call('gameplan.trust_levels.set_member_lock', {
        community: props.community,
        user: props.member.user,
        locked: props.member.locked ? 0 : 1,
        reason: reason.value,
      })
      toast.success(props.member.locked ? 'Level unlocked.' : 'Level locked.')
    }
    open.value = false
    emit('saved')
  } catch (e) {
    error.value = e
  } finally {
    saving.value = false
  }
}
</script>
