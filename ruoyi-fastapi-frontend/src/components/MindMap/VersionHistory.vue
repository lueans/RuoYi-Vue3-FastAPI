<template>
  <Sidebar ref="sidebarRef" title="版本历史">
    <div class="versionHistoryContainer">
      <!-- 预览状态提示 -->
      <div v-if="isPreviewing" class="previewBanner">
        <el-icon><InfoFilled /></el-icon>
        <span>正在预览历史版本</span>
        <el-button type="primary" size="small" @click="exitPreview">
          退出预览
        </el-button>
      </div>

      <!-- 操作栏 -->
      <div class="actionBar" v-if="!isReadonly">
        <el-button type="primary" size="small" @click="handleSaveVersion">
          保存正式版本
        </el-button>
      </div>

      <!-- 版本类型切换 -->
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="正式版本" name="formal" />
        <el-tab-pane label="草稿版本" name="draft" />
      </el-tabs>

      <!-- 版本列表 -->
      <div class="versionList" v-loading="loading">
        <div v-if="versionList.length === 0 && !loading" class="emptyTip">
          暂无版本记录
        </div>
        <div
          v-for="item in versionList"
          :key="item.id"
          class="versionItem"
        >
          <div class="versionInfo">
            <div class="versionName">
              {{ item.name || `版本 ${item.versionNumber}` }}
            </div>
            <div class="versionMeta">
              <span>{{ parseTime(item.createdTime) }}</span>
              <span class="versionAuthor">{{ item.createdBy }}</span>
            </div>
          </div>
          <div class="versionActions">
            <el-button link type="primary" size="small" @click="handlePreview(item)">
              查看
            </el-button>
            <el-button link type="primary" size="small" @click="handleRestore(item)" v-if="!isReadonly">
              恢复
            </el-button>
            <el-button
              link type="danger" size="small"
              @click="handleDelete(item)"
              v-if="!isReadonly && item.versionType === 1"
            >
              删除
            </el-button>
          </div>
        </div>
      </div>

      <!-- 分页 -->
      <div class="paginationWrap" v-if="total > pageSize">
        <el-pagination
          small
          layout="prev, pager, next"
          :total="total"
          :page-size="pageSize"
          v-model:current-page="pageNum"
          @current-change="loadVersions"
        />
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { store, actions } from './useStore'
import { listVersions, getVersionDetail, restoreVersion, saveFormalVersion, deleteVersion } from '@/api/mindmap/version'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import bus from './useEventBus'

const props = defineProps({
  mindMap: { type: Object, default: null },
  mindmapId: { type: Number, default: null },
  yjsSync: { type: Object, default: null },
})

const emit = defineEmits(['yjs-reinit'])

const { proxy } = getCurrentInstance()
const sidebarRef = ref(null)
const loading = ref(false)
const versionList = ref([])
const total = ref(0)
const pageNum = ref(1)
const pageSize = ref(20)
const activeTab = ref('formal')
const isReadonly = computed(() => store.isReadonly)
const isPreviewing = ref(false)

// 预览前保存的状态，用于退出预览时恢复
let _prePreviewState = null

const parseTime = (time) => {
  return proxy.parseTime(time)
}

// 监听侧边栏开关
watch(() => store.activeSidebar, (val) => {
  if (val === 'versionHistory') {
    loadVersions()
    sidebarRef.value?.open()
  } else {
    // 侧边栏关闭时，如果正在预览则退出预览恢复数据
    if (isPreviewing.value) {
      exitPreview()
    }
    sidebarRef.value?.close()
  }
})

function onTabChange() {
  pageNum.value = 1
  loadVersions()
}

async function loadVersions() {
  if (!props.mindmapId) return
  loading.value = true
  try {
    const versionType = activeTab.value === 'formal' ? 1 : 0
    const res = await listVersions(props.mindmapId, {
      versionType,
      pageNum: pageNum.value,
      pageSize: pageSize.value,
    })
    versionList.value = res.rows || []
    total.value = res.total || 0
  } catch (e) {
    console.error('加载版本列表失败:', e)
  } finally {
    loading.value = false
  }
}

async function handleSaveVersion() {
  if (!props.mindmapId) return
  try {
    await ElMessageBox.prompt('请输入版本名称（可选）', '保存正式版本', {
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputPlaceholder: '版本名称',
    }).then(async ({ value }) => {
      await saveFormalVersion({
        mindmapId: props.mindmapId,
        name: value || undefined,
      })
      ElMessage.success('正式版本保存成功')
      loadVersions()
    }).catch(() => {})
  } catch (e) {
    console.error('保存版本失败:', e)
    ElMessage.error('保存版本失败')
  }
}

