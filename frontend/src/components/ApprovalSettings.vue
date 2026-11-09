<template>
  <Button variant="ghost" icon-left="lucide-settings-2" @click="show">Approval settings</Button>
  <Dialog v-model:open="open" title="Community post approval" :dismissible="!saving">
    <p class="mb-4 text-base text-ink-gray-6">
      Review new contributors' discussions and replies before publication. Community staff are
      exempt. Existing published contributions count toward the threshold.
    </p>
    <Checkbox
      v-model="enabled"
      label="Require approval for new contributors"
      :disabled="loading || saving"
    />
    <TextInput
      v-if="enabled"
      v-model="count"
      class="mt-4"
      :label="
        levelsEnabled
          ? 'Accepted contributions to become a Member'
          : 'Accepted contributions needed to post freely'
      "
      type="number"
      :min="1"
      :max="100"
      :disabled="loading || saving"
    />
    <p class="mt-3 text-base text-ink-gray-5">
      Changes affect future submissions. Existing pending submissions still need a decision.
    </p>

    <div class="mt-5 border-t border-outline-gray-1 pt-4">
      <Checkbox
        v-model="levelsEnabled"
        label="Use trust levels"
        :disabled="loading || saving"
        data-testid="trust-levels-switch"
      />
      <p class="mt-2 text-p-sm text-ink-gray-6">
        Members move from New to Member to Trusted on their own. New members need approval, Members
        don't, and Trusted members also skip the link, image, file and mention caps. Moderators can
        change or lock a level on the Trust levels tab.
      </p>
      <template v-if="levelsEnabled">
        <p v-if="!enabled" class="mt-2 text-p-sm text-ink-gray-6">
          Approval is off, so everyone starts as a Member.
        </p>
        <p class="mt-4 text-base font-medium text-ink-gray-8">Trusted needs</p>
        <div class="mt-2 grid gap-3 sm:grid-cols-3">
          <TextInput
            v-model="trustedCount"
            label="Accepted contributions"
            type="number"
            :min="1"
            :max="100"
            :disabled="loading || saving"
          />
          <TextInput
            v-model="trustedDays"
            label="Days as a member"
            type="number"
            :min="0"
            :max="3650"
            :disabled="loading || saving"
          />
          <TextInput
            v-model="cleanDays"
            label="Clean record, days"
            type="number"
            :min="1"
            :max="3650"
            :disabled="loading || saving"
          />
        </div>
        <p class="mt-2 text-p-sm text-ink-gray-6">
          A clean record means no post removed by a moderator, no report upheld and no ban in that
          many days.
        </p>
      </template>
    </div>
    <ErrorMessage
      v-if="error"
      class="mt-3"
      :message="extractServerMessage(error) || 'Could not update approval settings'"
    />
    <template #actions
      ><Button
        variant="solid"
        :disabled="loading || !loaded || !valid"
        :loading="saving"
        @click="save"
        >Save approval policy</Button
      ></template
    >
  </Dialog>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { Button, Checkbox, Dialog, ErrorMessage, TextInput, call, toast } from 'frappe-ui'
import { extractServerMessage } from '@/utils'
import type { TrustSettings } from '@/data/trustLevels'
const props = defineProps<{ communityId: string }>()
const loaded = ref(false)
const open = ref(false),
  enabled = ref(false),
  count = ref('3'),
  levelsEnabled = ref(false),
  trustedCount = ref('25'),
  trustedDays = ref('30'),
  cleanDays = ref('90'),
  loading = ref(false),
  saving = ref(false),
  error = ref<unknown>(null)

function between(value: string, low: number, high: number) {
  const number = Number(value)
  return Number.isInteger(number) && number >= low && number <= high
}
const valid = computed(
  () =>
    (!enabled.value || between(count.value, 1, 100)) &&
    (!levelsEnabled.value ||
      (between(trustedCount.value, 1, 100) &&
        between(trustedDays.value, 0, 3650) &&
        between(cleanDays.value, 1, 3650))),
)

async function show() {
  open.value = true
  error.value = null
  loading.value = true
  loaded.value = false
  try {
    const [value, levels] = await Promise.all([
      call<number>('gameplan.approval_policy.get_policy', { community: props.communityId }),
      call<TrustSettings>('gameplan.trust_levels.get_settings', { community: props.communityId }),
    ])
    loaded.value = true
    enabled.value = value > 0
    count.value = String(value || 3)
    levelsEnabled.value = Boolean(levels.enabled)
    trustedCount.value = String(levels.trusted_count || 25)
    trustedDays.value = String(levels.trusted_days ?? 30)
    cleanDays.value = String(levels.clean_days || 90)
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
async function save() {
  saving.value = true
  error.value = null
  try {
    await call('gameplan.approval_policy.set_policy', {
      community: props.communityId,
      count: enabled.value ? Number(count.value) : 0,
    })
    await call('gameplan.trust_levels.save_settings', {
      community: props.communityId,
      enabled: levelsEnabled.value ? 1 : 0,
      trusted_count: Number(trustedCount.value),
      trusted_days: Number(trustedDays.value),
      clean_days: Number(cleanDays.value),
    })
    open.value = false
    toast.success('Approval policy saved.')
  } catch (e) {
    error.value = e
  } finally {
    saving.value = false
  }
}
</script>
