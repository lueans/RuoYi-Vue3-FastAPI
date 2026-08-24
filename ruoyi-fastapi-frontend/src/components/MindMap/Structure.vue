<template>
  <div class="structurePanel" :class="{ embedded: props.embedded }">
    <details ref="layoutPickerRef" class="layoutPicker" :class="{ isDark }">
      <summary ref="layoutSummaryRef" class="currentLayoutCard">
        <span class="currentLayoutPreview" aria-hidden="true">
          <img v-if="currentLayoutImage" :src="currentLayoutImage" alt="" />
        </span>
        <span class="currentLayoutMeta">
          <strong>{{ currentLayoutName }}</strong>
          <small>当前布局 · 点击更换</small>
        </span>
        <el-icon class="pickerChevron"><ArrowDown /></el-icon>
      </summary>

      <div class="layoutPickerBody">
        <div class="pickerHeading">
          <span>选择其他布局</span>
          <small>应用后可通过顶部撤销恢复</small>
        </div>
        <div class="layoutGroupList">
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
                :aria-pressed="false"
                :disabled="isReadonly"
                @click="useLayout(item)"
              >
                <span class="layoutPreview">
                  <img :src="layoutImgMap[item]" :alt="`${layoutNameMap[item] || item}结构预览`" />
                </span>
                <span class="layoutName">{{ layoutNameMap[item] || item }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </details>
  </div>
</template>

<script setup>
import { ArrowDown } from '@element-plus/icons-vue'
import { store } from './useStore'
import { layoutImgMap, layoutGroupList, layoutList } from './config'

const props = defineProps({
  mindMap: { type: Object, default: null },
  embedded: { type: Boolean, default: false }
})
const emit = defineEmits(['document-meta-change'])

const currentLayout = ref('')
const layoutPickerRef = ref(null)
const layoutSummaryRef = ref(null)
const isDark = computed(() => store.localConfig.isDark)
const isReadonly = computed(() => store.isReadonly)
const layoutNameMap = Object.fromEntries(layoutList.map(item => [item.value, item.name]))
const currentLayoutName = computed(() => layoutNameMap[currentLayout.value] || '默认布局')
const currentLayoutImage = computed(() => layoutImgMap[currentLayout.value] || '')

const layoutGroupListData = computed(() => {
  return layoutGroupList.map(group => {
    const list = [...group.list].filter(item => {
      return item !== currentLayout.value && !['rightFishbone', 'rightFishbone2'].includes(item)
    })
    return {
      name: group.name,
      list
    }
  }).filter(group => group.list.length > 0)
})

function useLayout(layout) {
  if (!props.mindMap || isReadonly.value) return
  currentLayout.value = layout
  props.mindMap.setLayout(layout)
  emit('document-meta-change', { layout })
  if (layoutPickerRef.value) layoutPickerRef.value.open = false
  nextTick(() => layoutSummaryRef.value?.focus())
}

watch(
  [() => props.mindMap, () => store.activeSidebar],
  ([mindMap, activeSidebar]) => {
    if (mindMap && ['baseStyle', 'structure'].includes(activeSidebar)) {
      currentLayout.value = mindMap.getLayout()
    }
  },
  { immediate: true }
)
</script>

<style lang="less" scoped>
.structurePanel {
  width: 100%;
}

.layoutPicker {
  width: 100%;
  margin: 0;

  &.isDark {
    .currentLayoutCard {
      border-color: #454950;
      background: #2f3338;

      &:hover {
        border-color: #5b8def;
      }
    }

    .currentLayoutMeta strong,
    .pickerHeading span {
      color: #e5e6eb;
    }

    .currentLayoutMeta small,
    .pickerHeading small {
      color: #8f959e;
    }

    .currentLayoutPreview {
      background: #25282d;
    }

    .laytouGroup {
      .groupName {
        color: #c9cdd4;
      }

      .layoutItem {
        border-color: #454950;
        background: #2f3338;

        &:hover {
          border-color: #5b8def;
        }
      }

      .layoutName {
        color: #c9cdd4;
      }
    }
  }

  &[open] {
    .pickerChevron {
      transform: rotate(180deg);
    }
  }
}

.currentLayoutCard {
  min-height: 74px;
  display: grid;
  align-items: center;
  grid-template-columns: 92px minmax(0, 1fr) 18px;
  gap: 12px;
  padding: 9px 12px 9px 9px;
  border: 1px solid #dfe3ea;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  list-style: none;
  transition: 0.16s ease;

  &::-webkit-details-marker {
    display: none;
  }

  &:hover {
    border-color: #8fb0ff;
    box-shadow: 0 4px 14px rgba(31, 35, 41, 0.07);
  }

  &:focus-visible {
    outline: 2px solid #3370ff;
    outline-offset: 2px;
  }
}

.currentLayoutPreview {
  width: 92px;
  height: 54px;
  display: block;
  overflow: hidden;
  border-radius: 6px;
  background: #f5f6f7;

  img {
    width: 100%;
    height: 100%;
    display: block;
    object-fit: cover;
  }
}

.currentLayoutMeta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;

  strong,
  small {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  strong {
    color: #1f2329;
    font-size: 13px;
    font-weight: 600;
  }

  small {
    color: #8f959e;
    font-size: 11px;
  }
}

.pickerChevron {
  color: #646a73;
  font-size: 14px;
  transition: transform 0.16s ease;
}

.layoutPickerBody {
  padding-top: 14px;
}

.pickerHeading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;

  span {
    color: #1f2329;
    font-size: 12px;
    font-weight: 600;
  }

  small {
    color: #8f959e;
    font-size: 10px;
  }
}

.layoutGroupList {
  width: 100%;
  padding: 0;

  .laytouGroup {
    width: 100%;
    margin-bottom: 16px;

    &:last-child {
      margin-bottom: 0;
    }

    .groupName {
      font-weight: 500;
      color: #646a73;
      margin-bottom: 8px;
      font-size: 12px;
    }

    .layoutList {
      width: 100%;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;

      .layoutItem {
        width: 100%;
        min-height: 94px;
        display: flex;
        flex-direction: column;
        gap: 6px;
        cursor: pointer;
        appearance: none;
        background: #fff;
        border: 1px solid #e2e5ea;
        color: #4e5969;
        font: inherit;
        transition: 0.16s ease;
        overflow: hidden;
        margin: 0;
        padding: 6px 6px 7px;
        border-radius: 8px;

        &:focus-visible {
          outline: 2px solid #3370ff;
          outline-offset: 2px;
        }

        &:hover {
          border-color: #8fb0ff;
          box-shadow: 0 4px 12px rgba(31, 35, 41, 0.08);
        }

        .layoutPreview {
          position: relative;
          width: 100%;
          height: 58px;
          display: block;
          overflow: hidden;
          border-radius: 5px;
          background: #f5f6f7;

          img {
            width: 100%;
            height: 100%;
            display: block;
            object-fit: cover;
          }
        }

        .layoutName {
          overflow: hidden;
          color: #4e5969;
          font-size: 11px;
          line-height: 1.3;
          text-align: left;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
      }
    }
  }
}
</style>
