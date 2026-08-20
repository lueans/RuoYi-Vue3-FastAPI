<template>
  <div v-if="onlineUsers.length > 0" class="collaborators">
    <el-popover
      v-model:visible="popoverVisible"
      placement="bottom-start"
      trigger="click"
      :width="288"
      :popper-class="props.dark ? 'mindmap-presence-popper is-dark' : 'mindmap-presence-popper'"
      @show="handlePopoverShow"
    >
      <template #reference>
        <button
          ref="triggerRef"
          type="button"
          class="presence-trigger"
          :class="{ 'is-dark': props.dark }"
          :aria-label="`${onlineUsers.length} 位协作者在线，查看成员名单`"
          aria-haspopup="dialog"
          :aria-controls="panelId"
          :aria-expanded="popoverVisible"
          title="查看在线协作者"
        >
          <span class="avatar-stack" aria-hidden="true">
            <el-avatar
              v-for="user in displayUsers"
              :key="user.identity"
              :size="28"
              :src="user.avatar || undefined"
              :style="{ backgroundColor: user.color }"
            >
              {{ getMindmapPresenceInitial(user.name) }}
            </el-avatar>
            <el-avatar v-if="extraCount > 0" :size="28" class="extra-count">
              +{{ extraCount }}
            </el-avatar>
          </span>
          <span class="presence-label">{{ onlineUsers.length }} 人在线</span>
        </button>
      </template>

      <section
        ref="panelRef"
        :id="panelId"
        class="presence-panel"
        :class="{ 'is-dark': props.dark }"
        role="dialog"
        tabindex="-1"
        :aria-labelledby="`${panelId}-title`"
        @keydown.esc.stop.prevent="handlePopoverEscape"
      >
        <header class="presence-panel-header">
          <div>
            <strong :id="`${panelId}-title`">正在协作</strong>
            <span aria-live="polite">{{ onlineUsers.length }} 位成员在线</span>
          </div>
          <span class="live-indicator" aria-hidden="true" />
        </header>
        <ul class="presence-list" aria-label="在线协作者名单">
          <li v-for="user in panelUsers" :key="user.identity" class="presence-member">
            <el-avatar
              :size="34"
              :src="user.avatar || undefined"
              :style="{ backgroundColor: user.color }"
              aria-hidden="true"
            >
              {{ getMindmapPresenceInitial(user.name) }}
            </el-avatar>
            <span class="member-name" :title="user.name">{{ user.name }}</span>
            <span class="member-status"><i aria-hidden="true" />在线</span>
          </li>
        </ul>
        <p v-if="panelOverflowCount > 0" class="presence-overflow-note">
          另有 {{ panelOverflowCount }} 位在线成员未展开显示
        </p>
      </section>
    </el-popover>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, useId, watch } from 'vue'
import {
  getMindmapPresenceInitial,
  MINDMAP_PRESENCE_PANEL_LIMIT,
  normalizeMindmapPresenceDisplayLimit,
  normalizeMindmapPresenceUsers,
} from '@/utils/mindmap-presence'

const props = defineProps({
  collaborators: { type: Array, default: () => [] },
  maxDisplay: { type: Number, default: 5 },
  dark: { type: Boolean, default: false },
})

const panelId = `mindmap-presence-${useId().replace(/[^\w-]/g, '')}`
const popoverVisible = ref(false)
const triggerRef = ref(null)
const panelRef = ref(null)
const onlineUsers = computed(() => normalizeMindmapPresenceUsers(props.collaborators))
const displayLimit = computed(() => normalizeMindmapPresenceDisplayLimit(props.maxDisplay))
const displayUsers = computed(() => onlineUsers.value.slice(0, displayLimit.value))
const extraCount = computed(() => Math.max(0, onlineUsers.value.length - displayUsers.value.length))
const panelUsers = computed(() => onlineUsers.value.slice(0, MINDMAP_PRESENCE_PANEL_LIMIT))
const panelOverflowCount = computed(() => Math.max(0, onlineUsers.value.length - panelUsers.value.length))

