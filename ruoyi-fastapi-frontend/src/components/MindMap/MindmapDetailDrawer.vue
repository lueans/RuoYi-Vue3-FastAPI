<template>
  <el-drawer
    :model-value="modelValue"
    class="mindmap-detail-drawer"
    size="min(860px, calc(100vw - 72px))"
    direction="rtl"
    append-to-body
    destroy-on-close
    aria-label="脑图详情"
    :show-close="false"
    :close-on-click-modal="!busy"
    :close-on-press-escape="!busy"
    @update:model-value="value => emit('update:modelValue', value)"
  >
    <template #header>
      <div class="mindmap-detail-header">
        <div class="mindmap-detail-heading">
          <span class="mindmap-detail-icon" aria-hidden="true">
            <el-icon><Share v-if="scope === 'shared'" /><Files v-else /></el-icon>
          </span>
          <div class="mindmap-detail-title-block">
            <div class="mindmap-detail-title-row">
              <h2 :title="item?.name || ''">{{ item?.name || '未命名脑图' }}</h2>
              <span class="mindmap-detail-status" :class="{ 'is-archived': isArchived }">
                {{ statusText }}
              </span>
              <span v-if="scope === 'shared'" class="mindmap-detail-permission">
                {{ canEdit ? '可编辑' : '只读' }}
              </span>
            </div>
            <p>{{ folderName }} · {{ normalizedNodeCount }} 个节点 · 更新于 {{ timeText || '未知时间' }}</p>
          </div>
        </div>
        <div class="mindmap-detail-header-actions">
          <el-button
            v-if="canEdit"
            link
            :disabled="busy"
            aria-label="编辑脑图信息"
            @click="emit('metadata', item)"
          >
            <el-icon><EditPen /></el-icon>
            <span class="mindmap-detail-edit-label">编辑信息</span>
          </el-button>
          <button
            type="button"
            class="mindmap-detail-close"
            :disabled="busy"
            aria-label="关闭脑图详情"
            @click="emit('update:modelValue', false)"
          >
            <el-icon><Close /></el-icon>
          </button>
        </div>
      </div>
    </template>

    <div v-if="item" class="mindmap-detail-content">
      <div class="mindmap-detail-tabs" aria-label="当前详情分区">
        <span aria-current="page">基本信息</span>
      </div>

      <section class="mindmap-detail-section" aria-labelledby="mindmap-detail-document-title">
        <div class="mindmap-detail-section-title">
          <div>
            <h3 id="mindmap-detail-document-title">在线脑图</h3>
            <p>从管理上下文进入画布，目录、权限和返回位置都会保持不变。</p>
          </div>
        </div>
        <div class="mindmap-online-document">
          <span class="mindmap-online-document-icon" aria-hidden="true">
            <el-icon><Files /></el-icon>
          </span>
          <div class="mindmap-online-document-copy">
            <strong>{{ item.name || '未命名脑图' }}</strong>
            <span>{{ folderName }} · {{ normalizedNodeCount }} 个节点 · {{ normalizedVersionCount }} 个版本</span>
          </div>
          <span class="mindmap-online-document-state">在线可用</span>
          <el-button
            :type="canEdit ? 'primary' : 'default'"
            :disabled="busy"
            @click="emit(canEdit ? 'edit' : 'view', item)"
          >{{ canEdit ? '编辑脑图' : '只读查看' }}</el-button>
        </div>
      </section>

      <section class="mindmap-detail-section" aria-labelledby="mindmap-detail-overview-title">
        <div class="mindmap-detail-section-title">
          <div>
            <h3 id="mindmap-detail-overview-title">内容概览</h3>
            <p>快速确认脑图规模、版本和内容修订状态。</p>
          </div>
        </div>
        <dl class="mindmap-detail-stats">
          <div>
            <dt>节点数</dt>
            <dd>{{ normalizedNodeCount }}</dd>
          </div>
          <div>
            <dt>版本数</dt>
            <dd>{{ normalizedVersionCount }}</dd>
          </div>
          <div>
            <dt>内容修订</dt>
            <dd>v{{ normalizedContentRevision }}</dd>
          </div>
          <div>
            <dt>内容状态</dt>
            <dd>{{ contentStateText }}</dd>
          </div>
        </dl>
      </section>

      <section class="mindmap-detail-section" aria-labelledby="mindmap-detail-info-title">
        <div class="mindmap-detail-section-title">
          <div>
            <h3 id="mindmap-detail-info-title">文件信息</h3>
            <p>{{ item.description || '暂无说明，可通过“编辑信息”补充目标、范围和使用方式。' }}</p>
          </div>
        </div>
        <dl class="mindmap-detail-info-list">
          <div>
            <dt>所属目录</dt>
            <dd>{{ folderName }}</dd>
          </div>
          <div>
            <dt>所有者</dt>
            <dd>{{ item.ownerName || (scope === 'shared' ? '未知所有者' : '我') }}</dd>
          </div>
          <div>
            <dt>创建时间</dt>
            <dd>{{ createTimeText || '未知时间' }}</dd>
          </div>
          <div>
            <dt>更新时间</dt>
            <dd>{{ timeText || '未知时间' }}</dd>
          </div>
          <div>
            <dt>布局</dt>
            <dd>{{ layoutText }}</dd>
          </div>
          <div>
            <dt>访问方式</dt>
            <dd>{{ accessText }}</dd>
          </div>
        </dl>
      </section>

      <section v-if="item.coverImage" class="mindmap-detail-section" aria-labelledby="mindmap-detail-preview-title">
        <div class="mindmap-detail-section-title">
          <div>
            <h3 id="mindmap-detail-preview-title">脑图封面</h3>
            <p>封面来自当前脑图文件，可用于打开前快速识别内容。</p>
          </div>
        </div>
        <img class="mindmap-detail-cover" :src="item.coverImage" alt="脑图封面预览" />
      </section>
    </div>

    <template #footer>
      <div class="mindmap-detail-footer">
        <span>打开后进入沉浸式脑图画布</span>
        <div :class="{ 'is-single-action': !canEdit }">
          <el-button :disabled="busy" @click="emit('view', item)">
            <el-icon><View /></el-icon>
            只读查看
          </el-button>
          <el-button v-if="canEdit" type="primary" :disabled="busy" @click="emit('edit', item)">
            <el-icon><Edit /></el-icon>
            继续编辑
          </el-button>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed } from 'vue'
