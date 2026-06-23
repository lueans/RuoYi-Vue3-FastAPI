<template>
  <div class="searchContainer" :class="{ isDark: isDark, show: show }">
    <div class="closeBtnBox">
      <span class="closeBtn" @click="close">
        <el-icon><Close /></el-icon>
      </span>
    </div>
    <div class="searchInputBox">
      <el-input
        ref="searchInputRef"
        placeholder="输入查找内容后按回车键"
        size="small"
        v-model="searchText"
        @keyup.enter.stop="onSearchNext"
        @keydown.stop
        @focus="onFocus"
        @blur="onBlur"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
        <template #append v-if="searchText !== undefined && searchText !== null && searchText !== ''">
          <el-button size="small" @click="showReplaceInput = true">替换</el-button>
        </template>
      </el-input>
      <div class="searchInfo" v-if="showSearchInfo && searchText">
        {{ currentIndex }} / {{ total }}
      </div>
    </div>
    <el-input
      v-if="showReplaceInput"
      ref="replaceInputRef"
      placeholder="请输入替换内容"
      size="small"
      v-model="replaceText"
      style="margin: 12px 0;"
      @keydown.stop
      @focus="onFocus"
      @blur="onBlur"
    >
      <template #prefix>
        <el-icon><Edit /></el-icon>
      </template>
      <template #append>
        <el-button size="small" @click="hideReplaceInput">取消</el-button>
      </template>
    </el-input>
    <div class="btnList" v-if="showReplaceInput">
      <el-button size="small" :disabled="isReadonly" @click="doReplace">替换</el-button>
      <el-button size="small" :disabled="isReadonly" @click="doReplaceAll">全部替换</el-button>
    </div>
    <div
      class="searchResultList"
      :style="{ height: searchResultListHeight + 'px' }"
      v-if="showSearchResultList"
    >
      <div
        class="searchResultItem"
        v-for="(item, index) in searchResultList"
        :key="item.id"
        :title="item.name"
        v-html="item.text"
        @click.stop="onSearchResultItemClick(index)"
      ></div>
      <div class="empty" v-if="searchResultList.length <= 0">
        <span class="iconfont iconwushuju"></span>
        <span class="text">暂无结果</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Close, Search as SearchIcon, Edit } from '@element-plus/icons-vue'
import { Search } from '@element-plus/icons-vue'
import bus from './useEventBus'
import { store } from './useStore'

const props = defineProps({
  mindMap: { type: Object, default: null }
})

const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)

const show = ref(false)
const searchText = ref('')
const replaceText = ref('')
const showReplaceInput = ref(false)
const currentIndex = ref(0)
const total = ref(0)
const showSearchInfo = ref(false)
const searchResultListHeight = ref(0)
const searchResultList = ref([])
const showSearchResultList = ref(false)
const searchInputRef = ref(null)
const replaceInputRef = ref(null)

function isUndef(val) {
  return val === undefined || val === null || val === ''
}

function handleSearchInfoChange(data) {
  currentIndex.value = data.currentIndex + 1
  total.value = data.total
  showSearchInfo.value = true
}

function showSearch() {
  bus.emit('closeSideBar')
  show.value = true
  nextTick(() => {
    searchInputRef.value?.focus()
  })
}

function hideReplaceInput() {
  showReplaceInput.value = false
  replaceText.value = ''
}

function onFocus() {
  props.mindMap?.updateConfig({
    enableAutoEnterTextEditWhenKeydown: false
  })
}

function onBlur() {
  props.mindMap?.updateConfig({
    enableAutoEnterTextEditWhenKeydown: true
  })
}

function blur() {
  searchInputRef.value?.blur?.()
  replaceInputRef.value?.blur?.()
}

function onSearchNext() {
  showSearchResultList.value = true
  props.mindMap?.search?.search(searchText.value)
}

function doReplace() {
  props.mindMap?.search?.replace(replaceText.value, true)
}

function doReplaceAll() {
  props.mindMap?.search?.replaceAll(replaceText.value)
}

function close() {
  show.value = false
  showSearchResultList.value = false
  showSearchInfo.value = false
  total.value = 0
  currentIndex.value = 0
  searchText.value = ''
  hideReplaceInput()
  props.mindMap?.search?.endSearch()
}

function onSearchMatchNodeListChange(list) {
  searchResultList.value = list.map(item => {
    const data = item.data || item.nodeData?.data
    let name = data.text
    const id = data.uid
    if (data.richText) {
      const el = document.createElement('div')
      el.innerHTML = name
      name = el.textContent || ''
    }
    name = name.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    const escaped = (searchText.value || '').trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const reg = new RegExp(escaped, 'g')
    const text = name.replace(reg, a => {
      return `<span class="match">${a}</span>`
    })
    return { data: item, id, text, name }
  })
}