async function handlePreview(item) {
  if (!props.mindMap) return
  try {
    // 如果已经在预览中，先退出上一次预览
    if (isPreviewing.value) {
      exitPreview()
    }

    const res = await getVersionDetail(item.id)
    const versionData = res.data
    if (versionData?.nodeTree && props.mindMap) {
      // 保存当前实时状态，用于退出预览时恢复
      _prePreviewState = props.mindMap.getData(true)
      isPreviewing.value = true

      // 暂停 Yjs 同步，防止预览数据广播给协作者
      if (props.yjsSync) {
        props.yjsSync.pause()
      }

      // 以版本数据替换当前显示
      props.mindMap.setFullData({
        root: versionData.nodeTree,
        layout: versionData.layout,
        theme: versionData.theme,
        view: versionData.viewData,
      })
      ElMessage.info('正在预览版本，点击"退出预览"或关闭侧边栏可恢复')
    }
  } catch (e) {
    console.error('预览版本失败:', e)
    ElMessage.error('预览版本失败')
  }
}

function exitPreview() {
  if (!isPreviewing.value || !_prePreviewState) return

  // 恢复预览前的状态
  if (props.mindMap) {
    props.mindMap.setFullData({
      root: _prePreviewState.root,
      layout: _prePreviewState.layout,
      theme: _prePreviewState.theme,
      view: _prePreviewState.view,
    })
  }

  // 恢复 Yjs 同步
  if (props.yjsSync) {
    props.yjsSync.resume()
  }

  _prePreviewState = null
  isPreviewing.value = false
  ElMessage.success('已恢复到编辑状态')
}

async function handleRestore(item) {
  try {
    await ElMessageBox.confirm(
      `确认恢复到「${item.name || '版本 ' + item.versionNumber}」？当前未保存的更改将丢失。`,
      '确认恢复',
      { type: 'warning' }
    )

    // 如果正在预览，先退出预览
    if (isPreviewing.value) {
      exitPreview()
    }

    await restoreVersion(item.id)
    ElMessage.success('版本恢复成功')

    // 从后端获取恢复后的最新数据
    if (props.mindMap) {
      const res = await getVersionDetail(item.id)
      const versionData = res.data
      if (versionData?.nodeTree) {
        props.mindMap.setFullData({
          root: versionData.nodeTree,
          layout: versionData.layout,
          theme: versionData.theme,
          view: versionData.viewData,
        })

        // 通知父组件重新初始化 Yjs，使协作者也看到恢复后的内容
        emit('yjs-reinit', versionData.nodeTree)
      }
    }
    loadVersions()
  } catch (e) {
    if (e !== 'cancel') {
      console.error('恢复版本失败:', e)
      ElMessage.error('恢复版本失败')
    }
  }
}

async function handleDelete(item) {
  try {
    await ElMessageBox.confirm(
      `确认删除「${item.name || '版本 ' + item.versionNumber}」？此操作不可撤销。`,
      '确认删除',
      { type: 'warning' }
    )
    await deleteVersion(item.id)
    ElMessage.success('版本删除成功')
    loadVersions()
  } catch (e) {
    if (e !== 'cancel') {
      console.error('删除版本失败:', e)
      ElMessage.error('删除版本失败')
    }
  }
}
</script>

<style lang="scss" scoped>
.versionHistoryContainer {
  padding: 10px;

  .previewBanner {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    background: #ecf5ff;
    border: 1px solid #b3d8ff;
    border-radius: 4px;
    margin-bottom: 10px;
    font-size: 13px;
    color: #409eff;

    .el-button {
      margin-left: auto;
    }
  }

  .actionBar {
    margin-bottom: 10px;
    text-align: center;
  }

  .versionList {
    min-height: 100px;
    max-height: calc(100vh - 320px);
    overflow-y: auto;
  }

  .emptyTip {
    text-align: center;
    color: #999;
    padding: 40px 0;
    font-size: 14px;
  }

  .versionItem {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 8px;
    border-bottom: 1px solid #f0f0f0;
    transition: background 0.2s;

    &:hover {
      background: #f5f7fa;
    }

    .versionInfo {
      flex: 1;
      min-width: 0;

      .versionName {
        font-size: 13px;
        font-weight: 500;
        color: #333;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      .versionMeta {
        font-size: 12px;
        color: #999;
        margin-top: 4px;
        display: flex;
        gap: 8px;
      }
    }

    .versionActions {
      flex-shrink: 0;
      margin-left: 8px;
    }
  }

  .paginationWrap {
    display: flex;
    justify-content: center;
    margin-top: 12px;
  }
}
</style>