import { Close, Edit, EditPen, Files, Share, View } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  item: { type: Object, default: null },
  scope: { type: String, default: 'owned' },
  folderName: { type: String, default: '根目录' },
  canEdit: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  timeText: { type: String, default: '' },
  createTimeText: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'view', 'edit', 'metadata'])

const isArchived = computed(() => Number(props.item?.status) === 1)
const normalizedNodeCount = computed(() => Math.max(0, Number(props.item?.nodeCount) || 0))
const normalizedVersionCount = computed(() => Math.max(0, Number(props.item?.versionCount) || 0))
const normalizedContentRevision = computed(() => Math.max(1, Number(props.item?.contentRevision) || 1))
const statusText = computed(() => isArchived.value ? '已归档' : '正常')
const contentStateText = computed(() => ({
  ready: '可用',
  migration_failed: '迁移保护',
  integrity_failed: '完整性保护',
  load_failed: '加载保护',
})[props.item?.contentState] || '可用')
const accessText = computed(() => ({
  owned: '我的脑图',
  shared: props.canEdit ? '共享给我 · 可编辑' : '共享给我 · 只读',
  trash: '回收站',
})[props.scope] || '我的脑图')
const layoutText = computed(() => {
  const value = String(props.item?.layout || '').trim()
  return value || '默认布局'
})
</script>

