<template>
  <article
    class="mindmap-file-card"
    :class="{ 'is-selected': selected, 'is-archived': isArchived }"
    :style="cardAccentStyle"
    :aria-label="`${item.name || '未命名脑图'}${isArchived ? '，已归档' : ''}`"
  >
    <div class="card-cover">
      <button
        v-if="scope !== 'trash'"
        type="button"
        class="cover-open-button"
        :aria-label="`打开脑图：${item.name || '未命名脑图'}`"
        :disabled="busy"
        @click="emit('open', item)"
      >
        <img
          v-if="showCoverImage"
          :src="item.coverImage"
          alt=""
          loading="lazy"
          @error="coverFailed = true"
        />
        <span v-else class="cover-placeholder" aria-hidden="true">
          <span class="root-node"></span>
          <span class="branch branch-one"></span>
          <span class="branch branch-two"></span>
          <span class="branch branch-three"></span>
          <span class="leaf leaf-one"></span>
          <span class="leaf leaf-two"></span>
          <span class="leaf leaf-three"></span>
        </span>
      </button>
      <div v-else class="cover-open-button is-static" aria-hidden="true">
        <span class="cover-placeholder">
          <span class="root-node"></span>
          <span class="branch branch-one"></span>
          <span class="branch branch-two"></span>
          <span class="branch branch-three"></span>
          <span class="leaf leaf-one"></span>
          <span class="leaf leaf-two"></span>
          <span class="leaf leaf-three"></span>
        </span>
      </div>

      <el-checkbox
        v-if="selectable"
        class="card-selector"
        :model-value="selected"
        :disabled="busy"
        :aria-label="`选择脑图：${item.name || '未命名脑图'}`"
        @change="value => emit('selection-change', Boolean(value))"
      />

      <div class="cover-badges" aria-label="脑图状态">
        <span v-if="scope === 'shared'" class="status-badge is-shared">共享</span>
        <span v-if="isArchived" class="status-badge is-archived">已归档</span>
        <span v-if="item.contentState === 'migration_failed'" class="status-badge is-warning">迁移保护</span>
      </div>
    </div>

    <div class="card-content">
      <div class="card-heading-row">
        <button
          v-if="scope !== 'trash'"
          type="button"
          class="card-title"
          :title="item.name"
          :disabled="busy"
          @click="emit('open', item)"
        >
          {{ item.name || '未命名脑图' }}
        </button>
        <h3 v-else class="card-title is-static" :title="item.name">{{ item.name || '未命名脑图' }}</h3>

        <el-dropdown
          v-if="scope !== 'trash'"
          trigger="click"
          placement="bottom-end"
          :disabled="busy"
          @command="command => emit('command', command, item)"
        >
          <button
            type="button"
            class="card-more-button"
            :disabled="busy"
            :aria-label="`更多操作：${item.name || '未命名脑图'}`"
          >
            <el-icon><MoreFilled /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item v-if="canEdit" command="metadata">
                <el-icon><Edit /></el-icon>编辑信息
              </el-dropdown-item>
              <el-dropdown-item command="copy" :disabled="!canCreate">
                <el-icon><CopyDocument /></el-icon>复制
              </el-dropdown-item>
              <el-dropdown-item v-if="isOwner && canEditFiles" command="move">
                <el-icon><Rank /></el-icon>移动
              </el-dropdown-item>
              <el-dropdown-item v-if="isOwner && canEditFiles" command="status">
                <el-icon><RefreshLeft v-if="isArchived" /><Box v-else /></el-icon>
                {{ isArchived ? '恢复' : '归档' }}
              </el-dropdown-item>
              <el-dropdown-item v-if="isOwner && canRemoveFiles" command="delete" divided>
                <el-icon><Delete /></el-icon><span class="danger-text">删除</span>
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>

      <p class="card-description" :title="item.description || ''">
        {{ item.description || '暂无说明，打开脑图继续完善内容。' }}
      </p>

      <div v-if="scope === 'shared'" class="shared-context">
        <span>{{ item.ownerName || '未知所有者' }}</span>
        <span class="permission-pill" :class="{ 'can-edit': canEdit }">{{ canEdit ? '可编辑' : '只读' }}</span>
      </div>

      <dl class="card-stats">
        <div>
          <dt>节点</dt>
          <dd>{{ normalizedNodeCount }}</dd>
        </div>
        <div>
          <dt>版本</dt>
          <dd>{{ normalizedVersionCount }}</dd>
        </div>
        <div class="updated-stat">
          <dt>{{ scope === 'trash' ? '删除记录' : '最近更新' }}</dt>
          <dd :title="timeText">{{ timeText || '时间未知' }}</dd>
        </div>
      </dl>

      <div class="card-actions">
        <template v-if="scope === 'trash'">
          <el-button
            v-if="canEditFiles"
            type="primary"
            plain
            size="small"
            :loading="busyOperation === `restore:${item.id}`"
            :disabled="busy"
            @click="emit('command', 'restore', item)"
          >恢复</el-button>
          <el-button
            v-if="canRemoveFiles"
            type="danger"
            plain
            size="small"
            :loading="busyOperation === `purge:${item.id}`"
            :disabled="busy"
            @click="emit('command', 'purge', item)"
          >永久删除</el-button>
        </template>
        <template v-else>
          <el-button plain size="small" :disabled="busy" @click="emit('view', item)">只读查看</el-button>
          <el-button v-if="canEdit" type="primary" size="small" :disabled="busy" @click="emit('edit', item)">继续编辑</el-button>
        </template>
      </div>
    </div>
  </article>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Box, CopyDocument, Delete, Edit, MoreFilled, Rank, RefreshLeft } from '@element-plus/icons-vue'