watch(() => onlineUsers.value.length, count => {
  if (count === 0) popoverVisible.value = false
})

function handlePopoverShow() {
  nextTick(() => panelRef.value?.focus?.())
}

function handlePopoverEscape() {
  popoverVisible.value = false
  nextTick(() => triggerRef.value?.focus?.())
}
</script>

<style scoped>
.collaborators {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.presence-trigger {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 32px;
  padding: 2px 8px 2px 4px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: #4d5562;
  cursor: pointer;
  font: inherit;
  transition: background 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;

  &:hover,
  &[aria-expanded='true'] {
    border-color: #dbe4f3;
    background: #f5f8fc;
  }

  &:focus-visible {
    outline: none;
    box-shadow: 0 0 0 3px rgba(51, 112, 255, 0.16);
  }

  &.is-dark {
    color: #d2d7df;

    &:hover,
    &[aria-expanded='true'] {
      border-color: #465064;
      background: #252b36;
    }
  }
}

.avatar-stack {
  display: inline-flex;
  align-items: center;
  padding-left: 6px;

  :deep(.el-avatar) {
    margin-left: -6px;
    border: 2px solid #fff;
    color: #fff;
    font-size: 11px;
    font-weight: 650;
    box-shadow: 0 1px 4px rgba(23, 35, 61, 0.16);
  }
}

.presence-trigger.is-dark .avatar-stack :deep(.el-avatar) {
  border-color: #1c212b;
}

.avatar-stack :deep(.extra-count) {
  background: #e9edf3 !important;
  color: #596273;
  font-size: 10px;
}

.presence-trigger.is-dark .avatar-stack :deep(.extra-count) {
  background: #394252 !important;
  color: #e4e8ef;
}

.presence-label {
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.presence-panel {
  color: #20242c;

  &:focus {
    outline: none;
  }
}

.presence-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 2px 10px;
  border-bottom: 1px solid #edf0f4;

  > div {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  strong {
    font-size: 14px;
    line-height: 20px;
  }

  span:not(.live-indicator) {
    color: #7b8391;
    font-size: 12px;
  }
}

.live-indicator {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #2fb66d;
  box-shadow: 0 0 0 4px rgba(47, 182, 109, 0.13);
}

.presence-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 320px;
  margin: 8px 0 0;
  padding: 0;
  overflow-y: auto;
  list-style: none;
  overscroll-behavior: contain;
}

.presence-member {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 44px;
  padding: 5px 6px;
  border-radius: 9px;

  &:hover {
    background: #f6f8fb;
  }

  :deep(.el-avatar) {
    color: #fff;
    font-size: 12px;
    font-weight: 650;
  }
}

.member-name {
  min-width: 0;
  overflow: hidden;
  color: #303641;
  font-size: 13px;
  font-weight: 550;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #6f7785;
  font-size: 11px;

  i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #2fb66d;
  }
}

.presence-overflow-note {
  margin: 8px 2px 0;
  color: #7b8391;
  font-size: 11px;
  line-height: 18px;
}

.presence-panel.is-dark {
  color: #edf0f5;

  .presence-panel-header {
    border-color: #3a4351;

    span:not(.live-indicator) {
      color: #aeb6c3;
    }
  }

  .presence-member:hover {
    background: #2b3340;
  }

  .member-name {
    color: #edf0f5;
  }

  .member-status,
  .presence-overflow-note {
    color: #aeb6c3;
  }
}

:global(.mindmap-presence-popper.is-dark) {
  border-color: #3a4351 !important;
  background: #202631 !important;
  box-shadow: 0 12px 30px rgba(0, 0, 0, 0.32) !important;
}

:global(.mindmap-presence-popper.is-dark .el-popper__arrow::before) {
  border-color: #3a4351 !important;
  background: #202631 !important;
}

@media (max-width: 1180px) {
  .presence-label {
    display: none;
  }

  .presence-trigger {
    padding-right: 4px;
  }
}
</style>