<style lang="scss">
.mindmap-detail-drawer {
  --mindmap-detail-border: #e8eaf0;

  .el-drawer__header {
    min-height: 72px;
    margin: 0;
    padding: 0 22px;
    border-bottom: 1px solid var(--mindmap-detail-border);
  }

  .el-drawer__body {
    padding: 0;
    overflow: auto;
    overscroll-behavior: contain;
  }

  .el-drawer__footer {
    padding: 0;
    border-top: 1px solid var(--mindmap-detail-border);
  }
}

.mindmap-detail-header {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}

.mindmap-detail-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 12px;
}

.mindmap-detail-icon {
  display: grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  border-radius: 10px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 19px;
}

.mindmap-detail-title-block {
  min-width: 0;

  p {
    margin: 4px 0 0;
    overflow: hidden;
    color: var(--el-text-color-secondary);
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.mindmap-detail-title-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;

  h2 {
    max-width: min(420px, 42vw);
    margin: 0;
    overflow: hidden;
    color: var(--el-text-color-primary);
    font-size: 17px;
    font-weight: 650;
    line-height: 1.35;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.mindmap-detail-status,
.mindmap-detail-permission {
  display: inline-flex;
  min-height: 22px;
  flex: none;
  align-items: center;
  padding: 0 8px;
  border-radius: 999px;
  background: #edf8f1;
  color: #23864b;
  font-size: 11px;
  font-weight: 600;
}

.mindmap-detail-status.is-archived {
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
}

.mindmap-detail-permission {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
}

.mindmap-detail-header-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 12px;
}

.mindmap-detail-close {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--el-text-color-regular);
  cursor: pointer;
  font-size: 18px;

  &:hover,
  &:focus-visible {
    background: var(--el-fill-color-light);
    color: var(--el-text-color-primary);
    outline: none;
  }
}

.mindmap-detail-tabs {
  height: 50px;
  padding: 0 24px;
  border-bottom: 1px solid var(--mindmap-detail-border);

  span {
    position: relative;
    height: 100%;
    padding: 0 4px;
    color: var(--el-color-primary);
    display: inline-flex;
    align-items: center;
    font-size: 14px;
    font-weight: 600;

    &::after {
      position: absolute;
      right: 0;
      bottom: 0;
      left: 0;
      height: 2px;
      border-radius: 999px 999px 0 0;
      background: var(--el-color-primary);
      content: '';
    }
  }
}

.mindmap-detail-content {
  padding-bottom: 28px;
}

.mindmap-detail-section {
  padding: 24px;
  border-bottom: 1px solid var(--mindmap-detail-border);
}

.mindmap-detail-section-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;

  h3 {
    margin: 0;
    color: var(--el-text-color-primary);
    font-size: 15px;
    font-weight: 650;
  }

  p {
    max-width: 640px;
    margin: 6px 0 0;
    color: var(--el-text-color-secondary);
    font-size: 13px;
    line-height: 1.65;
  }
}

.mindmap-online-document {
  display: flex;
  min-height: 76px;
  align-items: center;
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid var(--mindmap-detail-border);
  border-radius: 10px;
  background: #fbfcff;
}

.mindmap-online-document-icon {
  display: grid;
  width: 40px;
  height: 40px;
  flex: none;
  place-items: center;
  border-radius: 9px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 19px;
}