function setSearchResultListHeight() {
  searchResultListHeight.value = window.innerHeight - 267 - 24
}

function onSearchResultItemClick(index) {
  props.mindMap?.search?.jump(index)
}

watch(searchText, (val) => {
  if (isUndef(val)) {
    currentIndex.value = 0
    total.value = 0
    showSearchInfo.value = false
  }
})

onMounted(() => {
  setSearchResultListHeight()
  bus.on('show_search', showSearch)
  bus.on('setData', close)
  window.addEventListener('resize', setSearchResultListHeight)
})

watch(() => props.mindMap, (mm, oldMm) => {
  if (oldMm) {
    oldMm.off('search_info_change', handleSearchInfoChange)
    oldMm.off('node_click', blur)
    oldMm.off('draw_click', blur)
    oldMm.off('expand_btn_click', blur)
    oldMm.off('search_match_node_list_change', onSearchMatchNodeListChange)
    oldMm.keyCommand?.removeShortcut?.('Control+f', showSearch)
  }
  if (mm) {
    mm.on('search_info_change', handleSearchInfoChange)
    mm.on('node_click', blur)
    mm.on('draw_click', blur)
    mm.on('expand_btn_click', blur)
    mm.on('search_match_node_list_change', onSearchMatchNodeListChange)
    mm.keyCommand.addShortcut('Control+f', showSearch)
  }
}, { immediate: true })

onBeforeUnmount(() => {
  bus.off('show_search', showSearch)
  bus.off('setData', close)
  window.removeEventListener('resize', setSearchResultListHeight)
  props.mindMap?.off?.('search_info_change', handleSearchInfoChange)
  props.mindMap?.off?.('node_click', blur)
  props.mindMap?.off?.('draw_click', blur)
  props.mindMap?.off?.('expand_btn_click', blur)
  props.mindMap?.off?.('search_match_node_list_change', onSearchMatchNodeListChange)
  props.mindMap?.keyCommand?.removeShortcut?.('Control+f', showSearch)
})
</script>

<style lang="less" scoped>
.searchContainer {
  position: relative;
  background-color: #fff;
  padding: 16px;
  width: 296px;
  border-radius: 12px;
  box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.1);
  position: fixed;
  top: 110px;
  left: -296px;
  transition: all 0.3s;

  &.isDark {
    background-color: #363b3f;

    .closeBtnBox {
      color: #fff;
      background-color: #363b3f;
    }
  }

  &.show {
    left: 20px;
  }

  .btnList {
    display: flex;
    justify-content: flex-end;
  }

  .closeBtnBox {
    position: absolute;
    right: -5px;
    top: -5px;
    width: 20px;
    height: 20px;
    background-color: #fff;
    border-radius: 50%;
    display: flex;
    justify-content: center;
    align-items: center;
    cursor: pointer;
    box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.1);

    .closeBtn {
      font-size: 16px;
    }
  }

  .searchInputBox {
    position: relative;

    .searchInfo {
      position: absolute;
      right: 70px;
      top: 50%;
      transform: translateY(-50%);
      color: #909090;
      font-size: 14px;
    }
  }

  .searchResultList {
    position: absolute;
    left: 0;
    top: 100%;
    width: 100%;
    background-color: #fff;
    box-shadow: 0 4px 16px 0 rgba(0, 0, 0, 0.1);
    border-radius: 12px;
    margin-top: 5px;
    overflow-y: auto;
    padding: 12px 0;

    .searchResultItem {
      height: 30px;
      line-height: 30px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      padding: 0 12px;
      font-size: 14px;
      cursor: pointer;
      position: relative;
      padding-left: 22px;

      &::before {
        content: '';
        position: absolute;
        left: 10px;
        top: 50%;
        transform: translateY(-50%);
        width: 5px;
        height: 5px;
        background-color: #606266;
        border-radius: 50%;
      }

      &:hover {
        background-color: #f2f4f7;
      }

      :deep(.match) {
        color: #409eff;
        font-weight: bold;
      }
    }

    .empty {
      width: 100%;
      height: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;

      .iconfont {
        font-size: 50px;
        margin-bottom: 20px;
      }

      .text {
        font-size: 14px;
        color: rgba(26, 26, 26, 0.8);
      }
    }
  }
}
</style>