const props = defineProps({
  item: { type: Object, required: true },
  scope: { type: String, required: true },
  selected: { type: Boolean, default: false },
  selectable: { type: Boolean, default: true },
  busy: { type: Boolean, default: false },
  busyOperation: { type: String, default: '' },
  canEdit: { type: Boolean, default: false },
  canCreate: { type: Boolean, default: false },
  canEditFiles: { type: Boolean, default: false },
  canRemoveFiles: { type: Boolean, default: false },
  timeText: { type: String, default: '' },
})

const emit = defineEmits(['selection-change', 'open', 'view', 'edit', 'command'])
const coverFailed = ref(false)

watch(() => props.item.coverImage, () => {
  coverFailed.value = false
})

const showCoverImage = computed(() => Boolean(props.item.coverImage) && !coverFailed.value)
const isArchived = computed(() => Number(props.item.status) === 1)
const isOwner = computed(() => props.item.isOwner === true || props.item.accessType === 'owned')
const normalizedNodeCount = computed(() => Math.max(0, Number(props.item.nodeCount) || 0))
const normalizedVersionCount = computed(() => Math.max(0, Number(props.item.versionCount) || 0))
const cardAccentStyle = computed(() => {
  const id = Number(props.item.id)
  const hue = Number.isSafeInteger(id) && id > 0 ? (id * 47) % 360 : 214
  return { '--mindmap-card-hue': hue }
})
</script>

<style scoped lang="scss">
.mindmap-file-card {
  overflow: hidden;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 16px;
  background: var(--el-bg-color);
  box-shadow: 0 5px 18px rgba(15, 23, 42, 0.06);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;

  &:hover,
  &:focus-within {
    transform: translateY(-2px);
    border-color: color-mix(in srgb, hsl(var(--mindmap-card-hue) 72% 52%) 40%, var(--el-border-color));
    box-shadow: 0 12px 30px rgba(15, 23, 42, 0.11);
  }

  &.is-selected {
    border-color: var(--el-color-primary);
    box-shadow: 0 0 0 2px var(--el-color-primary-light-8), 0 12px 30px rgba(15, 23, 42, 0.1);
  }

  &.is-archived .card-cover {
    filter: saturate(0.62);
  }
}

.card-cover {
  position: relative;
  height: 150px;
  overflow: hidden;
  background:
    radial-gradient(circle at 84% 16%, hsla(var(--mindmap-card-hue), 78%, 72%, 0.52), transparent 32%),
    linear-gradient(145deg, hsla(var(--mindmap-card-hue), 82%, 96%, 1), hsla(var(--mindmap-card-hue), 70%, 88%, 0.72));
}

.cover-open-button {
  display: block;
  width: 100%;
  height: 100%;
  padding: 0;
  overflow: hidden;
  border: 0;
  background: transparent;
  cursor: pointer;

  &:focus-visible {
    outline: 3px solid var(--el-color-primary);
    outline-offset: -3px;
  }

  &:disabled {
    cursor: wait;
  }

  &.is-static {
    cursor: default;
  }

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }
}

