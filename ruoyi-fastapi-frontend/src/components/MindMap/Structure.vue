<template>
  <Sidebar ref="sidebarRef" title="结构" open-on-mount>
    <div class="layoutGroupList" :class="{ isDark: isDark }">
      <div
        class="laytouGroup"
        v-for="group in layoutGroupListData"
        :key="group.name"
      >
        <div class="groupName">{{ group.name }}</div>
        <div class="layoutList">
          <button
            class="layoutItem"
            v-for="item in group.list"
            :key="item"
            type="button"
            :aria-label="`使用结构：${layoutNameMap[item] || item}`"
            :aria-pressed="item === currentLayout"
            :disabled="isReadonly"
            @click="useLayout(item)"
            :class="{ active: item === currentLayout }"
          >
            <img :src="layoutImgMap[item]" :alt="`${layoutNameMap[item] || item}结构预览`" />
          </button>
        </div>
      </div>
    </div>
  </Sidebar>
</template>

<script setup>
import Sidebar from './Sidebar.vue'
import { store } from './useStore'
import { layoutImgMap, layoutGroupList, layoutList } from './config'

const props = defineProps({
  mindMap: { type: Object, default: null }
})
const emit = defineEmits(['document-meta-change'])

const sidebarRef = ref(null)
const currentLayout = ref('')
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const layoutNameMap = Object.fromEntries(layoutList.map(item => [item.value, item.name]))

const layoutGroupListData = computed(() => {
  return layoutGroupList.map(group => {
    const list = [...group.list].filter(item => {
      return !['rightFishbone', 'rightFishbone2'].includes(item)
    })
    return {
      name: group.name,
      list
    }
  })
})

function useLayout(layout) {
  if (!props.mindMap || isReadonly.value) return
  currentLayout.value = layout
  props.mindMap.setLayout(layout)
  emit('document-meta-change', { layout })
}

watch(() => store.activeSidebar, (val) => {
  if (val === 'structure') {
    if (props.mindMap) currentLayout.value = props.mindMap.getLayout()
    sidebarRef.value?.open()
  } else {
    sidebarRef.value?.close()
  }
}, { immediate: true })
</script>

<style lang="less" scoped>
.layoutGroupList {
  width: 100%;
  padding: 20px;

  &.isDark {
    .laytouGroup {
      .groupName {
        color: #fff;
      }
    }
  }

  .laytouGroup {
    width: 100%;
    margin-bottom: 12px;

    .groupName {
      font-weight: 500;
      color: #303133;
      margin-bottom: 8px;
      font-size: 14px;
    }

    .layoutList {
      width: 100%;
      display: flex;
      justify-content: space-between;
      flex-wrap: wrap;

      .layoutItem {
        width: 120px;
        height: 70px;
        cursor: pointer;
        appearance: none;
        background: transparent;
        border: 1px solid #e9e9e9;
        transition: all 0.2s;
        overflow: hidden;
        margin-bottom: 12px;
        padding: 5px;
        border-radius: 5px;

        &:focus-visible {
          outline: 3px solid #409eff;
          outline-offset: 2px;
        }

        &:hover {
          box-shadow: 0 1px 2px -2px rgba(0, 0, 0, 0.16),
            0 3px 6px 0 rgba(0, 0, 0, 0.12), 0 5px 12px 4px rgba(0, 0, 0, 0.09);
        }

        &.active {
          border: 1px solid #409eff;
        }

        img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }
      }
    }
  }
}
</style>
