<template>
  <el-dialog v-model="dialogVisible" title="标签" width="520px" :close-on-click-modal="false"
    @open="onOpen" @close="onClose" append-to-body>
    <!-- 从标签库选择 -->
    <div class="tag-library-section">
      <div class="sectionTitle">从标签库选择</div>
      <div class="tag-search-row">
        <el-select
          v-model="selectedLibraryTag"
          filterable
          remote
          reserve-keyword
          clearable
          :remote-method="searchLibraryTags"
          :loading="libraryLoading"
          placeholder="搜索标签库..."
          style="flex: 1"
          size="small"
          @change="onLibraryTagSelect"
        >
          <el-option
            v-for="tag in librarySuggestions"
            :key="tag.id"
            :label="`${tag.name} (${tag.tagKey})`"
            :value="tag.id"
          >
            <div class="libraryOption">
              <span class="tagDot" :style="{ backgroundColor: tag.style?.fill || '#409eff' }"></span>
              <span class="optionName">{{ tag.name }}</span>
              <span class="optionKey">{{ tag.tagKey }}</span>
              <el-tag v-if="tag.ownerId === 0" size="small" type="success" class="optionBadge">全局</el-tag>
            </div>
          </el-option>
        </el-select>
      </div>
    </div>

    <!-- 手动输入 -->
    <div class="sectionTitle" style="margin-top: 12px">自定义标签</div>
    <div class="tag-input-row">
      <el-input v-model="tagInput" placeholder="输入标签后按 Enter 添加" size="small"
        @keydown.enter="addTag" ref="inputRef" />
      <el-button size="small" type="primary" @click="addTag" :disabled="!tagInput.trim()">添加</el-button>
    </div>

    <!-- 当前标签列表 -->
    <div class="tag-list" v-if="tagArr.length > 0">
      <el-tag v-for="(tag, index) in tagArr" :key="index" closable
        :color="getTagColor(tag)" effect="dark" @close="removeTag(index)"
        style="margin: 4px">
        <template v-if="typeof tag === 'object' && tag.tagId">
          📌 {{ tag.text }}
        </template>
        <template v-else>
          {{ typeof tag === 'object' ? tag.text : tag }}
        </template>
      </el-tag>
    </div>
    <div v-else class="empty-tip">暂无标签</div>

    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" @click="confirm">确定</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import bus from './useEventBus'
import { getTagSuggestions } from '@/api/mindmap/tag'
import { ElMessage } from 'element-plus'

const dialogVisible = ref(false)
const tagInput = ref('')
const tagArr = ref([])
const activeNodes = ref([])
const inputRef = ref(null)

// 标签库
const selectedLibraryTag = ref(null)
const librarySuggestions = ref([])
const libraryLoading = ref(false)
let searchTimer = null

const tagColors = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#00bcd4', '#9c27b0', '#ff5722']

function getTagColor(tag) {
  if (typeof tag === 'object' && tag.style?.fill) return tag.style.fill
  const text = typeof tag === 'object' ? tag.text : tag
  let hash = 0
  for (let i = 0; i < text.length; i++) {
    hash = text.charCodeAt(i) + ((hash << 5) - hash)
  }
  return tagColors[Math.abs(hash) % tagColors.length]
}

function handleShow() {
  const node = activeNodes.value[0]
  if (!node) return
  const tags = node.getData('tag') || []
  tagArr.value = [...tags]
  dialogVisible.value = true
}

function onOpen() {
  bus.emit('startTextEdit')
  nextTick(() => inputRef.value?.focus())
}

function onClose() {
  bus.emit('endTextEdit')
}

// ── 标签库搜索 ──
function searchLibraryTags(keyword) {
  clearTimeout(searchTimer)
  if (!keyword || keyword.length < 1) {
    librarySuggestions.value = []
    return
  }
  searchTimer = setTimeout(async () => {
    libraryLoading.value = true
    try {
      const res = await getTagSuggestions(keyword)
      librarySuggestions.value = res.data || []
    } catch (e) {
      console.error('搜索标签库失败:', e)
      librarySuggestions.value = []
    } finally {
      libraryLoading.value = false
    }
  }, 300)
}

function onLibraryTagSelect(tagId) {
  if (!tagId) return
  const libTag = librarySuggestions.value.find(t => t.id === tagId)
  if (!libTag) return

  // 检查是否已存在（通过 tagId 或 text 去重）
  const exists = tagArr.value.some(t => {
    if (typeof t === 'object' && t.tagId === tagId) return true
    const text = typeof t === 'object' ? t.text : t
    return text === libTag.name
  })
  if (exists) {
    ElMessage.warning('该标签已存在')
    selectedLibraryTag.value = null
    return
  }
  if (tagArr.value.length >= 10) {
    ElMessage.warning('最多添加 10 个标签')
    selectedLibraryTag.value = null
    return
  }

  // 以对象格式添加，包含 tagId 引用
  // simple-mind-map 标签格式：placement/align 是顶层属性，fill/color/fontSize 在 style 内
  const libStyle = libTag.style || {}
  const { placement, align, ...innerStyle } = libStyle
  tagArr.value.push({
    tagId: libTag.id,
    text: libTag.name,
    style: Object.keys(innerStyle).length > 0 ? innerStyle : undefined,
    placement: placement || undefined,
    align: align || undefined,
  })
  selectedLibraryTag.value = null
  librarySuggestions.value = []
}

// ── 手动标签 ──
function addTag() {
  const text = tagInput.value.trim()
  if (!text) return
  if (tagArr.value.length >= 10) {
    ElMessage.warning('最多添加 10 个标签')
    return
  }
  tagArr.value.push(text)
  tagInput.value = ''
}

function removeTag(index) {
  tagArr.value.splice(index, 1)
}

function confirm() {
  activeNodes.value.forEach(node => {
    node.setTag([...tagArr.value])
  })
  dialogVisible.value = false
}

function onNodeActive(_, list) {
  activeNodes.value = list ? [...list] : []
}

onMounted(() => {
  bus.on('node_active', onNodeActive)
  bus.on('showNodeTag', handleShow)
})
onBeforeUnmount(() => {
  bus.off('node_active', onNodeActive)
  bus.off('showNodeTag', handleShow)
  clearTimeout(searchTimer)
})
</script>

<style scoped lang="scss">
.sectionTitle {
  font-size: 13px;
  font-weight: 500;
  color: #606266;
  margin-bottom: 8px;
}
.tag-library-section {
  padding-bottom: 12px;
  border-bottom: 1px solid #ebeef5;
}
.tag-search-row { display: flex; gap: 8px; }
.tag-input-row { display: flex; gap: 8px; margin-bottom: 12px; }
.tag-list { display: flex; flex-wrap: wrap; min-height: 40px; }
.empty-tip { text-align: center; color: #999; padding: 20px 0; }
</style>

<!-- el-option slot 内容 teleport 到 body，需要 non-scoped 样式 -->
<style lang="scss">
.libraryOption {
  display: flex;
  align-items: center;
  gap: 8px;

  .tagDot {
    width: 10px;
    height: 10px;
    border-radius: 2px;
    flex-shrink: 0;
  }

  .optionName {
    font-weight: 500;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .optionKey {
    font-size: 11px;
    color: #999;
  }

  .optionBadge {
    margin-left: 4px;
  }
}
</style>