.cover-placeholder {
  position: relative;
  display: block;
  width: 100%;
  height: 100%;
}

.root-node,
.leaf {
  position: absolute;
  height: 18px;
  border-radius: 7px;
  background: hsla(var(--mindmap-card-hue), 64%, 42%, 0.92);
  box-shadow: 0 4px 10px hsla(var(--mindmap-card-hue), 60%, 30%, 0.15);
}

.root-node {
  top: 66px;
  left: 21%;
  width: 28%;
}

.leaf {
  left: 67%;
  width: 21%;
  height: 14px;
  background: hsla(var(--mindmap-card-hue), 68%, 55%, 0.82);
}

.leaf-one { top: 32px; }
.leaf-two { top: 68px; }
.leaf-three { top: 104px; }

.branch {
  position: absolute;
  left: 47%;
  width: 22%;
  height: 2px;
  transform-origin: left center;
  border-radius: 999px;
  background: hsla(var(--mindmap-card-hue), 60%, 48%, 0.64);
}

.branch-one { top: 73px; transform: rotate(-24deg); }
.branch-two { top: 75px; }
.branch-three { top: 77px; transform: rotate(24deg); }

.card-selector {
  position: absolute;
  top: 12px;
  left: 12px;
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  margin: 0;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.1);

  :deep(.el-checkbox__label) {
    display: none;
  }
}

.cover-badges {
  position: absolute;
  top: 12px;
  right: 12px;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
}

.status-badge,
.permission-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 8px;
  border: 1px solid rgba(255, 255, 255, 0.72);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.9);
  color: var(--el-text-color-regular);
  font-size: 11px;
  font-weight: 600;
  backdrop-filter: blur(8px);

  &.is-shared,
  &.can-edit {
    color: var(--el-color-primary);
  }

  &.is-warning {
    color: var(--el-color-warning-dark-2);
  }
}

.card-content {
  padding: 15px 16px 14px;
}

.card-heading-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-title {
  min-width: 0;
  flex: 1;
  padding: 0;
  overflow: hidden;
  border: 0;
  background: transparent;
  color: var(--el-text-color-primary);
  cursor: pointer;
  font: inherit;
  font-size: 16px;
  font-weight: 650;
  line-height: 1.45;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;

  &:hover,
  &:focus-visible {
    color: var(--el-color-primary);
  }

  &:focus-visible {
    border-radius: 4px;
    outline: 2px solid var(--el-color-primary);
    outline-offset: 2px;
  }

  &.is-static {
    margin: 0;
    cursor: default;
  }
}

.card-more-button {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--el-text-color-secondary);
  cursor: pointer;

  &:hover,
  &:focus-visible {
    background: var(--el-fill-color-light);
    color: var(--el-color-primary);
  }

  &:focus-visible {
    outline: 2px solid var(--el-color-primary);
  }
}

.danger-text {
  color: var(--el-color-danger);
}

.card-description {
  height: 42px;
  margin: 8px 0 12px;
  overflow: hidden;
  color: var(--el-text-color-secondary);
  display: -webkit-box;
  font-size: 12px;
  line-height: 1.75;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.shared-context {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: -2px 0 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;

  > span:first-child {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .permission-pill {
    min-height: 21px;
    border-color: var(--el-border-color-lighter);
    background: var(--el-fill-color-extra-light);
    backdrop-filter: none;
  }
}

.card-stats {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  gap: 14px;
  margin: 0;
  padding: 11px 0;
  border-top: 1px solid var(--el-border-color-extra-light);
  border-bottom: 1px solid var(--el-border-color-extra-light);

  div {
    min-width: 0;
  }

  dt {
    margin-bottom: 3px;
    color: var(--el-text-color-placeholder);
    font-size: 10px;
    line-height: 1.4;
  }

  dd {
    margin: 0;
    overflow: hidden;
    color: var(--el-text-color-regular);
    font-size: 12px;
    font-weight: 600;
    line-height: 1.5;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .updated-stat {
    text-align: right;
  }
}

.card-actions {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
  min-height: 28px;
  margin-top: 12px;

  :deep(.el-button + .el-button) {
    margin-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .mindmap-file-card {
    transition: none;
  }
}
</style>
