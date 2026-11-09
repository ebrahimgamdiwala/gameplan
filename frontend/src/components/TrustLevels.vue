<template>
  <div class="flex flex-wrap items-center justify-between gap-3 pb-3">
    <TabButtons v-model="filter" :options="filters" />
    <p v-if="enabled && members.length" class="text-p-sm text-ink-gray-6">
      {{ members.length }}{{ more ? '+' : '' }} shown
    </p>
  </div>
  <ErrorMessage
    v-if="error"
    class="pb-3"
    :message="extractServerMessage(error) || 'Could not load trust levels'"
  />
  <ModerationEmpty
    v-if="!loading && !error && !enabled"
    icon="lucide-award"
    title="Trust levels are off"
    :description="
      canManage
        ? 'Turn them on under Approval settings on the Approvals tab.'
        : 'A Community admin can turn them on.'
    "
  />
  <template v-else-if="members.length">
    <div class="border-t border-outline-gray-1" data-testid="trust-level-list">
      <template v-for="member in members" :key="member.user">
        <ModerationRow>
          <template #lead>
            <Avatar
              :image="useUser(member.user).user_image"
              :label="member.full_name || useUser(member.user).full_name"
              size="md"
            />
          </template>
          <template #title>{{ member.full_name || useUser(member.user).full_name }}</template>
          <template #meta>{{ summary(member) }}</template>
          <template #status>
            <Badge :label="member.level" />
            <Badge v-if="member.locked" label="Locked" />
          </template>
          <template #actions>
            <Button variant="subtle" @click="openDialog(member, 'level')">Change</Button>
            <Dropdown
              align="end"
              :button="{ icon: 'lucide-more-horizontal', variant: 'ghost', label: 'More actions' }"
              :options="[
                {
                  label: expanded === member.user ? 'Hide requirements' : 'Show requirements',
                  icon: 'lucide-list-checks',
                  onClick: () => (expanded = expanded === member.user ? '' : member.user),
                },
                {
                  label: member.locked ? 'Unlock level' : 'Lock level',
                  icon: member.locked ? 'lucide-lock-open' : 'lucide-lock',
                  onClick: () => openDialog(member, 'lock'),
                },
                {
                  label: 'View history',
                  icon: 'lucide-history',
                  onClick: () =>
                    router.push({
                      query: { ...route.query, tab: 'history', kind: 'user', target: member.user },
                    }),
                },
              ]"
            />
          </template>
        </ModerationRow>
        <div
          v-if="expanded === member.user"
          class="mb-3 ml-10 rounded-5 bg-surface-gray-1 p-4"
          data-testid="trust-requirements"
        >
          <p class="text-p-sm text-ink-gray-7">{{ levelDescriptions[member.level] }}</p>
          <p v-if="member.pending" class="mt-2 text-p-sm text-ink-gray-6">
            The background job has not reached this member yet. Their level is worked out the next
            time they post.
          </p>
          <ul
            v-else-if="nextSteps(member.level, member.requirements).length"
            class="mt-3 space-y-1.5"
          >
            <li
              v-for="step in nextSteps(member.level, member.requirements)"
              :key="step.label"
              class="flex items-start gap-2 text-p-sm text-ink-gray-7"
            >
              <span
                :class="[
                  step.met
                    ? 'lucide-circle-check text-ink-gray-7'
                    : 'lucide-circle text-ink-gray-4',
                  'mt-0.5 size-4 shrink-0',
                ]"
                aria-hidden="true"
              />
              <span>{{ step.met ? 'Met' : 'Not met' }}: {{ step.label }}</span>
            </li>
          </ul>
          <p v-else class="mt-2 text-p-sm text-ink-gray-6">This is the highest level.</p>
        </div>
      </template>
    </div>
  </template>
  <ModerationEmpty
    v-else-if="!loading && !error"
    icon="lucide-award"
    :title="filter ? `No ${filter} members` : 'No members yet'"
    description="Community staff are not listed: they have no level."
  />
  <p v-if="loading" role="status" class="mt-4 text-base text-ink-gray-5">Loading…</p>
  <ModerationPager
    :previous="start > 0"
    :next="more"
    @previous="start -= PAGE"
    @next="start += PAGE"
  />
  <TrustLevelDialog
    v-if="target"
    :key="`${target.user}-${mode}`"
    v-model:open="dialogOpen"
    :member="target"
    :community="communityId"
    :mode="mode"
    @saved="load"
  />
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Avatar, Badge, Button, Dropdown, ErrorMessage, TabButtons, call } from 'frappe-ui'
import ModerationEmpty from '@/components/moderation/ModerationEmpty.vue'
import ModerationPager from '@/components/moderation/ModerationPager.vue'
import ModerationRow from '@/components/moderation/ModerationRow.vue'
import TrustLevelDialog from '@/components/TrustLevelDialog.vue'
import { useCommunity } from '@/data/communities'
import { useSessionUser, useUser } from '@/data/users'
import { levelDescriptions, nextSteps, summary, type MemberLevel } from '@/data/trustLevels'
import { canManageCommunity } from '@/utils/permissions'
import { extractServerMessage } from '@/utils'

const PAGE = 50
const props = defineProps<{ communityId: string }>()
const route = useRoute()
const router = useRouter()
const community = useCommunity(() => props.communityId)
const canManage = computed(() => canManageCommunity(community.value, useSessionUser()))
const filters = [
  { label: 'All', value: '' },
  { label: 'New', value: 'New' },
  { label: 'Member', value: 'Member' },
  { label: 'Trusted', value: 'Trusted' },
]
const filter = ref('')
const start = ref(0)
const members = ref<MemberLevel[]>([])
const enabled = ref(true)
const more = ref(false)
const loading = ref(false)
const error = ref<unknown>(null)
const expanded = ref('')
const target = ref<MemberLevel | null>(null)
const mode = ref<'level' | 'lock'>('level')
const dialogOpen = ref(false)

function openDialog(member: MemberLevel, nextMode: 'level' | 'lock') {
  target.value = member
  mode.value = nextMode
  dialogOpen.value = true
}

let request = 0
async function load() {
  const current = ++request
  loading.value = true
  error.value = null
  try {
    const result = await call<{ enabled: number; members: MemberLevel[]; more: boolean }>(
      'gameplan.trust_levels.member_levels',
      { community: props.communityId, level: filter.value, start: start.value },
    )
    if (current !== request) return
    enabled.value = Boolean(result.enabled)
    members.value = result.members
    more.value = result.more
  } catch (e) {
    if (current === request) error.value = e
  } finally {
    if (current === request) loading.value = false
  }
}
watch([() => props.communityId, filter], () => {
  start.value = 0
  expanded.value = ''
})
watch([() => props.communityId, filter, start], load, { immediate: true })
</script>