.mindmap-online-document-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 5px;

  strong,
  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: var(--el-text-color-primary);
    font-size: 14px;
  }

  span {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

.mindmap-online-document-state {
  display: inline-flex;
  min-height: 22px;
  flex: none;
  align-items: center;
  padding: 0 8px;
  border-radius: 999px;
  background: #edf8f1;
  color: #23864b;
  font-size: 11px;
  font-weight: 600;
}

.mindmap-detail-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin: 0;
  overflow: hidden;
  border: 1px solid var(--mindmap-detail-border);
  border-radius: 10px;

  > div {
    min-width: 0;
    padding: 18px 20px;
    border-right: 1px solid var(--mindmap-detail-border);

    &:last-child {
      border-right: 0;
    }
  }

  dt {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }

  dd {
    margin: 8px 0 0;
    overflow: hidden;
    color: var(--el-text-color-primary);
    font-size: 20px;
    font-weight: 650;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.mindmap-detail-info-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 48px;
  margin: 0;

  > div {
    display: grid;
    grid-template-columns: 92px minmax(0, 1fr);
    align-items: baseline;
    padding: 13px 0;
    border-bottom: 1px solid var(--mindmap-detail-border);
  }

  dt {
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  dd {
    margin: 0;
    overflow: hidden;
    color: var(--el-text-color-primary);
    font-size: 13px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.mindmap-detail-cover {
  display: block;
  width: 100%;
  max-height: 360px;
  object-fit: contain;
  border: 1px solid var(--mindmap-detail-border);
  border-radius: 10px;
  background: #fff;
}

.mindmap-detail-footer {
  display: flex;
  min-height: 66px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 22px;

  > span {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

@media (max-width: 760px) {
  .mindmap-detail-drawer {
    width: 100vw !important;

    .el-drawer__header {
      min-height: 76px;
      padding: 0 14px;
    }
  }

  .mindmap-detail-header {
    gap: 8px;
  }

  .mindmap-detail-footer > span,
  .mindmap-online-document-state {
    display: none;
  }

  .mindmap-detail-heading {
    flex: 1;
    gap: 10px;
  }

  .mindmap-detail-icon {
    width: 34px;
    height: 34px;
    border-radius: 9px;
  }

  .mindmap-detail-title-row {
    flex-wrap: wrap;
    gap: 4px 6px;
  }

  .mindmap-detail-title-block p {
    max-width: calc(100vw - 128px);
  }

  .mindmap-detail-header-actions {
    gap: 4px;

    .el-button {
      width: 34px;
      height: 34px;
      margin: 0;
      padding: 0;
      border-radius: 8px;
    }
  }

  .mindmap-detail-edit-label {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }

  .mindmap-online-document {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .mindmap-online-document-copy {
    width: calc(100% - 54px);
    flex: none;
  }

  .mindmap-online-document .el-button {
    width: 100%;
  }

  .mindmap-detail-title-row h2 {
    max-width: calc(100vw - 200px);
  }

  .mindmap-detail-stats,
  .mindmap-detail-info-list {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .mindmap-detail-stats > div:nth-child(2) {
    border-right: 0;
  }

  .mindmap-detail-stats > div:nth-child(-n + 2) {
    border-bottom: 1px solid var(--mindmap-detail-border);
  }

  .mindmap-detail-section {
    padding: 20px 18px;
  }

  .mindmap-detail-info-list {
    gap: 0;
  }

  .mindmap-detail-footer {
    min-height: 72px;
    justify-content: flex-end;
    padding: 10px 14px max(10px, env(safe-area-inset-bottom));

    > div {
      display: grid;
      width: 100%;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;

      &.is-single-action {
        grid-template-columns: minmax(0, 1fr);
      }
    }

    .el-button {
      width: 100%;
      margin: 0;
    }
  }
}

@media (max-width: 420px) {
  .mindmap-detail-status,
  .mindmap-detail-permission {
    min-height: 20px;
    padding: 0 6px;
  }

  .mindmap-detail-title-row h2 {
    max-width: calc(100vw - 154px);
    flex-basis: calc(100vw - 154px);
  }

  .mindmap-detail-stats,
  .mindmap-detail-info-list {
    grid-template-columns: minmax(0, 1fr);
  }

  .mindmap-detail-stats > div {
    border-right: 0;
    border-bottom: 1px solid var(--mindmap-detail-border);

    &:last-child { border-bottom: 0; }
  }

  .mindmap-detail-info-list > div {
    grid-template-columns: 84px minmax(0, 1fr);
  }
}
</style>
